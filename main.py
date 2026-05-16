from fastapi import FastAPI, HTTPException
from sqlalchemy import create_engine, Column, Integer, String, Boolean
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from pydantic import BaseModel

DATABASE_URL = "sqlite:///./tasks.db"
engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(bind=engine)
Base = declarative_base()

class Task(Base):
    __tablename__ = "tasks"
    id = Column(Integer, primary_key=True, index=True)
    title = Column(String, nullable=False)
    done = Column(Boolean, default=False)

Base.metadata.create_all(bind=engine)

class TaskInput(BaseModel):
    title: str

app = FastAPI()

@app.get("/health")
def health_check():
    return {"status": "ok", "message": "To-do API is running!"}

@app.get("/tasks")
def get_tasks():
    db = SessionLocal()
    tasks = db.query(Task).all()
    db.close()
    return {"tasks": [{"id": t.id, "title": t.title, "done": t.done} for t in tasks]}

@app.post("/tasks")
def add_task(task: TaskInput):
    db = SessionLocal()
    new_task = Task(title=task.title)
    db.add(new_task)
    db.commit()
    db.refresh(new_task)
    db.close()
    return {"message": "Task added!", "task": {"id": new_task.id, "title": new_task.title, "done": new_task.done}}

@app.put("/tasks/{task_id}/done")
def complete_task(task_id: int):
    db = SessionLocal()
    task = db.query(Task).filter(Task.id == task_id).first()
    if not task:
        db.close()
        raise HTTPException(status_code=404, detail="Task not found")
    task.done = True
    db.commit()
    db.close()
    return {"message": f"Task {task_id} marked as done!"}

@app.delete("/tasks/{task_id}")
def delete_task(task_id: int):
    db = SessionLocal()
    task = db.query(Task).filter(Task.id == task_id).first()
    if not task:
        db.close()
        raise HTTPException(status_code=404, detail="Task not found")
    db.delete(task)
    db.commit()
    db.close()
    return {"message": f"Task {task_id} deleted!"}