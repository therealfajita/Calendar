import json
import os
import threading
import time
from datetime import datetime
from flask import Flask, jsonify, render_template_string
import icalendar
import requests

app = Flask(__name__)

# REPLACE THIS WITH YOUR ICAL FEED URL
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
    """Fetches the external feed and updates tasks.json without duplicates."""
    try:
        response = requests.get(FEED_URL)
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

                # Keep existing completion status if task already exists
                existing_status = tasks.get(uid, {}).get("status", "To Do")

                tasks[uid] = {
                    "uid": uid,
                    "title": summary,
                    "start": start_str,
                    "status": existing_status,
                }

        save_tasks(tasks)
        print(f"[{datetime.now()}] Calendar synced to tasks.json successfully.")
    except Exception as e:
        print(f"Sync error: {e}")


def background_sync_scheduler(interval_seconds=900):
    """Syncs feed every 15 minutes in the background."""
    while True:
        sync_calendar()
        time.sleep(interval_seconds)


@app.route("/")
def index():
    html = """
    <!DOCTYPE html>
    <html>
    <head>
        <title>Local Task Calendar</title>
        <script src='https://cdn.jsdelivr.net/npm/fullcalendar@6.1.8/index.global.min.js'></script>
    </head>
    <body style="font-family: sans-serif; margin: 20px;">
        <h2>My Auto-Syncing Task Calendar</h2>
        <div id='calendar'></div>
        <script>
          document.addEventListener('DOMContentLoaded', function() {
            var calendarEl = document.getElementById('calendar');
            var calendar = new FullCalendar.Calendar(calendarEl, {
              initialView: 'dayGridMonth',
              events: '/api/tasks'
            });
            calendar.render();

            // Auto-refresh calendar interface every 5 minutes
            setInterval(() => { calendar.refetchEvents(); }, 300000);
          });
        </script>
    </body>
    </html>
    """
    return render_template_string(html)


@app.route("/api/tasks")
def get_tasks():
    tasks = load_tasks()
    # Format tasks list for FullCalendar
    events = [
        {"title": item["title"], "start": item["start"]}
        for item in tasks.values()
    ]
    return jsonify(events)


if __name__ == "__main__":
    # Perform initial sync
    sync_calendar()

    # Start 15-minute background auto-sync thread
    threading.Thread(target=background_sync_scheduler, daemon=True).start()

    # Run local server
    app.run(port=5000)