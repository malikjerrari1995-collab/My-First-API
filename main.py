import resend
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import create_engine, Column, Integer, String, Float, Boolean, func
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from pydantic import BaseModel
from typing import Optional
from datetime import datetime

RESEND_API_KEY = "re_C7p7odaG_PaFJUT87ntWC9DHSKa7QJV1F"
NOTIFICATION_EMAIL = "malikjerrari1995@gmail.com"
resend.api_key = RESEND_API_KEY

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

DATABASE_URL = "sqlite:///./finance.db"
engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(bind=engine)
Base = declarative_base()

class Expense(Base):
    __tablename__ = "expenses"
    id          = Column(Integer, primary_key=True, index=True)
    amount      = Column(Float, nullable=False)
    category    = Column(String, nullable=False)
    description = Column(String, nullable=True)
    date        = Column(String, nullable=False)
    recurring   = Column(Boolean, default=False)

class Income(Base):
    __tablename__ = "income"
    id          = Column(Integer, primary_key=True, index=True)
    amount      = Column(Float, nullable=False)
    source      = Column(String, nullable=False)
    description = Column(String, nullable=True)
    date        = Column(String, nullable=False)

class Budget(Base):
    __tablename__ = "budgets"
    id           = Column(Integer, primary_key=True, index=True)
    category     = Column(String, nullable=False)
    limit_amount = Column(Float, nullable=False)
    month        = Column(String, nullable=False)

class SavingsGoal(Base):
    __tablename__ = "savings_goals"
    id           = Column(Integer, primary_key=True, index=True)
    name         = Column(String, nullable=False)
    target       = Column(Float, nullable=False)
    month        = Column(String, nullable=False)

Base.metadata.create_all(bind=engine)

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

class BudgetInput(BaseModel):
    category:     str
    limit_amount: float
    month:        Optional[str] = None

class SavingsGoalInput(BaseModel):
    name:   str
    target: float
    month:  Optional[str] = None

def get_alert(category, spent, limit):
    if limit <= 0:
        return None
    pct = (spent / limit) * 100
    if pct >= 100:
        return f"OVER BUDGET! You've spent £{spent:.2f} of your £{limit:.2f} {category} budget ({pct:.0f}%)"
    elif pct >= 80:
        return f"Warning — you've used {pct:.0f}% of your {category} budget (£{spent:.2f} of £{limit:.2f})"
    return None

app = FastAPI(title="Expense Tracker API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/health")
def health_check():
    return {"status": "ok", "message": "Expense Tracker API is running!"}

@app.post("/expenses")
def add_expense(expense: ExpenseInput):
    db = SessionLocal()
    date = expense.date or datetime.today().strftime("%Y-%m-%d")
    month = date[:7]
    new_expense = Expense(amount=expense.amount, category=expense.category.lower(), description=expense.description, date=date, recurring=expense.recurring)
    db.add(new_expense)
    db.commit()
    db.refresh(new_expense)
    budget = db.query(Budget).filter(Budget.category == expense.category.lower(), Budget.month == month).first()
    alert = None
    if budget:
        spent = db.query(func.sum(Expense.amount)).filter(Expense.category == expense.category.lower(), Expense.date.startswith(month)).scalar() or 0
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
def get_expenses(category: Optional[str] = Query(None), month: Optional[str] = Query(None)):
    db = SessionLocal()
    query = db.query(Expense)
    if category:
        query = query.filter(Expense.category == category.lower())
    if month:
        query = query.filter(Expense.date.startswith(month))
    expenses = query.order_by(Expense.date.desc()).all()
    total = sum(e.amount for e in expenses)
    db.close()
    return {"total": round(total, 2), "count": len(expenses), "expenses": [{"id": e.id, "amount": e.amount, "category": e.category, "description": e.description, "date": e.date, "recurring": e.recurring} for e in expenses]}

@app.get("/expenses/recurring")
def get_recurring_expenses():
    db = SessionLocal()
    expenses = db.query(Expense).filter(Expense.recurring == True).all()
    total = sum(e.amount for e in expenses)
    db.close()
    return {"message": "Your recurring monthly expenses", "monthly_total": round(total, 2), "count": len(expenses), "expenses": [{"id": e.id, "amount": e.amount, "category": e.category, "description": e.description} for e in expenses]}

@app.put("/expenses/{expense_id}")
def update_expense(expense_id: int, amount: Optional[float] = Query(None), category: Optional[str] = Query(None), description: Optional[str] = Query(None), date: Optional[str] = Query(None), recurring: Optional[bool] = Query(None)):
    db = SessionLocal()
    expense = db.query(Expense).filter(Expense.id == expense_id).first()
    if not expense:
        db.close()
        raise HTTPException(status_code=404, detail="Expense not found")
    if amount is not None:
        expense.amount = amount
    if category is not None:
        expense.category = category.lower()
    if description is not None:
        expense.description = description
    if date is not None:
        expense.date = date
    if recurring is not None:
        expense.recurring = recurring
    db.commit()
    db.refresh(expense)
    db.close()
    return {"message": f"Expense {expense_id} updated!", "expense": {"id": expense.id, "amount": expense.amount, "category": expense.category, "description": expense.description, "date": expense.date, "recurring": expense.recurring}}

@app.delete("/expenses/{expense_id}")
def delete_expense(expense_id: int):
    db = SessionLocal()
    expense = db.query(Expense).filter(Expense.id == expense_id).first()
    if not expense:
        db.close()
        raise HTTPException(status_code=404, detail="Expense not found")
    db.delete(expense)
    db.commit()
    db.close()
    return {"message": f"Expense {expense_id} deleted!"}

@app.post("/income")
def add_income(income: IncomeInput):
    db = SessionLocal()
    date = income.date or datetime.today().strftime("%Y-%m-%d")
    new_income = Income(amount=income.amount, source=income.source, description=income.description, date=date)
    db.add(new_income)
    db.commit()
    db.refresh(new_income)
    db.close()
    return {"message": "Income added!", "income": {"id": new_income.id, "amount": new_income.amount, "source": new_income.source, "description": new_income.description, "date": new_income.date}}

@app.get("/income")
def get_income(month: Optional[str] = Query(None)):
    db = SessionLocal()
    query = db.query(Income)
    if month:
        query = query.filter(Income.date.startswith(month))
    incomes = query.order_by(Income.date.desc()).all()
    total = sum(i.amount for i in incomes)
    db.close()
    return {"total": round(total, 2), "count": len(incomes), "income": [{"id": i.id, "amount": i.amount, "source": i.source, "description": i.description, "date": i.date} for i in incomes]}

@app.post("/budgets")
def set_budget(budget: BudgetInput):
    db = SessionLocal()
    month = budget.month or datetime.today().strftime("%Y-%m")
    existing = db.query(Budget).filter(Budget.category == budget.category.lower(), Budget.month == month).first()
    if existing:
        existing.limit_amount = budget.limit_amount
        db.commit()
        db.refresh(existing)
        db.close()
        return {"message": f"Budget updated for {budget.category} in {month}", "budget": {"category": existing.category, "limit": existing.limit_amount, "month": existing.month}}
    new_budget = Budget(category=budget.category.lower(), limit_amount=budget.limit_amount, month=month)
    db.add(new_budget)
    db.commit()
    db.refresh(new_budget)
    db.close()
    return {"message": f"Budget set for {budget.category} in {month}", "budget": {"category": new_budget.category, "limit": new_budget.limit_amount, "month": new_budget.month}}

@app.get("/budgets")
def get_budgets(month: Optional[str] = Query(None)):
    db = SessionLocal()
    month = month or datetime.today().strftime("%Y-%m")
    budgets = db.query(Budget).filter(Budget.month == month).all()
    result = []
    for b in budgets:
        spent = db.query(func.sum(Expense.amount)).filter(Expense.category == b.category, Expense.date.startswith(month)).scalar() or 0
        spent = round(spent, 2)
        percentage = round((spent / b.limit_amount) * 100, 1) if b.limit_amount > 0 else 0
        remaining = round(b.limit_amount - spent, 2)
        alert = get_alert(b.category, spent, b.limit_amount)
        result.append({"category": b.category, "limit": b.limit_amount, "spent": spent, "remaining": remaining, "percentage": percentage, "status": "over budget" if percentage >= 100 else "warning" if percentage >= 80 else "on track", "alert": alert})
    db.close()
    return {"month": month, "budgets": result}

@app.post("/savings")
def set_savings_goal(goal: SavingsGoalInput):
    db = SessionLocal()
    month = goal.month or datetime.today().strftime("%Y-%m")
    existing = db.query(SavingsGoal).filter(SavingsGoal.name == goal.name, SavingsGoal.month == month).first()
    if existing:
        existing.target = goal.target
        db.commit()
        db.refresh(existing)
        db.close()
        return {"message": "Savings goal updated!", "goal": {"name": existing.name, "target": existing.target, "month": existing.month}}
    new_goal = SavingsGoal(name=goal.name, target=goal.target, month=month)
    db.add(new_goal)
    db.commit()
    db.refresh(new_goal)
    db.close()
    return {"message": "Savings goal created!", "goal": {"name": new_goal.name, "target": new_goal.target, "month": new_goal.month}}

@app.get("/savings/{month}")
def get_savings_progress(month: str):
    db = SessionLocal()
    goals = db.query(SavingsGoal).filter(SavingsGoal.month == month).all()
    total_income = db.query(func.sum(Income.amount)).filter(Income.date.startswith(month)).scalar() or 0
    total_expenses = db.query(func.sum(Expense.amount)).filter(Expense.date.startswith(month)).scalar() or 0
    actual_saved = round(total_income - total_expenses, 2)
    result = []
    for g in goals:
        percentage = round((actual_saved / g.target) * 100, 1) if g.target > 0 else 0
        remaining = round(g.target - actual_saved, 2)
        if actual_saved >= g.target:
            status = "GOAL REACHED!"
        elif percentage >= 75:
            status = "Almost there!"
        elif percentage >= 50:
            status = "Halfway there!"
        else:
            status = "Keep going!"
        result.append({"name": g.name, "target": g.target, "saved_so_far": actual_saved, "remaining": remaining if remaining > 0 else 0, "percentage": percentage, "status": status})
    db.close()
    return {"month": month, "actual_saved": actual_saved, "goals": result}

@app.get("/summary/{month}")
def get_summary(month: str):
    db = SessionLocal()
    total_income = db.query(func.sum(Income.amount)).filter(Income.date.startswith(month)).scalar() or 0
    total_expenses = db.query(func.sum(Expense.amount)).filter(Expense.date.startswith(month)).scalar() or 0
    category_totals = db.query(Expense.category, func.sum(Expense.amount).label("total")).filter(Expense.date.startswith(month)).group_by(Expense.category).all()
    recurring_total = db.query(func.sum(Expense.amount)).filter(Expense.recurring == True, Expense.date.startswith(month)).scalar() or 0
    budgets = db.query(Budget).filter(Budget.month == month).all()
    alerts = []
    for b in budgets:
        spent = db.query(func.sum(Expense.amount)).filter(Expense.category == b.category, Expense.date.startswith(month)).scalar() or 0
        alert = get_alert(b.category, spent, b.limit_amount)
        if alert:
            alerts.append(alert)
    db.close()
    balance = round(total_income - total_expenses, 2)
    return {"month": month, "total_income": round(total_income, 2), "total_expenses": round(total_expenses, 2), "recurring_expenses": round(recurring_total, 2), "balance": balance, "balance_status": "surplus" if balance >= 0 else "deficit", "spending_by_category": [{"category": c, "total": round(t, 2)} for c, t in sorted(category_totals, key=lambda x: x[1], reverse=True)], "alerts": alerts}