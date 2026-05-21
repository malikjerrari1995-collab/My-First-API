import resend
import csv
import io
from fastapi import FastAPI, HTTPException, Query, Depends, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse, FileResponse
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from sqlalchemy import create_engine, Column, Integer, String, Float, Boolean, func
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from pydantic import BaseModel
from typing import Optional
from datetime import datetime, timedelta
from passlib.context import CryptContext
from jose import JWTError, jwt

# --- Config ---
RESEND_API_KEY = "re_C7p7odaG_PaFJUT87ntWC9DHSKa7QJV1F"
NOTIFICATION_EMAIL = "malikjerrari1995@gmail.com"
SECRET_KEY = "your-super-secret-key-change-this-in-production"
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60 * 24
resend.api_key = RESEND_API_KEY
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="login")

# --- Database ---
DATABASE_URL = "sqlite:///./finance.db"
engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(bind=engine)
Base = declarative_base()

# --- Models ---
class User(Base):
    __tablename__ = "users"
    id       = Column(Integer, primary_key=True, index=True)
    email    = Column(String, unique=True, nullable=False)
    password = Column(String, nullable=False)
    name     = Column(String, nullable=True)

class Expense(Base):
    __tablename__ = "expenses"
    id          = Column(Integer, primary_key=True, index=True)
    user_id     = Column(Integer, nullable=False)
    amount      = Column(Float, nullable=False)
    category    = Column(String, nullable=False)
    description = Column(String, nullable=True)
    date        = Column(String, nullable=False)
    recurring   = Column(Boolean, default=False)

class Income(Base):
    __tablename__ = "income"
    id          = Column(Integer, primary_key=True, index=True)
    user_id     = Column(Integer, nullable=False)
    amount      = Column(Float, nullable=False)
    source      = Column(String, nullable=False)
    description = Column(String, nullable=True)
    date        = Column(String, nullable=False)
    recurring   = Column(Boolean, default=False)

class Budget(Base):
    __tablename__ = "budgets"
    id           = Column(Integer, primary_key=True, index=True)
    user_id      = Column(Integer, nullable=False)
    category     = Column(String, nullable=False)
    limit_amount = Column(Float, nullable=False)
    month        = Column(String, nullable=False)

class SavingsGoal(Base):
    __tablename__ = "savings_goals"
    id      = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, nullable=False)
    name    = Column(String, nullable=False)
    target  = Column(Float, nullable=False)
    month   = Column(String, nullable=False)

class BankToken(Base):
    __tablename__ = "bank_tokens"
    id           = Column(Integer, primary_key=True, index=True)
    user_id      = Column(Integer, nullable=False, unique=True)
    access_token = Column(String, nullable=False)

Base.metadata.create_all(bind=engine)

# --- Input models ---
class UserRegister(BaseModel):
    email:    str
    password: str
    name:     Optional[str] = None

class ExpenseInput(BaseModel):
    amount:      float
    category:    str
    description: Optional[str] = None
    date:        Optional[str] = None
    recurring:   Optional[bool] = False

class IncomeInput(BaseModel):
    amount:      float
    source:      str
    description: Optional[str] = None
    date:        Optional[str] = None
    recurring:   Optional[bool] = False

class BudgetInput(BaseModel):
    category:     str
    limit_amount: float
    month:        Optional[str] = None

class SavingsGoalInput(BaseModel):
    name:   str
    target: float
    month:  Optional[str] = None

# --- Auth helpers ---
def hash_password(password: str):
    return pwd_context.hash(password)

def verify_password(plain: str, hashed: str):
    return pwd_context.verify(plain, hashed)

def create_token(data: dict):
    to_encode = data.copy()
    expire = datetime.utcnow() + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)

def get_current_user(token: str = Depends(oauth2_scheme)):
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        user_id = payload.get("user_id")
        if user_id is None:
            raise HTTPException(status_code=401, detail="Invalid token")
        return user_id
    except JWTError:
        raise HTTPException(status_code=401, detail="Invalid token")

def get_alert(category, spent, limit):
    if limit <= 0:
        return None
    pct = (spent / limit) * 100
    if pct >= 100:
        return f"OVER BUDGET! You've spent £{spent:.2f} of your £{limit:.2f} {category} budget ({pct:.0f}%)"
    elif pct >= 80:
        return f"Warning — you've used {pct:.0f}% of your {category} budget (£{spent:.2f} of £{limit:.2f})"
    return None

def send_alert_email(subject: str, message: str):
    try:
        resend.Emails.send({
            "from": "onboarding@resend.dev",
            "to": NOTIFICATION_EMAIL,
            "subject": subject,
            "html": f"<h2>Expense Tracker Alert</h2><p>{message}</p>"
        })
    except Exception as e:
        print(f"Email failed: {e}")

# --- App ---
app = FastAPI(title="Expense Tracker API", version="2.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- Serve dashboard ---
@app.get("/")
def serve_dashboard():
    return FileResponse("dashboard.html")

# --- Health ---
@app.get("/health")
def health_check():
    return {"status": "ok", "message": "Expense Tracker API v2 is running!"}

# --- Auth ---
@app.post("/register")
def register(user: UserRegister):
    db = SessionLocal()
    existing = db.query(User).filter(User.email == user.email).first()
    if existing:
        db.close()
        raise HTTPException(status_code=400, detail="Email already registered")
    if len(user.password) < 8:
        db.close()
        raise HTTPException(status_code=400, detail="Password must be at least 8 characters")
    if not any(c.isdigit() for c in user.password):
        db.close()
        raise HTTPException(status_code=400, detail="Password must contain at least one number")
    if not any(c.isupper() for c in user.password):
        db.close()
        raise HTTPException(status_code=400, detail="Password must contain at least one uppercase letter")
    new_user = User(email=user.email, password=hash_password(user.password), name=user.name)
    db.add(new_user)
    db.commit()
    db.refresh(new_user)
    db.close()
    token = create_token({"user_id": new_user.id})
    return {"message": "Account created!", "token": token, "name": new_user.name, "email": new_user.email}

@app.post("/login")
def login(form: OAuth2PasswordRequestForm = Depends()):
    db = SessionLocal()
    user = db.query(User).filter(User.email == form.username).first()
    db.close()
    if not user or not verify_password(form.password, user.password):
        raise HTTPException(status_code=401, detail="Invalid email or password")
    token = create_token({"user_id": user.id})
    return {"access_token": token, "token_type": "bearer", "name": user.name, "email": user.email}

# --- Expenses ---
@app.post("/expenses")
def add_expense(expense: ExpenseInput, user_id: int = Depends(get_current_user)):
    db = SessionLocal()
    date = expense.date or datetime.today().strftime("%Y-%m-%d")
    month = date[:7]
    new_expense = Expense(user_id=user_id, amount=expense.amount, category=expense.category.lower(), description=expense.description, date=date, recurring=expense.recurring)
    db.add(new_expense)
    db.commit()
    db.refresh(new_expense)
    budget = db.query(Budget).filter(Budget.user_id == user_id, Budget.category == expense.category.lower(), Budget.month == month).first()
    alert = None
    if budget:
        spent = db.query(func.sum(Expense.amount)).filter(Expense.user_id == user_id, Expense.category == expense.category.lower(), Expense.date.startswith(month)).scalar() or 0
        alert = get_alert(expense.category, spent, budget.limit_amount)
        if alert:
            send_alert_email(f"Budget Alert - {expense.category.title()}", alert)
    db.close()
    response = {"message": "Expense added!", "expense": {"id": new_expense.id, "amount": new_expense.amount, "category": new_expense.category, "description": new_expense.description, "date": new_expense.date, "recurring": new_expense.recurring}}
    if alert:
        response["alert"] = alert
        response["email_sent"] = True
    return response

@app.get("/expenses")
def get_expenses(category: Optional[str] = Query(None), month: Optional[str] = Query(None), user_id: int = Depends(get_current_user)):
    db = SessionLocal()
    query = db.query(Expense).filter(Expense.user_id == user_id)
    if category:
        query = query.filter(Expense.category == category.lower())
    if month:
        query = query.filter(Expense.date.startswith(month))
    expenses = query.order_by(Expense.date.desc()).all()
    total = sum(e.amount for e in expenses)
    db.close()
    return {"total": round(total, 2), "count": len(expenses), "expenses": [{"id": e.id, "amount": e.amount, "category": e.category, "description": e.description, "date": e.date, "recurring": e.recurring} for e in expenses]}

@app.get("/expenses/recurring")
def get_recurring_expenses(user_id: int = Depends(get_current_user)):
    db = SessionLocal()
    expenses = db.query(Expense).filter(Expense.user_id == user_id, Expense.recurring == True).all()
    total = sum(e.amount for e in expenses)
    db.close()
    return {"message": "Your recurring monthly expenses", "monthly_total": round(total, 2), "count": len(expenses), "expenses": [{"id": e.id, "amount": e.amount, "category": e.category, "description": e.description} for e in expenses]}

@app.put("/expenses/{expense_id}")
def update_expense(expense_id: int, amount: Optional[float] = Query(None), category: Optional[str] = Query(None), description: Optional[str] = Query(None), date: Optional[str] = Query(None), recurring: Optional[bool] = Query(None), user_id: int = Depends(get_current_user)):
    db = SessionLocal()
    expense = db.query(Expense).filter(Expense.id == expense_id, Expense.user_id == user_id).first()
    if not expense:
        db.close()
        raise HTTPException(status_code=404, detail="Expense not found")
    if amount is not None: expense.amount = amount
    if category is not None: expense.category = category.lower()
    if description is not None: expense.description = description
    if date is not None: expense.date = date
    if recurring is not None: expense.recurring = recurring
    db.commit()
    db.refresh(expense)
    db.close()
    return {"message": f"Expense {expense_id} updated!", "expense": {"id": expense.id, "amount": expense.amount, "category": expense.category, "description": expense.description, "date": expense.date, "recurring": expense.recurring}}

@app.delete("/expenses/{expense_id}")
def delete_expense(expense_id: int, user_id: int = Depends(get_current_user)):
    db = SessionLocal()
    expense = db.query(Expense).filter(Expense.id == expense_id, Expense.user_id == user_id).first()
    if not expense:
        db.close()
        raise HTTPException(status_code=404, detail="Expense not found")
    db.delete(expense)
    db.commit()
    db.close()
    return {"message": f"Expense {expense_id} deleted!"}

@app.delete("/income/{income_id}")
def delete_income(income_id: int, user_id: int = Depends(get_current_user)):
    db = SessionLocal()
    income = db.query(Income).filter(Income.id == income_id, Income.user_id == user_id).first()
    if not income:
        db.close()
        raise HTTPException(status_code=404, detail="Income not found")
    db.delete(income)
    db.commit()
    db.close()
    return {"message": f"Income {income_id} deleted!"}

# --- Income ---
@app.post("/income")
def add_income(income: IncomeInput, user_id: int = Depends(get_current_user)):
    db = SessionLocal()
    date = income.date or datetime.today().strftime("%Y-%m-%d")
    new_income = Income(user_id=user_id, amount=income.amount, source=income.source, description=income.description, date=date, recurring=income.recurring)
    db.add(new_income)
    db.commit()
    db.refresh(new_income)
    db.close()
    return {"message": "Income added!", "income": {"id": new_income.id, "amount": new_income.amount, "source": new_income.source, "description": new_income.description, "date": new_income.date, "recurring": new_income.recurring}}

@app.get("/income")
def get_income(month: Optional[str] = Query(None), user_id: int = Depends(get_current_user)):
    db = SessionLocal()
    query = db.query(Income).filter(Income.user_id == user_id)
    if month:
        query = query.filter(Income.date.startswith(month))
    incomes = query.order_by(Income.date.desc()).all()
    total = sum(i.amount for i in incomes)
    db.close()
    return {"total": round(total, 2), "count": len(incomes), "income": [{"id": i.id, "amount": i.amount, "source": i.source, "description": i.description, "date": i.date} for i in incomes]}

# --- Budgets ---
@app.post("/budgets")
def set_budget(budget: BudgetInput, user_id: int = Depends(get_current_user)):
    db = SessionLocal()
    month = budget.month or datetime.today().strftime("%Y-%m")
    existing = db.query(Budget).filter(Budget.user_id == user_id, Budget.category == budget.category.lower(), Budget.month == month).first()
    if existing:
        existing.limit_amount = budget.limit_amount
        db.commit()
        db.refresh(existing)
        db.close()
        return {"message": f"Budget updated for {budget.category} in {month}", "budget": {"category": existing.category, "limit": existing.limit_amount, "month": existing.month}}
    new_budget = Budget(user_id=user_id, category=budget.category.lower(), limit_amount=budget.limit_amount, month=month)
    db.add(new_budget)
    db.commit()
    db.refresh(new_budget)
    db.close()
    return {"message": f"Budget set for {budget.category} in {month}", "budget": {"category": new_budget.category, "limit": new_budget.limit_amount, "month": new_budget.month}}

@app.get("/budgets")
def get_budgets(month: Optional[str] = Query(None), user_id: int = Depends(get_current_user)):
    db = SessionLocal()
    month = month or datetime.today().strftime("%Y-%m")
    budgets = db.query(Budget).filter(Budget.user_id == user_id, Budget.month == month).all()
    result = []
    for b in budgets:
        spent = db.query(func.sum(Expense.amount)).filter(Expense.user_id == user_id, Expense.category == b.category, Expense.date.startswith(month)).scalar() or 0
        spent = round(spent, 2)
        percentage = round((spent / b.limit_amount) * 100, 1) if b.limit_amount > 0 else 0
        remaining = round(b.limit_amount - spent, 2)
        alert = get_alert(b.category, spent, b.limit_amount)
        result.append({"category": b.category, "limit": b.limit_amount, "spent": spent, "remaining": remaining, "percentage": percentage, "status": "over budget" if percentage >= 100 else "warning" if percentage >= 80 else "on track", "alert": alert})
    db.close()
    return {"month": month, "budgets": result}

# --- Savings ---
@app.post("/savings")
def set_savings_goal(goal: SavingsGoalInput, user_id: int = Depends(get_current_user)):
    db = SessionLocal()
    month = goal.month or datetime.today().strftime("%Y-%m")
    existing = db.query(SavingsGoal).filter(SavingsGoal.user_id == user_id, SavingsGoal.name == goal.name, SavingsGoal.month == month).first()
    if existing:
        existing.target = goal.target
        db.commit()
        db.refresh(existing)
        db.close()
        return {"message": "Savings goal updated!", "goal": {"name": existing.name, "target": existing.target, "month": existing.month}}
    new_goal = SavingsGoal(user_id=user_id, name=goal.name, target=goal.target, month=month)
    db.add(new_goal)
    db.commit()
    db.refresh(new_goal)
    db.close()
    return {"message": "Savings goal created!", "goal": {"name": new_goal.name, "target": new_goal.target, "month": new_goal.month}}

@app.get("/savings/{month}")
def get_savings_progress(month: str, user_id: int = Depends(get_current_user)):
    db = SessionLocal()
    goals = db.query(SavingsGoal).filter(SavingsGoal.user_id == user_id, SavingsGoal.month == month).all()
    total_income = db.query(func.sum(Income.amount)).filter(Income.user_id == user_id, Income.date.startswith(month)).scalar() or 0
    total_expenses = db.query(func.sum(Expense.amount)).filter(Expense.user_id == user_id, Expense.date.startswith(month)).scalar() or 0
    actual_saved = round(total_income - total_expenses, 2)
    result = []
    for g in goals:
        percentage = round((actual_saved / g.target) * 100, 1) if g.target > 0 else 0
        remaining = round(g.target - actual_saved, 2)
        if actual_saved >= g.target: status = "GOAL REACHED!"
        elif percentage >= 75: status = "Almost there!"
        elif percentage >= 50: status = "Halfway there!"
        else: status = "Keep going!"
        result.append({"name": g.name, "target": g.target, "saved_so_far": actual_saved, "remaining": remaining if remaining > 0 else 0, "percentage": percentage, "status": status})
    db.close()
    return {"month": month, "actual_saved": actual_saved, "goals": result}

# --- Summary ---
@app.get("/summary/{month}")
def get_summary(month: str, user_id: int = Depends(get_current_user)):
    db = SessionLocal()
    total_income = db.query(func.sum(Income.amount)).filter(Income.user_id == user_id, Income.date.startswith(month)).scalar() or 0
    total_expenses = db.query(func.sum(Expense.amount)).filter(Expense.user_id == user_id, Expense.date.startswith(month)).scalar() or 0
    category_totals = db.query(Expense.category, func.sum(Expense.amount).label("total")).filter(Expense.user_id == user_id, Expense.date.startswith(month)).group_by(Expense.category).all()
    recurring_total = db.query(func.sum(Expense.amount)).filter(Expense.user_id == user_id, Expense.recurring == True, Expense.date.startswith(month)).scalar() or 0
    budgets = db.query(Budget).filter(Budget.user_id == user_id, Budget.month == month).all()
    alerts = []
    for b in budgets:
        spent = db.query(func.sum(Expense.amount)).filter(Expense.user_id == user_id, Expense.category == b.category, Expense.date.startswith(month)).scalar() or 0
        alert = get_alert(b.category, spent, b.limit_amount)
        if alert: alerts.append(alert)
    db.close()
    balance = round(total_income - total_expenses, 2)
    return {"month": month, "total_income": round(total_income, 2), "total_expenses": round(total_expenses, 2), "recurring_expenses": round(recurring_total, 2), "balance": balance, "balance_status": "surplus" if balance >= 0 else "deficit", "spending_by_category": [{"category": c, "total": round(t, 2)} for c, t in sorted(category_totals, key=lambda x: x[1], reverse=True)], "alerts": alerts}

# --- Export ---
@app.get("/export/{month}")
def export_expenses(month: str, user_id: int = Depends(get_current_user)):
    db = SessionLocal()
    expenses = db.query(Expense).filter(Expense.user_id == user_id, Expense.date.startswith(month)).order_by(Expense.date.desc()).all()
    income = db.query(Income).filter(Income.user_id == user_id, Income.date.startswith(month)).order_by(Income.date.desc()).all()
    db.close()
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["EXPENSES"])
    writer.writerow(["ID", "Date", "Category", "Description", "Amount", "Recurring"])
    for e in expenses:
        writer.writerow([e.id, e.date, e.category, e.description or "", f"£{e.amount:.2f}", "Yes" if e.recurring else "No"])
    writer.writerow([])
    writer.writerow(["INCOME"])
    writer.writerow(["ID", "Date", "Source", "Description", "Amount"])
    for i in income:
        writer.writerow([i.id, i.date, i.source, i.description or "", f"£{i.amount:.2f}"])
    output.seek(0)
    return StreamingResponse(io.BytesIO(output.getvalue().encode()), media_type="text/csv", headers={"Content-Disposition": f"attachment; filename=finance_{month}.csv"})

# --- Bank Statement Import (CSV + Excel) ---
def _detect_csv_columns(headers):
    hl = [h.lower().strip() for h in headers]
    date_col = next((headers[i] for i, h in enumerate(hl) if 'date' in h), None)
    desc_col = None
    for kw in ['description', 'memo', 'narrative', 'details', 'counter party', 'counterparty', 'payee', 'merchant', 'reference', 'transaction', 'name']:
        desc_col = next((headers[i] for i, h in enumerate(hl) if kw in h), None)
        if desc_col:
            break
    amount_col = next((headers[i] for i, h in enumerate(hl) if h in ('amount', 'value') or h.startswith('amount')), None)
    debit_col = credit_col = None
    if not amount_col:
        for i, h in enumerate(hl):
            if 'debit' in h or 'paid out' in h or 'withdrawal' in h:
                debit_col = headers[i]
            elif 'credit' in h or 'paid in' in h or 'deposit' in h:
                credit_col = headers[i]
        if not debit_col and not credit_col:
            amount_col = next((headers[i] for i, h in enumerate(hl) if 'amount' in h or 'value' in h), None)
    return date_col, desc_col, amount_col, debit_col, credit_col

def _parse_date(s):
    for fmt in ['%Y-%m-%d', '%d/%m/%Y', '%m/%d/%Y', '%d-%m-%Y', '%d %b %Y', '%d/%m/%y', '%Y/%m/%d']:
        try:
            return datetime.strptime(s.strip(), fmt).strftime('%Y-%m-%d')
        except (ValueError, AttributeError):
            continue
    return None

def _parse_amount(s):
    if not s:
        return None
    cleaned = str(s).strip().replace('£', '').replace('$', '').replace(',', '').replace(' ', '')
    if not cleaned or cleaned == '-':
        return None
    try:
        return float(cleaned)
    except ValueError:
        return None

def _load_rows(content: bytes, filename: str):
    """Return (headers, list_of_dicts) scanning past any metadata rows."""
    fname = (filename or '').lower()
    all_rows = []

    if fname.endswith('.xlsx') or fname.endswith('.xls'):
        import openpyxl
        wb = openpyxl.load_workbook(io.BytesIO(content), read_only=True, data_only=True)
        ws = wb.active
        for row in ws.iter_rows(values_only=True):
            all_rows.append([str(v) if v is not None else '' for v in row])
        wb.close()
    elif fname.endswith('.pdf'):
        import pdfplumber
        with pdfplumber.open(io.BytesIO(content)) as pdf:
            for page in pdf.pages:
                table = page.extract_table()
                if table:
                    for row in table:
                        all_rows.append([str(v) if v is not None else '' for v in row])
    else:
        try:
            text = content.decode('utf-8-sig')
        except UnicodeDecodeError:
            text = content.decode('latin-1')
        for row in csv.reader(io.StringIO(text)):
            all_rows.append([str(v) for v in row])

    # Find the header row: first row that contains a cell with 'date' in it
    header_idx = 0
    for i, row in enumerate(all_rows):
        if any('date' in str(c).lower() for c in row):
            header_idx = i
            break

    headers = all_rows[header_idx]
    dict_rows = []
    for row in all_rows[header_idx + 1:]:
        if not any(v.strip() for v in row):
            continue  # skip blank rows
        dict_rows.append(dict(zip(headers, row)))

    return headers, dict_rows

@app.post("/bank/import/csv")
async def import_csv(file: UploadFile = File(...), user_id: int = Depends(get_current_user)):
    content = await file.read()
    try:
        headers, rows = _load_rows(content, file.filename or '')
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Could not read file: {e}")

    if not headers:
        raise HTTPException(status_code=400, detail="No headers found in file")

    date_col, desc_col, amount_col, debit_col, credit_col = _detect_csv_columns(headers)
    if not date_col:
        raise HTTPException(status_code=400, detail=f"No date column found. Columns: {', '.join(h for h in headers if h)}")
    if not amount_col and not debit_col and not credit_col:
        raise HTTPException(status_code=400, detail=f"No amount column found. Columns: {', '.join(h for h in headers if h)}")

    db = SessionLocal()
    imported_expenses = imported_income = skipped = 0

    for row in rows:
        date = _parse_date(row.get(date_col, ''))
        if not date:
            skipped += 1
            continue

        desc = row.get(desc_col, '').strip() if desc_col else 'Bank transaction'
        desc = desc or 'Bank transaction'

        if amount_col:
            amount = _parse_amount(row.get(amount_col))
            if amount is None:
                skipped += 1
                continue
            is_expense = amount < 0
            abs_amount = round(abs(amount), 2)
        else:
            debit = _parse_amount(row.get(debit_col, '')) if debit_col else None
            credit = _parse_amount(row.get(credit_col, '')) if credit_col else None
            if debit and debit > 0:
                is_expense, abs_amount = True, round(debit, 2)
            elif credit and credit > 0:
                is_expense, abs_amount = False, round(credit, 2)
            else:
                skipped += 1
                continue

        if abs_amount == 0:
            skipped += 1
            continue

        if is_expense:
            exists = db.query(Expense).filter(
                Expense.user_id == user_id, Expense.amount == abs_amount,
                Expense.date == date, Expense.description == desc
            ).first()
            if not exists:
                db.add(Expense(user_id=user_id, amount=abs_amount, category='other', description=desc, date=date, recurring=False))
                imported_expenses += 1
        else:
            exists = db.query(Income).filter(
                Income.user_id == user_id, Income.amount == abs_amount,
                Income.date == date, Income.description == desc
            ).first()
            if not exists:
                db.add(Income(user_id=user_id, amount=abs_amount, source='Bank Import', description=desc, date=date, recurring=False))
                imported_income += 1

    db.commit()
    db.close()

    parts = []
    if imported_expenses:
        parts.append(f"{imported_expenses} expense{'s' if imported_expenses != 1 else ''}")
    if imported_income:
        parts.append(f"{imported_income} income entr{'ies' if imported_income != 1 else 'y'}")
    message = f"Imported {' and '.join(parts)}!" if parts else "No new transactions found (all already imported or skipped)"
    return {"message": message, "imported_expenses": imported_expenses, "imported_income": imported_income, "skipped": skipped}

# --- AI Insights ---
@app.get("/insights/{month}")
def get_insights(month: str, user_id: int = Depends(get_current_user)):
    db = SessionLocal()
    total_income = db.query(func.sum(Income.amount)).filter(Income.user_id == user_id, Income.date.startswith(month)).scalar() or 0
    total_expenses = db.query(func.sum(Expense.amount)).filter(Expense.user_id == user_id, Expense.date.startswith(month)).scalar() or 0
    category_totals = db.query(Expense.category, func.sum(Expense.amount).label("total")).filter(Expense.user_id == user_id, Expense.date.startswith(month)).group_by(Expense.category).all()
    budgets = db.query(Budget).filter(Budget.user_id == user_id, Budget.month == month).all()
    goals = db.query(SavingsGoal).filter(SavingsGoal.user_id == user_id, SavingsGoal.month == month).all()
    recurring_total = db.query(func.sum(Expense.amount)).filter(Expense.user_id == user_id, Expense.recurring == True, Expense.date.startswith(month)).scalar() or 0
    db.close()

    insights = []
    balance = total_income - total_expenses

    if total_income > 0:
        expense_pct = round((total_expenses / total_income) * 100, 1)
        if expense_pct >= 90:
            insights.append({"type": "warning", "icon": "⚠️", "title": "High spending alert", "message": f"You've spent {expense_pct}% of your income this month. Try to keep it under 80% to maintain a healthy balance."})
        elif expense_pct >= 70:
            insights.append({"type": "info", "icon": "📊", "title": "Spending on track", "message": f"You've spent {expense_pct}% of your income. You're doing well but keep an eye on your spending."})
        else:
            insights.append({"type": "success", "icon": "🎉", "title": "Excellent spending habits", "message": f"You've only spent {expense_pct}% of your income this month. Keep it up!"})

    if category_totals:
        top_category = max(category_totals, key=lambda x: x[1])
        pct_of_expenses = round((top_category[1] / total_expenses) * 100, 1) if total_expenses > 0 else 0
        insights.append({"type": "info", "icon": "🏆", "title": "Top spending category", "message": f"Your biggest expense is {top_category[0]} at £{top_category[1]:.2f}, which is {pct_of_expenses}% of your total spending."})

    if recurring_total > 0 and total_income > 0:
        recurring_pct = round((recurring_total / total_income) * 100, 1)
        insights.append({"type": "info", "icon": "🔁", "title": "Fixed monthly costs", "message": f"Your recurring expenses total £{recurring_total:.2f}, which is {recurring_pct}% of your income."})

    for b in budgets:
        db = SessionLocal()
        spent = db.query(func.sum(Expense.amount)).filter(Expense.user_id == user_id, Expense.category == b.category, Expense.date.startswith(month)).scalar() or 0
        db.close()
        pct = round((spent / b.limit_amount) * 100, 1) if b.limit_amount > 0 else 0
        if pct >= 100:
            insights.append({"type": "danger", "icon": "🚨", "title": f"{b.category.title()} budget exceeded", "message": f"You've gone over your {b.category} budget by £{spent - b.limit_amount:.2f}. Consider reducing {b.category} spending next month."})
        elif pct >= 80:
            insights.append({"type": "warning", "icon": "⚠️", "title": f"{b.category.title()} budget warning", "message": f"You've used {pct}% of your {b.category} budget. Only £{b.limit_amount - spent:.2f} remaining."})

    for g in goals:
        actual_saved = total_income - total_expenses
        if actual_saved >= g.target:
            insights.append({"type": "success", "icon": "🎯", "title": f"{g.name} goal reached!", "message": f"Congratulations! You've hit your {g.name} savings goal of £{g.target:.2f} this month!"})
        else:
            remaining = g.target - actual_saved
            insights.append({"type": "info", "icon": "🎯", "title": f"{g.name} progress", "message": f"You need £{remaining:.2f} more to hit your {g.name} goal. Try cutting back on non-essential spending."})

    if balance > 0:
        insights.append({"type": "success", "icon": "💰", "title": "Positive balance", "message": f"Great job! You have £{balance:.2f} left over this month. Consider putting it towards your savings goals."})
    elif balance < 0:
        insights.append({"type": "danger", "icon": "🔴", "title": "Negative balance", "message": f"You've spent £{abs(balance):.2f} more than you earned this month. Review your expenses to get back on track."})

# Savings opportunity insight
    if total_income > 0 and total_expenses > 0:
        food_total = sum(t[1] for t in category_totals if t[0] == "food")
        if food_total > 0:
            saving = round(food_total * 0.1, 2)
            insights.append({"type": "info", "icon": "💡", "title": "Savings opportunity", "message": f"If you reduced your food spending by 10%, you could save an extra £{saving:.2f} this month."})

    # Savings goal timeline
    for g in goals:
        actual_saved = total_income - total_expenses
        if actual_saved > 0 and actual_saved < g.target:
            months_needed = round(g.target / actual_saved, 1)
            insights.append({"type": "info", "icon": "📅", "title": f"{g.name} timeline", "message": f"At your current savings rate of £{actual_saved:.2f}/month, you'll hit your {g.name} goal in {months_needed} months."})

    # Income tip
    if total_income > 0:
        monthly_savings = total_income - total_expenses
        annual_savings = round(monthly_savings * 12, 2)
        if monthly_savings > 0:
            insights.append({"type": "success", "icon": "📈", "title": "Annual savings projection", "message": f"If you keep this up, you'll save £{annual_savings:.2f} over the next 12 months!"})
    if not insights:
        insights.append({"type": "info", "icon": "💡", "title": "Add more data", "message": "Add your income, expenses and budgets to get personalised insights for this month."})

    return {"month": month, "insights": insights}