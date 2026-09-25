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


def sync_calendar():
    """Fetches the external feed and updates tasks.json, skipping events from past weeks."""
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

                # Skip events before Monday of the current week
                if event_dt and event_dt < start_of_week:
                    continue

                if isinstance(dtstart, (datetime, date)):
                    start_str = dtstart.isoformat()
                else:
                    start_str = str(dtstart)

                existing_status = tasks.get(uid, {}).get("status", "To Do")

                tasks[uid] = {
                    "uid": uid,
                    "title": summary,
                    "start": start_str,
                    "status": existing_status,
                }

        save_tasks(tasks)
        print(
            f"[{datetime.now()}] Calendar feed synced successfully (filtered previous weeks)."
        )
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


CLASS_REGEX = r"\[([A-Za-z0-9\s-]+)\]"
@app.route("/api/tasks", methods=["GET"])
def get_tasks():
    tasks = load_tasks()
    events = []
    start_of_week = get_start_of_current_week()

    for item in tasks.values():
        event_dt = parse_event_datetime(item["start"])

        # Filter out past week events when serving API
        if event_dt and event_dt < start_of_week:
            continue

        title = item["title"]

        #Skips lecture events
        if title == "F26-9:30am Lecture [ISYE-2027-B]" or title == "Lecture [ISYE-2027-B]":
            continue

        #Skips Office hours
        if "Office Hours" in title:
            continue

        match = re.search(CLASS_REGEX, title)
        if match:
            class_code = match.group(1).replace(" ", "-").upper()
        else:
            class_code = "DEFAULT"

        status = item.get("status", "To Do")
        is_completed = status == "Completed"

        events.append(
            {
                "id": item["uid"],
                "title": title,
                "start": item["start"],
                "status": status,
                "classCode": class_code,
                "className": (
                    "completed-task"
                    if is_completed
                    else f"class-{class_code.lower()}"
                ),
            }
        )

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