import sqlite3

conn = sqlite3.connect("finance.db")
cursor = conn.cursor()

try:
    cursor.execute("ALTER TABLE income ADD COLUMN recurring BOOLEAN DEFAULT FALSE")
    print("✅ Migration successful: 'recurring' column added to income table")
except Exception as e:
    if "duplicate column name" in str(e):
        print("ℹ️ Column already exists, nothing to do")
    else:
        print(f"❌ Error: {e}")

conn.commit()
conn.close()