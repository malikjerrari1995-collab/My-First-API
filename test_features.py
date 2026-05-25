"""
Test all three new features locally (no DB, no API key required).
Run: python test_features.py
"""
import re, io, csv, json, os
from datetime import datetime

# ── replicate helpers from main.py ─────────────────────────────────────────
_DEBIT_TERMS  = {'debit','paid out','withdrawal','withdrawn','ausgabe','soll','belastung',
                 'lastschrift','af','debe','uscita','débit','debet'}
_CREDIT_TERMS = {'credit','paid in','deposit','einnahme','haben','gutschrift','bij','haber',
                 'entrata','crédit','credit'}
_DATE_TERMS   = {'date','datum','buchungstag','valutadatum','buchungsdatum','wertstellung',
                 'wertstellungsdatum','fecha','data','transactiedatum','boekingsdatum'}
_AMOUNT_TERMS = {'amount','value','betrag','umsatz','betrag eur','summe','importe','importo',
                 'bedrag','montant','soll/haben','umsatz eur'}
_BALANCE_TERMS= {'balance','saldo','kontostand'}
_DESC_TERMS   = ['description','memo','narrative','details','verwendungszweck','buchungstext',
                 'auftraggeber','beguenstigter','zahlungsempfaenger','empfaenger','omschrijving',
                 'naam','libelle','concepto','causale','counter party','counterparty','payee',
                 'merchant','reference','transaction','name']
_TRANSFER_TERMS = {'to pot', 'from pot', 'transfer', 'moving money', 'internal'}
_AI_VALID_CATS  = frozenset({'food','transport','entertainment','utilities','rent','shopping','fitness','other'})


def _is_transfer(desc):
    dl = (desc or '').lower()
    return any(t in dl for t in _TRANSFER_TERMS)


def _ai_categorize(descriptions):
    if not descriptions:
        return []
    api_key = os.environ.get('ANTHROPIC_API_KEY', '')
    if not api_key:
        return ['other'] * len(descriptions)
    try:
        import anthropic as _ant
        client = _ant.Anthropic(api_key=api_key)
        numbered = '\n'.join(f'{i+1}. {d}' for i, d in enumerate(descriptions))
        prompt = (
            'Categorize each bank transaction into exactly one of: '
            'food, transport, entertainment, utilities, rent, shopping, fitness, other.\n'
            'Return ONLY a valid JSON array of lowercase strings.\n'
            f'Input ({len(descriptions)} items):\n{numbered}'
        )
        msg = client.messages.create(
            model='claude-sonnet-4-20250514',
            max_tokens=max(256, len(descriptions) * 12),
            messages=[{'role': 'user', 'content': prompt}]
        )
        raw = msg.content[0].text.strip()
        m = re.search(r'\[.*\]', raw, re.DOTALL)
        if m:
            cats = json.loads(m.group())
            result = [c.lower() if c.lower() in _AI_VALID_CATS else 'other'
                      for c in cats[:len(descriptions)]]
            result += ['other'] * (len(descriptions) - len(result))
            return result
    except Exception as e:
        print(f'  [AI error: {e}]')
    return ['other'] * len(descriptions)


def _parse_date(s):
    for fmt in ['%Y-%m-%d','%d/%m/%Y','%m/%d/%Y','%d-%m-%Y','%d.%m.%Y',
                '%d %b %Y','%d %B %Y','%d/%m/%y','%d.%m.%y','%d %b %y','%d %B %y','%Y/%m/%d']:
        try:
            return datetime.strptime(s.strip(), fmt).strftime('%Y-%m-%d')
        except (ValueError, AttributeError):
            continue
    current_year = datetime.today().year
    for fmt in ['%d %b', '%d %B']:
        try:
            return datetime.strptime(f"{s.strip()} {current_year}", fmt + ' %Y').strftime('%Y-%m-%d')
        except (ValueError, AttributeError):
            continue
    return None


def _parse_amount(s):
    if not s:
        return None
    cleaned = str(s).strip().replace('\xa3','').replace('$','').replace('€','').replace('£','')
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
        if desc_col: break
    amount_col = debit_col = credit_col = None
    for i, h in enumerate(hl):
        if debit_col is None and any(t in h for t in _DEBIT_TERMS): debit_col = headers[i]
        if credit_col is None and any(t in h for t in _CREDIT_TERMS): credit_col = headers[i]
    if not debit_col and not credit_col:
        amount_col = next((headers[i] for i, h in enumerate(hl)
                           if any(h == t or h.startswith(t) for t in _AMOUNT_TERMS)), None)
        if not amount_col:
            amount_col = next((headers[i] for i, h in enumerate(hl)
                               if any(t in h for t in _AMOUNT_TERMS)), None)
    return date_col, desc_col, amount_col, debit_col, credit_col


def simulate_import(csv_bytes):
    """Replicate the new import_csv logic (without DB, without actual AI call unless key set)."""
    text = csv_bytes.decode('utf-8')
    all_rows = [r for r in csv.reader(io.StringIO(text))]
    # Find header
    date_hints = _DATE_TERMS | {'date','datum'}
    amt_hints  = _AMOUNT_TERMS | _DEBIT_TERMS | _CREDIT_TERMS | _BALANCE_TERMS
    header_idx = 0
    for i, row in enumerate(all_rows):
        rl = ' '.join(c.lower() for c in row)
        if any(t in rl for t in date_hints) and any(t in rl for t in amt_hints):
            header_idx = i; break
    headers = all_rows[header_idx]
    dict_rows = [dict(zip(headers, r)) for r in all_rows[header_idx+1:] if any(v.strip() for v in r)]
    date_col, desc_col, amount_col, debit_col, credit_col = _detect_csv_columns(headers)

    # First pass
    pending = []
    skipped = 0
    for row in dict_rows:
        date = _parse_date(row.get(date_col, ''))
        if not date: skipped += 1; continue
        desc = (row.get(desc_col, '') or '').strip() or 'Bank transaction'
        if amount_col:
            amount = _parse_amount(row.get(amount_col))
            if amount is None: skipped += 1; continue
            is_expense = amount < 0
            abs_amount = round(abs(amount), 2)
        else:
            debit  = _parse_amount(row.get(debit_col,  '')) if debit_col  else None
            credit = _parse_amount(row.get(credit_col, '')) if credit_col else None
            if debit is not None and debit != 0:
                is_expense, abs_amount = True,  round(abs(debit),  2)
            elif credit is not None and credit != 0:
                is_expense, abs_amount = False, round(abs(credit), 2)
            else:
                skipped += 1; continue
        if abs_amount == 0: skipped += 1; continue
        pending.append((date, desc, is_expense, abs_amount))

    # AI categorize
    expense_idxs = [i for i, (_, desc, is_exp, _) in enumerate(pending)
                    if is_exp and not _is_transfer(desc)]
    ai_cats = _ai_categorize([pending[i][1] for i in expense_idxs])
    cat_map = {expense_idxs[j]: ai_cats[j] for j in range(len(expense_idxs))}

    # Second pass
    expenses = income = transfers = []
    expenses, income, transfers = [], [], []
    for i, (date, desc, is_expense, abs_amount) in enumerate(pending):
        if _is_transfer(desc):
            transfers.append((date, desc, abs_amount))
        elif is_expense:
            expenses.append((date, desc, abs_amount, cat_map.get(i, 'other')))
        else:
            income.append((date, desc, abs_amount))

    return expenses, income, transfers, skipped, headers, date_col, debit_col, credit_col, amount_col


# ── Test data ─────────────────────────────────────────────────────────────
P = '\xa3'

# NatWest with Paid out/in — includes a transfer (To Pot) and negative Paid out value
NATWEST_MIXED = (
    f"Date,Description,Paid out ({P}),Paid in ({P}),Balance ({P})\n"
    f"22/05/2025,TESCO STORES,45.50,,988.25\n"      # expense
    f"21/05/2025,SALARY,,2000.00,1033.75\n"          # income
    f"20/05/2025,To Pot,100.00,,933.75\n"            # transfer
    f"19/05/2025,AMAZON.CO.UK,23.99,,909.76\n"       # expense
    f"18/05/2025,From Pot,,50.00,959.76\n"           # transfer (credit side)
    f"17/05/2025,COUNCIL TAX,120.00,,839.76\n"       # expense
).encode('utf-8')

# NatWest with negative amounts in Paid out (old bug scenario)
NATWEST_NEGATIVE_DEBIT = (
    f"Date,Description,Value,Balance\n"
    f"22/05/2025,TESCO STORES,-45.50,988.25\n"       # negative = expense
    f"21/05/2025,SALARY,2000.00,1033.75\n"           # positive = income
    f"20/05/2025,MOVING MONEY TO SAVINGS,-100.00,933.75\n"  # transfer (negative)
).encode('utf-8')


def run_test(label, csv_bytes, exp_expenses, exp_income, exp_transfers, exp_skipped=0):
    print(f"\n{'='*60}")
    print(f"TEST: {label}")
    print('='*60)
    errors = []

    expenses, income, transfers, skipped, headers, date_col, debit_col, credit_col, amount_col = simulate_import(csv_bytes)

    print(f"  headers   : {headers}")
    print(f"  date={date_col} | amount={amount_col} | debit={debit_col} | credit={credit_col}")
    has_api_key = bool(os.environ.get('ANTHROPIC_API_KEY', ''))
    print(f"  AI key    : {'YES — live categories' if has_api_key else 'NO — all categories will be other'}")

    print(f"  Expenses ({len(expenses)}):")
    for date, desc, amt, cat in expenses:
        print(f"    EXPENSE  {amt:.2f}  '{desc}'  [{cat}]  {date}")

    print(f"  Income ({len(income)}):")
    for date, desc, amt in income:
        print(f"    INCOME   {amt:.2f}  '{desc}'  {date}")

    print(f"  Transfers ({len(transfers)}):")
    for date, desc, amt in transfers:
        print(f"    TRANSFER {amt:.2f}  '{desc}'  {date}")

    print(f"  Skipped   : {skipped}")

    if len(expenses) != exp_expenses:
        errors.append(f"Expected {exp_expenses} expenses, got {len(expenses)}")
    if len(income) != exp_income:
        errors.append(f"Expected {exp_income} income, got {len(income)}")
    if len(transfers) != exp_transfers:
        errors.append(f"Expected {exp_transfers} transfers, got {len(transfers)}")
    if skipped != exp_skipped:
        errors.append(f"Expected {exp_skipped} skipped, got {skipped}")

    if not errors:
        print(f"  [ALL PASS]")
    else:
        for e in errors:
            print(f"  [FAIL] {e}")

    return not errors


# ── _is_transfer unit tests ───────────────────────────────────────────────
print("=== _is_transfer unit tests ===")
transfer_cases = [
    ('To Pot', True), ('FROM POT', True), ('Transfer to savings', True),
    ('Moving Money', True), ('Internal Transfer', True),
    ('TESCO STORES', False), ('SALARY', False), ('AMAZON.CO.UK', False),
    ('HMRC REFUND', False), ('Direct Debit - Council Tax', False),
]
all_ok = True
for desc, expected in transfer_cases:
    got = _is_transfer(desc)
    ok = got == expected
    all_ok = all_ok and ok
    print(f"  {'PASS' if ok else 'FAIL'} _is_transfer({repr(desc)}) = {got}  (expected {expected})")
print(f"  {'[ALL PASS]' if all_ok else '[FAILURES ABOVE]'}")

# ── import simulation tests ───────────────────────────────────────────────
r1 = run_test("NatWest mixed (transfers + expenses + income)", NATWEST_MIXED,
              exp_expenses=3, exp_income=1, exp_transfers=2)
r2 = run_test("NatWest negative debit amounts (fix #1)",       NATWEST_NEGATIVE_DEBIT,
              exp_expenses=1, exp_income=1, exp_transfers=1)

print(f"\n{'='*60}")
print(f"OVERALL: {'ALL TESTS PASSED' if all_ok and r1 and r2 else 'SOME TESTS FAILED'}")
