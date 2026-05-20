with open("main.py", "r", encoding="utf-8") as f:
    content = f.read()

old = '    return {"message": "Income added!", "income": {"id": new_income.id, "amount": new_income.amount, "source": new_income.source, "description": new_income.description, "date": new_income.date, "recurring": new_income.recurring}} new_income.amount, "source": new_income.source, "description": new_income.description, "date": new_income.date, "recurring": new_income.recurring}}description": new_income.description, "date": new_income.date}}'

new = '    return {"message": "Income added!", "income": {"id": new_income.id, "amount": new_income.amount, "source": new_income.source, "description": new_income.description, "date": new_income.date, "recurring": new_income.recurring}}'

content = content.replace(old, new)

with open("main.py", "w", encoding="utf-8") as f:
    f.write(content)

print("✅ Fixed!")