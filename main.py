# main.py — your first Python API!
# This file is the heart of your backend service.

from fastapi import FastAPI

# Create the app — this is your API
app = FastAPI()


# This is a "route" — it listens at the /health URL
# When someone visits it, it returns a simple message
@app.get("/health")
def health_check():
    return {"status": "ok", "message": "My API is running!"}


# A second route — a friendly greeting
# Visit /hello/yourname to try it
@app.get("/hello/{name}")
def say_hello(name: str):
    return {"message": f"Hello, {name}! Your API is working 🎉"}


# A third route — returns some example data
# This is what a real API endpoint looks like
@app.get("/items")
def get_items():
    return {
        "items": [
            {"id": 1, "name": "Apple",  "price": 0.50},
            {"id": 2, "name": "Banana", "price": 0.30},
            {"id": 3, "name": "Cherry", "price": 2.00},
        ]
    }
