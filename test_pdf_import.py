"""
PDF import test — creates real PDFs with reportlab, parses with pdfplumber.
Run: python test_pdf_import.py
"""
import io, re, csv
from datetime import datetime

import pdfplumber
from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfgen import canvas

# ── term sets (exact copies from main.py) ────────────────────────────────────
_DATE_TERMS   = {'date','datum','buchungstag','valutadatum','buchungsdatum','wertstellung',
                 'wertstellungsdatum','fecha','data','transactiedatum','boekingsdatum'}
_AMOUNT_TERMS = {'amount','value','betrag','umsatz','betrag eur','summe','importe','importo',
                 'bedrag','montant','soll/haben','umsatz eur'}
_BALANCE_TERMS= {'balance','saldo','kontostand'}
_DEBIT_TERMS  = {'debit','paid out','withdrawal','withdrawn','ausgabe','soll','belastung',
                 'lastschrift','af','debe','uscita','débit','debet'}
_CREDIT_TERMS = {'credit','paid in','deposit','einnahme','haben','gutschrift','bij','haber',
                 'entrata','crédit'}
_DESC_TERMS   = ['description','memo','narrative','details','verwendungszweck','buchungstext',
                 'auftraggeber','beguenstigter','zahlungsempfaenger','empfaenger','omschrijving',
                 'naam','libelle','concepto','causale','counter party','counterparty','payee',
                 'merchant','reference','transaction','name']


def _parse_date(s):
    for fmt in ['%Y-%m-%d','%d/%m/%Y','%m/%d/%Y','%d-%m-%Y','%d.%m.%Y',
                '%d %b %Y','%d %B %Y','%d/%m/%y','%d.%m.%y','%d %b %y','%d %B %y','%Y/%m/%d']:
        try:
            return datetime.strptime(s.strip(), fmt).strftime('%Y-%m-%d')
        except (ValueError, AttributeError):
            continue
    return None


def _parse_amount(s):
    if not s:
        return None
    cleaned = str(s).strip()
    cleaned = cleaned.replace('\xa3','').replace('$','').replace('€','').replace('£','')
    cleaned = cleaned.replace(' ','').replace('\xa0','').replace('−','-').replace('–','-')
    force_negative = False
    upper = cleaned.upper()
    if upper.endswith('DR'):
        cleaned, force_negative = cleaned[:-2], True
    elif upper.endswith('CR'):
        cleaned = cleaned[:-2]
    if cleaned.startswith('(') and cleaned.endswith(')'):
        cleaned = '-' + cleaned[1:-1]
    cleaned = cleaned.lstrip('+')
    if not cleaned or cleaned in ('-','n/a','n.a.'):
        return None
    if re.search(r',\d{1,2}$', cleaned):
        cleaned = cleaned.replace('.', '').replace(',', '.')
    else:
        cleaned = cleaned.replace(',', '')
    try:
        result = float(cleaned)
        if force_negative:
            result = -abs(result)
        return result
    except ValueError:
        return None


def _detect_csv_columns(headers):
    hl = [h.lower().strip() for h in headers]
    date_col = next((headers[i] for i, h in enumerate(hl) if any(t in h for t in _DATE_TERMS)), None)
    desc_col = None
    for kw in _DESC_TERMS:
        desc_col = next((headers[i] for i, h in enumerate(hl) if kw in h), None)
        if desc_col:
            break
    amount_col = debit_col = credit_col = None
    for i, h in enumerate(hl):
        if debit_col is None and any(t in h for t in _DEBIT_TERMS):
            debit_col = headers[i]
        if credit_col is None and any(t in h for t in _CREDIT_TERMS):
            credit_col = headers[i]
    if not debit_col and not credit_col:
        amount_col = next((headers[i] for i, h in enumerate(hl)
                           if any(h == t or h.startswith(t) for t in _AMOUNT_TERMS)), None)
        if not amount_col:
            amount_col = next((headers[i] for i, h in enumerate(hl)
                               if any(t in h for t in _AMOUNT_TERMS)), None)
    return date_col, desc_col, amount_col, debit_col, credit_col


def _parse_pdf_page_by_words(page):
    """Parse a pdfplumber page using word bounding boxes to reconstruct columns.

    Works for text-layout PDFs (e.g. Nationwide) where extract_table() finds nothing.
    Column headers like 'Paid In(£)' are re-joined by detecting small intra-word gaps
    (< 12pt) vs large inter-column gaps.
    """
    words = page.extract_words(x_tolerance=3, y_tolerance=3)
    if not words:
        return None

    # Group words into lines by y-position (5pt tolerance)
    lines_map = {}
    for word in words:
        y_key = round(word['top'] / 5) * 5
        lines_map.setdefault(y_key, []).append(word)
    sorted_lines = [sorted(lines_map[y], key=lambda w: w['x0']) for y in sorted(lines_map)]

    # Find header line: must contain a date term AND an amount/debit/credit term
    date_hints = _DATE_TERMS | {'date', 'datum'}
    amt_hints  = _AMOUNT_TERMS | _DEBIT_TERMS | _CREDIT_TERMS | _BALANCE_TERMS
    header_line_idx = None
    for i, line in enumerate(sorted_lines):
        line_text = ' '.join(w['text'] for w in line).lower()
        if any(t in line_text for t in date_hints) and any(t in line_text for t in amt_hints):
            header_line_idx = i
            break

    if header_line_idx is None:
        return None

    # Cluster header words into column groups.
    # Words with gap < 12pt are part of the same multi-word column name (e.g. "Paid In(£)").
    header_words = sorted_lines[header_line_idx]
    columns = []          # list of (x0, col_name_str)
    current_group = [header_words[0]]
    for word in header_words[1:]:
        gap = word['x0'] - current_group[-1]['x1']
        if gap < 12:
            current_group.append(word)
        else:
            columns.append((current_group[0]['x0'], ' '.join(w['text'] for w in current_group)))
            current_group = [word]
    columns.append((current_group[0]['x0'], ' '.join(w['text'] for w in current_group)))

    if len(columns) < 2:
        return None

    col_names = [c[1] for c in columns]
    col_x0s   = [c[0] for c in columns]

    # Assign each data-row word to its column by finding the rightmost col_x0 ≤ word's x0
    all_rows = [col_names]
    for line in sorted_lines[header_line_idx + 1:]:
        if not line:
            continue
        row = [''] * len(col_names)
        for word in line:
            best_col = 0
            for ci, cx0 in enumerate(col_x0s):
                if cx0 <= word['x0']:
                    best_col = ci
            existing = row[best_col]
            row[best_col] = (existing + ' ' + word['text']).strip() if existing else word['text']
        all_rows.append(row)

    return all_rows


def extract_pdf_rows(pdf_bytes: bytes):
    """Replicate the proposed _load_rows PDF branch for main.py."""
    all_rows = []

    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        for page in pdf.pages:
            # Strategy 1: bordered table extraction
            table = page.extract_table()
            if table:
                for row in table:
                    all_rows.append([str(v).strip() if v is not None else '' for v in row])
            else:
                # Strategy 2: word-position-based column parsing
                page_rows = _parse_pdf_page_by_words(page)
                if page_rows and len(page_rows) > 1 and len(page_rows[0]) >= 2:
                    # Skip repeated header on subsequent pages
                    start = 1 if all_rows else 0
                    all_rows.extend(page_rows[start:])
                else:
                    # Strategy 3: last-resort per-line text split
                    text = page.extract_text(x_tolerance=3, y_tolerance=3)
                    if text:
                        for line in text.splitlines():
                            cols = [c.strip() for c in re.split(r'\s{2,}', line) if c.strip()]
                            if cols:
                                all_rows.append(cols)

    return all_rows


def simulate_import(all_rows):
    date_hints   = _DATE_TERMS | {'date', 'datum'}
    amount_hints = _AMOUNT_TERMS | _DEBIT_TERMS | _CREDIT_TERMS | _BALANCE_TERMS
    header_idx, fallback_idx = 0, None
    for i, row in enumerate(all_rows):
        rl = ' '.join(str(c).lower() for c in row)
        if any(t in rl for t in date_hints) and any(t in rl for t in amount_hints):
            header_idx = i
            break
        if any(t in rl for t in date_hints) and fallback_idx is None:
            fallback_idx = i
    else:
        if fallback_idx is not None:
            header_idx = fallback_idx

    headers = all_rows[header_idx]
    dict_rows = [dict(zip(headers, row)) for row in all_rows[header_idx + 1:]
                 if any(str(v).strip() for v in row)]
    date_col, desc_col, amount_col, debit_col, credit_col = _detect_csv_columns(headers)
    results = []
    for row in dict_rows:
        date = _parse_date(row.get(date_col, '')) if date_col else None
        if not date:
            results.append(('SKIP', None, str(row.get(desc_col or '', ''))[:30]))
            continue
        if amount_col:
            amount = _parse_amount(row.get(amount_col))
            if amount is None:
                results.append(('SKIP', None, row.get(desc_col or '', '')[:30]))
                continue
            kind = 'EXPENSE' if amount < 0 else 'INCOME'
            amt  = round(abs(amount), 2)
        else:
            debit  = _parse_amount(row.get(debit_col, '')) if debit_col else None
            credit = _parse_amount(row.get(credit_col, '')) if credit_col else None
            if debit and debit > 0:
                kind, amt = 'EXPENSE', round(debit, 2)
            elif credit and credit > 0:
                kind, amt = 'INCOME', round(credit, 2)
            else:
                results.append(('SKIP', None, row.get(desc_col or '', '')[:30]))
                continue
        results.append((kind, amt, (row.get(desc_col or '', '') or 'Bank transaction')[:30]))
    return headers, date_col, debit_col, credit_col, amount_col, results


# ── PDF builders ─────────────────────────────────────────────────────────────

def build_natwest_pdf():
    """NatWest-style: bordered table (pdfplumber extract_table should work)."""
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, topMargin=20*mm, bottomMargin=20*mm,
                            leftMargin=20*mm, rightMargin=20*mm)
    styles = getSampleStyleSheet()
    elements = []
    elements.append(Paragraph("NatWest Bank Statement", styles['Heading1']))
    elements.append(Paragraph("Account: 12345678 | Sort code: 60-00-01", styles['Normal']))
    elements.append(Spacer(1, 6*mm))

    data = [
        ['Date', 'Description', 'Paid in (\xa3)', 'Paid out (\xa3)', 'Balance (\xa3)'],
        ['22/05/2025', 'TESCO STORES 1234', '', '45.50', '988.25'],
        ['21/05/2025', 'SALARY MAY 2025', '2000.00', '', '1033.75'],
        ['20/05/2025', 'AMAZON.CO.UK', '', '23.99', '1009.76'],
        ['19/05/2025', 'DIRECT DEBIT - COUNCIL TAX', '', '120.00', '889.76'],
        ['18/05/2025', 'HMRC TAX REFUND', '312.50', '', '1202.26'],
    ]
    t = Table(data, colWidths=[28*mm, 72*mm, 28*mm, 28*mm, 28*mm])
    t.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,0), colors.HexColor('#003399')),
        ('TEXTCOLOR',  (0,0), (-1,0), colors.white),
        ('FONTNAME',   (0,0), (-1,0), 'Helvetica-Bold'),
        ('FONTSIZE',   (0,0), (-1,-1), 9),
        ('GRID',       (0,0), (-1,-1), 0.5, colors.grey),
        ('ROWBACKGROUNDS', (0,1), (-1,-1), [colors.white, colors.HexColor('#f5f5f5')]),
        ('ALIGN',      (2,0), (-1,-1), 'RIGHT'),
    ]))
    elements.append(t)
    doc.build(elements)
    buf.seek(0)
    return buf.read()


def build_nationwide_pdf():
    """Nationwide-style: plain text layout, no table borders."""
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    c.setFont("Courier", 10)
    y = 800
    lines = [
        "Nationwide Building Society",
        "Account Name: Current Account",
        "Sort Code: 07-00-55   Account Number: 87654321",
        "",
        " Date          Description                     Paid In(\xa3)   Withdrawn(\xa3)   Balance(\xa3)",
        " BROUGHT FORWARD                                                               33.75",
        " 22 May 2025   To Pot                                          100.00          33.75",
        " 20 May 2025   Salary Payment                  2000.00                        1933.75",
        " 19 May 2025   Tesco Stores                                     45.50         1888.25",
        " 18 May 2025   HMRC Refund                      150.00                        2038.25",
        " 17 May 2025   Netflix                                           15.99         2022.26",
    ]
    for line in lines:
        c.drawString(20, y, line)
        y -= 16
    c.save()
    buf.seek(0)
    return buf.read()


# ── Test runner ───────────────────────────────────────────────────────────────

def run_test(label, pdf_bytes, expected_expenses, expected_income):
    print(f"\n{'='*60}")
    print(f"TEST: {label}")
    print('='*60)
    errors = []

    all_rows = extract_pdf_rows(pdf_bytes)
    if not all_rows:
        print("  [FAIL] No rows extracted from PDF")
        return

    headers, date_col, debit_col, credit_col, amount_col, results = simulate_import(all_rows)
    print(f"  Headers   : {headers}")
    print(f"  date={date_col} | amount={amount_col} | debit={debit_col} | credit={credit_col}")
    print(f"  Transactions:")

    exp_count = inc_count = skip_count = 0
    for kind, amt, desc in results:
        status = 'PASS' if kind in ('EXPENSE','INCOME') else 'SKIP'
        print(f"    [{status}] {kind} {amt} '{desc}'")
        if kind == 'EXPENSE':   exp_count += 1
        elif kind == 'INCOME':  inc_count += 1
        else:                   skip_count += 1

    if exp_count != expected_expenses:
        errors.append(f"Expected {expected_expenses} expenses, got {exp_count}")
    if inc_count != expected_income:
        errors.append(f"Expected {expected_income} income, got {inc_count}")

    if not errors:
        print(f"  [ALL PASS] {exp_count} expenses, {inc_count} income, {skip_count} skipped")
    else:
        for e in errors:
            print(f"  [FAIL] {e}")


natwest_pdf    = build_natwest_pdf()
nationwide_pdf = build_nationwide_pdf()

run_test("NatWest PDF (bordered table)",        natwest_pdf,    3, 2)
run_test("Nationwide PDF (text layout)",        nationwide_pdf, 3, 2)
