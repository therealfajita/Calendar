import json
import os
import threading
import time
from datetime import date, datetime, timedelta
from flask import Flask, jsonify, render_template, request
import icalendar
import requests
import re

app = Flask(__name__)

# REPLACE WITH YOUR ACTUAL ICAL/URL FEED
FEED_URL = "https://gatech.instructure.com/feeds/calendars/user_ZwmEaflRhKApN4Nah3ijlSpy2QTYELYfBXKl8Cw2.ics"
JSON_FILE = "tasks.json"

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
    """Fetches the external feed and updates tasks.json."""
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



def load_tasks():
    """Loads tasks from the local JSON file."""
    if not os.path.exists(JSON_FILE):
        return {}
    with open(JSON_FILE, "r") as f:
        return json.load(f)


def save_tasks(tasks):
    """Saves tasks to the local JSON file."""
    with open(JSON_FILE, "w") as f:
        json.dump(tasks, f, indent=4)

def background_sync_scheduler(interval_seconds=900):
    """Syncs the external feed every 15 minutes in the background."""
    while True:
        sync_calendar()
        time.sleep(interval_seconds)

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

    # Rule 5: All other assignments -> Medium effort
    return "Medium Effort"

@app.route("/")
def index():
    return render_template("calendar.html")



CLASS_REGEX = r"\[([A-Za-z0-9\s-]+)\]"
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
        
        events.append({
            "id": item["uid"],
            "title": title,
            "start": item["start"],
            "status": status,
            "subject": subject,
            "priority": item.get("priority", ""),
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

    tasks = load_tasks()
    if uid in tasks:
        tasks[uid][field] = value
        save_tasks(tasks)
        return jsonify({"success": True}), 200

    return jsonify({"error": "Task not found"}), 404


@app.route("/api/tasks/toggle", methods=["POST"])
def toggle_task():
    """Toggle a task between 'To Do' and 'Completed'."""
    data = request.json
    uid = data.get("uid")

    tasks = load_tasks()
    if uid in tasks:
        current_status = tasks[uid].get("status", "To Do")
        tasks[uid]["status"] = (
            "Completed" if current_status == "To Do" else "To Do"
        )
        save_tasks(tasks)
        return jsonify(
            {"success": True, "new_status": tasks[uid]["status"]}
        ), 200

    return jsonify({"error": "Task not found"}), 404

@app.route("/tasks")
def tasks_page():
    return render_template("tasks.html")

if __name__ == "__main__":
    # Perform an initial sync upon running
    sync_calendar()

    # Start background auto-sync thread
    threading.Thread(target=background_sync_scheduler, daemon=True).start()

    # Start server
    app.run(port=5000, debug=True)