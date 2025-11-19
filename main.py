import os
from datetime import datetime, timezone
from typing import List, Optional

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from bson import ObjectId

from database import db, create_document, get_documents
from schemas import Task, Timeentry

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# -----------------------------
# Helpers
# -----------------------------

def to_object_id(id_str: str) -> ObjectId:
    try:
        return ObjectId(id_str)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid id")


def serialize(doc: dict):
    if not doc:
        return doc
    doc["id"] = str(doc.pop("_id"))
    # Convert datetimes to isoformat
    for k, v in list(doc.items()):
        if isinstance(v, datetime):
            doc[k] = v.isoformat()
    return doc


# -----------------------------
# Health + schema endpoints
# -----------------------------

@app.get("/")
def read_root():
    return {"message": "Task Time Manager API"}


@app.get("/schema")
def get_schema():
    return {
        "task": Task.model_json_schema(),
        "timeentry": Timeentry.model_json_schema(),
    }


@app.get("/test")
def test_database():
    response = {
        "backend": "✅ Running",
        "database": "❌ Not Available",
        "database_url": None,
        "database_name": None,
        "connection_status": "Not Connected",
        "collections": []
    }

    try:
        if db is not None:
            response["database"] = "✅ Available"
            response["database_url"] = "✅ Configured"
            response["database_name"] = db.name if hasattr(db, 'name') else "✅ Connected"
            response["connection_status"] = "Connected"

            try:
                collections = db.list_collection_names()
                response["collections"] = collections[:10]
                response["database"] = "✅ Connected & Working"
            except Exception as e:
                response["database"] = f"⚠️  Connected but Error: {str(e)[:50]}"
        else:
            response["database"] = "⚠️  Available but not initialized"

    except Exception as e:
        response["database"] = f"❌ Error: {str(e)[:50]}"

    import os as _os
    response["database_url"] = "✅ Set" if _os.getenv("DATABASE_URL") else "❌ Not Set"
    response["database_name"] = "✅ Set" if _os.getenv("DATABASE_NAME") else "❌ Not Set"

    return response


# -----------------------------
# Task endpoints
# -----------------------------

class TaskCreate(BaseModel):
    title: str
    description: Optional[str] = None
    estimated_minutes: Optional[int] = None
    labels: Optional[List[str]] = None


@app.post("/tasks")
def create_task(payload: TaskCreate):
    task = Task(
        title=payload.title,
        description=payload.description,
        estimated_minutes=payload.estimated_minutes,
        labels=payload.labels or [],
    )
    task_id = create_document("task", task)
    doc = db.task.find_one({"_id": ObjectId(task_id)})
    return serialize(doc)


@app.get("/tasks")
def list_tasks():
    items = get_documents("task", {})
    return [serialize(i) for i in items]


@app.patch("/tasks/{task_id}")
def update_task(task_id: str, payload: dict):
    oid = to_object_id(task_id)
    payload.pop("_id", None)
    payload.pop("id", None)
    payload["updated_at"] = datetime.now(timezone.utc)
    result = db.task.update_one({"_id": oid}, {"$set": payload})
    if result.matched_count == 0:
        raise HTTPException(status_code=404, detail="Task not found")
    doc = db.task.find_one({"_id": oid})
    return serialize(doc)


@app.delete("/tasks/{task_id}")
def delete_task(task_id: str):
    oid = to_object_id(task_id)
    db.task.delete_one({"_id": oid})
    # Also remove related running entries optionally
    db.timeentry.delete_many({"task_id": task_id, "is_running": True})
    return {"success": True}


# -----------------------------
# Time entry endpoints (start/stop timer, manual log)
# -----------------------------

class TimeEntryStart(BaseModel):
    note: Optional[str] = None


@app.post("/tasks/{task_id}/timer/start")
def start_timer(task_id: str, payload: TimeEntryStart):
    # Stop any running timer for this task first
    db.timeentry.update_many(
        {"task_id": task_id, "is_running": True},
        {"$set": {"is_running": False, "end_time": datetime.now(timezone.utc)}},
    )

    entry = Timeentry(
        task_id=task_id,
        start_time=datetime.now(timezone.utc),
        end_time=None,
        duration_sec=None,
        note=payload.note,
        is_running=True,
    )
    entry_id = create_document("timeentry", entry)
    doc = db.timeentry.find_one({"_id": ObjectId(entry_id)})
    return serialize(doc)


@app.post("/tasks/{task_id}/timer/stop")
def stop_timer(task_id: str):
    running = db.timeentry.find_one({"task_id": task_id, "is_running": True})
    if not running:
        raise HTTPException(status_code=400, detail="No running timer for this task")

    start_time = running.get("start_time")
    if not start_time:
        raise HTTPException(status_code=500, detail="Running entry missing start_time")

    end_time = datetime.now(timezone.utc)
    duration_sec = int((end_time - start_time).total_seconds())

    db.timeentry.update_one(
        {"_id": running["_id"]},
        {"$set": {"is_running": False, "end_time": end_time, "duration_sec": duration_sec, "updated_at": datetime.now(timezone.utc)}},
    )

    doc = db.timeentry.find_one({"_id": running["_id"]})
    return serialize(doc)


class ManualLog(BaseModel):
    duration_sec: int
    note: Optional[str] = None
    when: Optional[datetime] = None


@app.post("/tasks/{task_id}/log")
def manual_log(task_id: str, payload: ManualLog):
    when = payload.when or datetime.now(timezone.utc)
    entry = Timeentry(
        task_id=task_id,
        start_time=None,
        end_time=None,
        duration_sec=payload.duration_sec,
        note=payload.note,
        is_running=False,
        date=when.date().isoformat(),
    )
    entry_id = create_document("timeentry", entry)
    doc = db.timeentry.find_one({"_id": ObjectId(entry_id)})
    return serialize(doc)


@app.get("/tasks/{task_id}/time")
def list_time_entries(task_id: str):
    items = get_documents("timeentry", {"task_id": task_id})
    return [serialize(i) for i in items]


@app.get("/reports/summary")
def report_summary():
    # Aggregate total time per task
    pipeline = [
        {"$match": {"duration_sec": {"$ne": None}}},
        {"$group": {"_id": "$task_id", "total_sec": {"$sum": "$duration_sec"}}},
    ]
    agg = list(db.timeentry.aggregate(pipeline))

    # Map to task titles
    task_map = {str(t["_id"]): t for t in db.task.find()}
    data = []
    for row in agg:
        task_id = row["_id"]
        total = row["total_sec"]
        task = db.task.find_one({"_id": ObjectId(task_id)}) if ObjectId.is_valid(task_id) else None
        title = task.get("title") if task else task_map.get(task_id, {}).get("title", "Unknown Task")
        data.append({"task_id": task_id, "title": title, "total_sec": int(total)})

    # Also include running timers durations (up to now) for completeness
    running_entries = list(db.timeentry.find({"is_running": True}))
    now = datetime.now(timezone.utc)
    for e in running_entries:
        task_id = e["task_id"]
        inc = int((now - e["start_time"]).total_seconds()) if e.get("start_time") else 0
        found = next((d for d in data if d["task_id"] == task_id), None)
        if found:
            found["total_sec"] += inc
        else:
            task = db.task.find_one({"_id": ObjectId(task_id)}) if ObjectId.is_valid(task_id) else None
            title = task.get("title") if task else "Unknown Task"
            data.append({"task_id": task_id, "title": title, "total_sec": inc})

    return {"items": data}


if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
