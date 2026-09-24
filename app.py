import json
import os
import threading
import time
from datetime import datetime
from flask import Flask, jsonify, render_template, request
import icalendar
import requests

app = Flask(__name__)

# REPLACE WITH YOUR ACTUAL ICAL/URL FEED
FEED_URL = "https://gatech.instructure.com/feeds/calendars/user_ZwmEaflRhKApN4Nah3ijlSpy2QTYELYfBXKl8Cw2.ics"
JSON_FILE = "tasks.json"


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


def sync_calendar():
    """Fetches the external feed and updates tasks.json without losing custom data."""
    try:
        response = requests.get(FEED_URL, timeout=10)
        cal = icalendar.Calendar.from_ical(response.content)

        tasks = load_tasks()

        for component in cal.walk():
            if component.name == "VEVENT":
                uid = str(component.get("uid"))
                summary = str(component.get("summary"))
                start = component.get("dtstart").dt

                if isinstance(start, datetime):
                    start_str = start.isoformat()
                else:
                    start_str = str(start)

                # Preserve existing completion status if task already exists
                existing_status = tasks.get(uid, {}).get("status", "To Do")

                tasks[uid] = {
                    "uid": uid,
                    "title": summary,
                    "start": start_str,
                    "status": existing_status,
                }

        save_tasks(tasks)
        print(f"[{datetime.now()}] Calendar feed synced successfully.")
    except Exception as e:
        print(f"Sync error: {e}")


def background_sync_scheduler(interval_seconds=900):
    """Syncs the external feed every 15 minutes in the background."""
    while True:
        sync_calendar()
        time.sleep(interval_seconds)


@app.route("/")
def index():
    return render_template("calendar.html")


@app.route("/api/tasks", methods=["GET"])
def get_tasks():
    tasks = load_tasks()
    events = [
        {
            "id": item["uid"],
            "title": item["title"],
            "start": item["start"],
            "status": item.get("status", "To Do"),
            # Add class names for custom styling based on status
            "className": (
                "completed-task"
                if item.get("status") == "Completed"
                else "todo-task"
            ),
        }
        for item in tasks.values()
    ]
    return jsonify(events)


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


if __name__ == "__main__":
    # Perform an initial sync upon running
    sync_calendar()

    # Start background auto-sync thread
    threading.Thread(target=background_sync_scheduler, daemon=True).start()

    # Start server
    app.run(port=5000, debug=True)