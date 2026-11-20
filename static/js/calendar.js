document.addEventListener('DOMContentLoaded', function() {
    var calendarEl = document.getElementById('calendar');
    var taskListEl = document.getElementById('task-list');

    // Initialize FullCalendar with Month, Week, and Day views + Time Grid
    var calendar = new FullCalendar.Calendar(calendarEl, {
      initialView: 'dayGridMonth',
      headerToolbar: {
        left: 'prev,next today',
        center: 'title',
        right: 'dayGridMonth,timeGridWeek,timeGridDay'
      },
      slotMinTime: '06:00:00', // Start time slot (6:00 AM)
      slotMaxTime: '23:00:00', // End time slot (11:00 PM)
      slotDuration: '00:30:00', // 30-minute intervals
      allDaySlot: true, // Show all-day events header row
      nowIndicator: true, // Red line indicating current time
      events: '/api/tasks',
      eventClick: function(info) {
        toggleTaskStatus(info.event.id);
      },
      // Clicking an empty spot on a day opens the "New Task" dialog for that day
      dateClick: function(info) {
        openNewTaskModal(info);
      }
    });

    calendar.render();

    // Load side list view
    function loadTaskList() {
        fetch('/api/tasks')
            .then(res => res.json())
            .then(events => {
                taskListEl.innerHTML = '';
                events.forEach(task => {
                    const li = document.createElement('li');
                    
                    const classStyle = task.status === 'Completed' ? 'done' : `class-${task.classCode.toLowerCase()}`;
                    li.className = `task-item ${classStyle}`;
                    
                    li.innerHTML = `
                    <div>
                        <span class="task-badge">${task.classCode !== 'DEFAULT' ? task.classCode : 'General'}</span>
                        <span class="task-title">${task.title}</span>
                    </div>
                    <span class="task-date" style="color: black;"><strong>${parseTaskDate(task.start).toLocaleDateString()}</strong></span>
                    `;
                    li.onclick = () => toggleTaskStatus(task.id);
                    taskListEl.appendChild(li);
                });
            });
    }

    function toggleTaskStatus(uid) {
      fetch('/api/tasks/toggle', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ uid: uid })
      })
      .then(res => res.json())
      .then(data => {
        if (data.success) {
          calendar.refetchEvents();
          loadTaskList();
        }
      });
    }

    // Date-only strings ("YYYY-MM-DD") are parsed by `new Date()` as UTC midnight,
    // which shows up as the previous day in timezones behind UTC. Parse them as local dates.
    function parseTaskDate(value) {
      if (/^\d{4}-\d{2}-\d{2}$/.test(value)) {
        const [y, m, d] = value.split('-').map(Number);
        return new Date(y, m - 1, d);
      }
      return new Date(value);
    }

    // ---------- Create a task by clicking on a calendar day ----------
    const modalEl = document.getElementById('new-task-modal');
    const formEl = document.getElementById('calendar-task-form');
    const titleInput = document.getElementById('calendar-task-title');
    const typeSelect = document.getElementById('calendar-task-type');
    const prioritySelect = document.getElementById('calendar-task-priority');
    const effortSelect = document.getElementById('calendar-task-effort');
    const dateLabel = document.getElementById('new-task-date-label');
    const errorEl = document.getElementById('calendar-task-error');
    const cancelBtn = document.getElementById('calendar-task-cancel');
    const submitBtn = formEl.querySelector('button[type="submit"]');

    // Due date ("start") for the task currently being created
    let pendingDueDate = null;

    function openNewTaskModal(info) {
      // Month view / all-day row gives "YYYY-MM-DD"; the Week/Day time grid gives
      // that day plus the clicked time slot. Either way the task is due on that day.
      pendingDueDate = info.dateStr;
      if (info.allDay) {
        dateLabel.textContent = info.date.toLocaleDateString(undefined, {
          weekday: 'long', month: 'long', day: 'numeric', year: 'numeric'
        });
      } else {
        dateLabel.textContent = info.date.toLocaleString(undefined, {
          weekday: 'long', month: 'long', day: 'numeric', year: 'numeric',
          hour: 'numeric', minute: '2-digit'
        });
      }

      formEl.reset();
      errorEl.hidden = true;
      submitBtn.disabled = false;
      modalEl.hidden = false;
      titleInput.focus();
    }

    function closeNewTaskModal() {
      modalEl.hidden = true;
      pendingDueDate = null;
    }

    function showModalError(message) {
      errorEl.textContent = message;
      errorEl.hidden = false;
    }

    formEl.addEventListener('submit', function(e) {
      e.preventDefault();
      const title = titleInput.value.trim();
      if (!title) {
        showModalError('Please enter a task name.');
        return;
      }
      if (!pendingDueDate) return;

      submitBtn.disabled = true;
      fetch('/api/tasks/create', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          title: title,
          start: pendingDueDate,
          taskType: typeSelect.value,
          priority: prioritySelect.value,
          effortLevel: effortSelect.value
        })
      })
      .then(res => res.json().then(data => ({ ok: res.ok, data })))
      .then(({ ok, data }) => {
        if (!ok || !data.success) {
          throw new Error(data.error || 'Could not create task.');
        }
        closeNewTaskModal();
        calendar.refetchEvents();
        loadTaskList();
      })
      .catch(err => {
        submitBtn.disabled = false;
        showModalError(err.message || 'Could not create task.');
      });
    });

    cancelBtn.addEventListener('click', closeNewTaskModal);

    // Close when clicking the dimmed backdrop (but not the card itself)
    modalEl.addEventListener('click', function(e) {
      if (e.target === modalEl) closeNewTaskModal();
    });

    document.addEventListener('keydown', function(e) {
      if (e.key === 'Escape' && !modalEl.hidden) closeNewTaskModal();
    });

    // Initial sidebar load
    loadTaskList();

    // Refresh data every 5 minutes automatically
    setInterval(() => {
      calendar.refetchEvents();
      loadTaskList();
    }, 300000);
});