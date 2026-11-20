import json
import os
import threading
import time
from datetime import date, datetime, timedelta
from flask import Flask, jsonify, render_template, request
import click
import icalendar
import requests
import re
import uuid
from sqlalchemy import Column, MetaData, String, Table, Text, create_engine, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from dotenv import load_dotenv

# Load settings (FEED_URL, DATABASE_URL, ...) from a .env file next to this file,
# if one exists. Used for local development; on Render the variables come from the
# dashboard, and real environment variables always take priority over the file.
load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"))

app = Flask(__name__)

# iCal feed URL. Keep this out of source control: it contains a private token.
# Set it as the FEED_URL environment variable (Render dashboard -> Environment).
FEED_URL = os.environ.get("FEED_URL", "")


# ---------------------------------------------------------------------------
# Database
# ---------------------------------------------------------------------------
# On Render, DATABASE_URL is provided by the linked Postgres database.
# Locally it falls back to a SQLite file so the app runs without Postgres.
def _database_url():
    url = os.environ.get("DATABASE_URL", "sqlite:///tasks.db")
    # SQLAlchemy needs an explicit driver name for psycopg 3
    if url.startswith("postgres://"):
        url = "postgresql+psycopg://" + url[len("postgres://"):]
    elif url.startswith("postgresql://"):
        url = "postgresql+psycopg://" + url[len("postgresql://"):]
    return url


engine = create_engine(_database_url(), pool_pre_ping=True, future=True)
metadata = MetaData()

tasks_table = Table(
    "tasks",
    metadata,
    Column("uid", String(255), primary_key=True),
    Column("title", Text, nullable=False, default=""),
    Column("start", String(64), nullable=False, default=""),
    Column("status", String(32), nullable=False, default="Not started"),
    Column("subject", String(255), nullable=False, default=""),
    Column("priority", String(32), nullable=False, default=""),
    Column("task_type", String(32), nullable=False, default=""),
    Column("effort_level", String(32), nullable=False, default=""),
)

metadata.create_all(engine)

# Maps the JSON/API field names used by the frontend to database columns
FIELD_TO_COLUMN = {
    "uid": "uid",
    "title": "title",
    "start": "start",
    "status": "status",
    "subject": "subject",
    "priority": "priority",
    "taskType": "task_type",
    "effortLevel": "effort_level",
}
COLUMN_TO_FIELD = {v: k for k, v in FIELD_TO_COLUMN.items()}

# Fields the frontend is allowed to change through /api/tasks/update
EDITABLE_FIELDS = {"title", "start", "status", "subject", "priority", "taskType", "effortLevel"}

def get_start_of_current_week():
    """Returns a datetime object representing Monday 00:00:00 of the current week."""
    today = date.today()
    monday = today - timedelta(days=today.weekday())
    return datetime.combine(monday, datetime.min.time())


def parse_event_datetime(dt_val):
    """Parses raw dtstart into a naive datetime object for comparison."""
    if isinstance(dt_val, datetime):
        return dt_val.replace(tzinfo=None)
    elif isinstance(dt_val, date):
        return datetime.combine(dt_val, datetime.min.time())
    elif isinstance(dt_val, str):
        return datetime.fromisoformat(dt_val.replace("Z", "+00:00")).replace(
            tzinfo=None
        )
    return None


# Regex to extract class code inside brackets
CLASS_REGEX = r"\[([A-Za-z0-9\s-]+)\]"

def sync_calendar():
    """Fetches the external feed and updates the tasks table."""
    if not FEED_URL:
        print("Sync skipped: FEED_URL environment variable is not set.")
        return
    try:
        response = requests.get(FEED_URL, timeout=10)
        cal = icalendar.Calendar.from_ical(response.content)

        tasks = load_tasks()
        start_of_week = get_start_of_current_week()

        for component in cal.walk():
            if component.name == "VEVENT":
                uid = str(component.get("uid"))
                summary = str(component.get("summary"))
                dtstart = component.get("dtstart").dt

                event_dt = parse_event_datetime(dtstart)

                if event_dt and event_dt < start_of_week:
                    continue

                start_str = dtstart.isoformat() if isinstance(dtstart, (datetime, date)) else str(dtstart)

                # Extract class code for Subject
                match = re.search(CLASS_REGEX, summary)
                class_code = match.group(1).replace(" ", "-").upper() if match else ""

                # Default status to "Not started" if not present
                existing_status = tasks.get(uid, {}).get("status", "Not started")

                tasks[uid] = {
                    "uid": uid,
                    "title": summary,
                    "start": start_str,
                    "status": existing_status,
                    "subject": tasks.get(uid, {}).get("subject", class_code), # Default subject to associated class
                    "priority": tasks.get(uid, {}).get("priority", ""),        # Default empty
                    "taskType": tasks.get(uid, {}).get("taskType", ""),        # Default empty
                    "effortLevel": tasks.get(uid, {}).get("effortLevel", "")   # Default empty
                }

        save_tasks(tasks)
        print(f"[{datetime.now()}] Calendar feed synced successfully.")
    except Exception as e:
        print(f"Sync error: {e}")



def _row_to_task(row):
    return {COLUMN_TO_FIELD[key]: (value or "") for key, value in row._mapping.items()}


def _task_to_row(task):
    return {
        column: (task.get(field) or "")
        for field, column in FIELD_TO_COLUMN.items()
    }


def _upsert(rows):
    """Insert rows, or update them if a task with the same uid already exists."""
    if not rows:
        return
    insert = pg_insert if engine.dialect.name == "postgresql" else sqlite_insert
    stmt = insert(tasks_table).values(rows)
    stmt = stmt.on_conflict_do_update(
        index_elements=[tasks_table.c.uid],
        set_={c.name: stmt.excluded[c.name] for c in tasks_table.columns if c.name != "uid"},
    )
    with engine.begin() as conn:
        conn.execute(stmt)


def load_tasks():
    """Loads all tasks from the database, keyed by uid."""
    with engine.connect() as conn:
        rows = conn.execute(select(tasks_table)).all()
    return {row.uid: _row_to_task(row) for row in rows}


def get_task(uid):
    """Returns a single task dict, or None if it doesn't exist."""
    with engine.connect() as conn:
        row = conn.execute(select(tasks_table).where(tasks_table.c.uid == uid)).first()
    return _row_to_task(row) if row else None


def save_task(task):
    """Creates or updates a single task."""
    _upsert([_task_to_row(task)])


def save_tasks(tasks):
    """Creates or updates every task in a {uid: task} dict."""
    _upsert([_task_to_row(task) for task in tasks.values()])


def update_task_fields(uid, **fields):
    """Updates specific fields on a task. Returns False if the task doesn't exist."""
    values = {FIELD_TO_COLUMN[name]: value for name, value in fields.items()}
    with engine.begin() as conn:
        result = conn.execute(
            update(tasks_table).where(tasks_table.c.uid == uid).values(**values)
        )
    return result.rowcount > 0


@app.cli.command("import-json")
@click.argument("path", default="tasks.json")
def import_json_command(path):
    """One-time import of an existing tasks.json file into the database."""
    with open(path, "r") as f:
        tasks = json.load(f)
    save_tasks(tasks)
    click.echo(f"Imported {len(tasks)} tasks from {path}.")


# ---------------------------------------------------------------------------
# Background feed sync
# ---------------------------------------------------------------------------
def background_sync_scheduler(interval_seconds=900):
    """Syncs the external feed every 15 minutes in the background."""
    while True:
        sync_calendar()
        time.sleep(interval_seconds)


_sync_lock = threading.Lock()
_sync_started = False


def start_background_sync():
    """Starts the background sync thread once per process."""
    global _sync_started
    with _sync_lock:
        if _sync_started:
            return
        _sync_started = True
    threading.Thread(target=background_sync_scheduler, daemon=True).start()

def determine_task_type(title, class_code):
    """
    Determines the task type based on title keywords and class rules.
    Returns None if the task is a Reading (so it can be filtered/deleted).
    """
    title_lower = title.lower()

    # Priority rules for Project, Exam, Quiz
    if "project" in title_lower:
        return "Project"
    
    if "exam" in title_lower:
        return "Exam"
    
    if "quiz" in title_lower:
        return "Quiz"

    if "review" in title_lower:
        return "Study"

    # Rule for Assignment
    # - Anything with HW or Training
    # - OR any MATH 1553 task that is not a Quiz or Exam
    if "hw" in title_lower or "training" in title_lower or "coding" in title_lower or "polls" in title_lower:
        return "Assignment"
    
    if "MATH" in class_code and "1553" in class_code:
        return "Assignment"

    if "EAS" in class_code and "1601" in class_code:
            return "Assignment"

    # Default empty for other unmatched tasks
    return ""

def determine_effort_level(task_type, title, class_code):
    """
    Determines effort level based on task type, title keywords, and class code.
    """
    title_lower = title.lower()
    class_code_upper = class_code.upper()

    # Rule 1: Exam or Quiz -> High effort
    if task_type in ["Exam", "Quiz"]:
        return "High Effort"

    # Rule 2: CS HW -> High effort
    if "CS" in class_code_upper and "hw" in title_lower:
        return "High Effort"

    # Rule 3: All other CS assignments -> Low effort
    if "CS" in class_code_upper:
        return "Low Effort"

    # Rule 4: EAS assignments -> Low effort
    if "EAS" in class_code_upper:
        return "Low Effort"

    if "study" in title_lower:
        return "High Effort"

    # Rule 5: All other assignments -> Medium effort
    return "Medium Effort"

def determine_priority(event_dt):
    """
    Determines priority level based on the number of days until the due date.
    - Due within 2 days: High priority
    - Due within 3 to 5 days: Medium priority
    - All other times: Low priority
    """
    if not event_dt:
        return "Low"

    today = date.today()
    task_date = event_dt.date() if isinstance(event_dt, datetime) else event_dt
    days_until_due = (task_date - today).days

    if 0 <= days_until_due <= 2:
        return "High"
    elif 3 <= days_until_due <= 5:
        return "Medium"
    else:
        return "Low"

@app.route("/")
def index():
    return render_template("calendar.html")

@app.route("/api/tasks", methods=["GET"])
def get_tasks():
    tasks = load_tasks()
    events = []
    start_of_week = get_start_of_current_week()

    for item in tasks.values():
        title = item.get("title", "")
        event_dt = parse_event_datetime(item.get("start"))

        if event_dt and event_dt < start_of_week:
            continue

        if "Office Hours" in title or "Attendance" in title or title in ["F26-9:30am Lecture [ISYE-2027-B]", "Lecture [ISYE-2027-B]","Habitable Planet - EAS-1601-A [EAS-1601-A]"]:
            continue

        match = re.search(CLASS_REGEX, title)
        class_code = match.group(1).replace(" ", "-").upper() if match else "DEFAULT"

        # Auto-extract subject if empty
        subject = item.get("subject") or (class_code if class_code != "DEFAULT" else "")
        status = item.get("status", "Not started")

        #Determines Task Type
        detected_task_type = determine_task_type(title, class_code)
        task_type = item.get("taskType") or detected_task_type

        # Auto-detect Effort Level
        detected_effort = determine_effort_level(task_type, title, class_code)
        effort_level = item.get("effortLevel") or detected_effort

        # Auto-detect Priority based on Due Date
        existing_priority = item.get("priority")
        if status == "Completed" and existing_priority:
            priority = existing_priority
        else:
            priority = existing_priority or determine_priority(event_dt)

        events.append({
            "id": item["uid"],
            "title": title,
            "start": item["start"],
            "status": status,
            "subject": subject,
            "priority": priority,
            "taskType": task_type,
            "effortLevel":effort_level,
            "classCode": class_code,
            "className": "completed-task" if status == "Completed" else f"class-{class_code.lower()}"
        })

    events.sort(key=lambda x: x["start"])
    return jsonify(events)

@app.route("/api/tasks/update", methods=["POST"])
def update_task_property():
    """Update custom editable properties for a task."""
    data = request.json
    uid = data.get("uid")
    field = data.get("field")
    value = data.get("value")

    if field not in EDITABLE_FIELDS:
        return jsonify({"error": f"Field '{field}' cannot be edited"}), 400

    if update_task_fields(uid, **{field: value or ""}):
        return jsonify({"success": True}), 200

    return jsonify({"error": "Task not found"}), 404


@app.route("/api/tasks/toggle", methods=["POST"])
def toggle_task():
    """Toggle a task between 'To Do' and 'Completed'."""
    data = request.json
    uid = data.get("uid")

    task = get_task(uid)
    if task:
        current_status = task.get("status") or "To Do"
        new_status = "Completed" if current_status == "To Do" else "To Do"
        update_task_fields(uid, status=new_status)
        return jsonify({"success": True, "new_status": new_status}), 200

    return jsonify({"error": "Task not found"}), 404

@app.route("/api/tasks/create", methods=["POST"])
def create_task():
    """Create a new manual task."""
    data = request.json
    title = data.get("title")
    due_date = data.get("start")

    if not title or not due_date:
        return jsonify({"error": "Title and due date are required"}), 400

    uid = str(uuid.uuid4())

    # Extract class code if present in the title
    match = re.search(CLASS_REGEX, title)
    class_code = match.group(1).replace(" ", "-").upper() if match else ""

    save_task({
        "uid": uid,
        "title": title,
        "start": due_date,
        "status": "Not started",
        "subject": class_code,
        "priority": data.get("priority", ""),
        "taskType": data.get("taskType", ""),
        "effortLevel": data.get("effortLevel", "")
    })

    return jsonify({"success": True, "uid": uid}), 201

@app.route("/tasks")
def tasks_page():
    return render_template("tasks.html")

if __name__ == "__main__":
    # Local development only. In production (Render) gunicorn imports this module
    # and gunicorn.conf.py starts the background sync instead.
    debug = os.environ.get("FLASK_DEBUG", "1") == "1"

    # With debug on, Flask's reloader runs this file twice (a watcher process and
    # the real server). Only start the sync thread in the real server.
    if not debug or os.environ.get("WERKZEUG_RUN_MAIN") == "true":
        start_background_sync()

    app.run(port=int(os.environ.get("PORT", 5000)), debug=debug)
