from fastapi import FastAPI, HTTPException, Query
from sqlalchemy import create_engine, Column, Integer, String, Float, func
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from pydantic import BaseModel
from typing import Optional
from datetime import datetime

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

Base.metadata.create_all(bind=engine)

class ExpenseInput(BaseModel):
    amount:      float
    category:    str
    description: Optional[str] = None
    date:        Optional[str] = None

class IncomeInput(BaseModel):
    amount:      float
    source:      str
    description: Optional[str] = None
    date:        Optional[str] = None

class BudgetInput(BaseModel):
    category:     str
    limit_amount: float
    month:        Optional[str] = None

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

@app.get("/health")
def health_check():
    return {"status": "ok", "message": "Expense Tracker API is running!"}

@app.post("/expenses")
def add_expense(expense: ExpenseInput):
    db = SessionLocal()
    date = expense.date or datetime.today().strftime("%Y-%m-%d")
    month = date[:7]
    new_expense = Expense(amount=expense.amount, category=expense.category.lower(), description=expense.description, date=date)
    db.add(new_expense)
    db.commit()
    db.refresh(new_expense)
    budget = db.query(Budget).filter(Budget.category == expense.category.lower(), Budget.month == month).first()
    alert = None
    if budget:
        spent = db.query(func.sum(Expense.amount)).filter(Expense.category == expense.category.lower(), Expense.date.startswith(month)).scalar() or 0
        alert = get_alert(expense.category, spent, budget.limit_amount)
    db.close()
    response = {"message": "Expense added!", "expense": {"id": new_expense.id, "amount": new_expense.amount, "category": new_expense.category, "description": new_expense.description, "date": new_expense.date}}
    if alert:
        response["alert"] = alert
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
    return {"total": round(total, 2), "count": len(expenses), "expenses": [{"id": e.id, "amount": e.amount, "category": e.category, "description": e.description, "date": e.date} for e in expenses]}

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

@app.get("/summary/{month}")
def get_summary(month: str):
    db = SessionLocal()
    total_income = db.query(func.sum(Income.amount)).filter(Income.date.startswith(month)).scalar() or 0
    total_expenses = db.query(func.sum(Expense.amount)).filter(Expense.date.startswith(month)).scalar() or 0
    category_totals = db.query(Expense.category, func.sum(Expense.amount).label("total")).filter(Expense.date.startswith(month)).group_by(Expense.category).all()
    budgets = db.query(Budget).filter(Budget.month == month).all()
    alerts = []
    for b in budgets:
        spent = db.query(func.sum(Expense.amount)).filter(Expense.category == b.category, Expense.date.startswith(month)).scalar() or 0
        alert = get_alert(b.category, spent, b.limit_amount)
        if alert:
            alerts.append(alert)
    db.close()
    balance = round(total_income - total_expenses, 2)
    return {"month": month, "total_income": round(total_income, 2), "total_expenses": round(total_expenses, 2), "balance": balance, "balance_status": "surplus" if balance >= 0 else "deficit", "spending_by_category": [{"category": c, "total": round(t, 2)} for c, t in sorted(category_totals, key=lambda x: x[1], reverse=True)], "alerts": alerts}