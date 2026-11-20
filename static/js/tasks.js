document.addEventListener('DOMContentLoaded', function() {
    const tableBody = document.getElementById('task-table-body');

    function loadTasks() {
      fetch('/api/tasks')
        .then(res => res.json())
        .then(tasks => {
          tableBody.innerHTML = '';
          tasks.forEach(task => {
            const tr = document.createElement('tr');
            
            // Determine class styling based on classCode or task status
            const classCodeCss = task.classCode ? `class-${task.classCode.toLowerCase()}` : 'class-default';
            const rowClass = task.status === 'Completed' ? 'completed-task' : classCodeCss;
            tr.className = `task-row ${rowClass}`;

            tr.innerHTML = `
              <td class="task-title-cell">
                <span class="task-badge">${task.classCode || 'General'}</span>
                ${task.title}
              </td>
              <td>
                <select onchange="updateProp('${task.id}', 'status', this.value)">
                  <option value="Not started" ${task.status === 'Not started' ? 'selected' : ''}>Not started</option>
                  <option value="In progress" ${task.status === 'In progress' ? 'selected' : ''}>In progress</option>
                  <option value="Completed" ${task.status === 'Completed' ? 'selected' : ''}>Completed</option>
                </select>
              </td>
              <td class="due-date-cell">${new Date(task.start).toLocaleDateString()}</td>
              <td>
                <select onchange="updateProp('${task.id}', 'priority', this.value)">
                  <option value="" ${!task.priority ? 'selected' : ''}></option>
                  <option value="Low" ${task.priority === 'Low' ? 'selected' : ''}>Low</option>
                  <option value="Medium" ${task.priority === 'Medium' ? 'selected' : ''}>Medium</option>
                  <option value="High" ${task.priority === 'High' ? 'selected' : ''}>High</option>
                </select>
              </td>
              <td>
                <input type="text" placeholder="" value="${task.subject || ''}" onchange="updateProp('${task.id}', 'subject', this.value)">
              </td>
              <td>
                <select onchange="updateProp('${task.id}', 'taskType', this.value)">
                  <option value="" ${!task.taskType ? 'selected' : ''}></option>
                  <option value="Assignment" ${task.taskType === 'Assignment' ? 'selected' : ''}>Assignment</option>
                  <option value="Quiz" ${task.taskType === 'Quiz' ? 'selected' : ''}>Quiz</option>
                  <option value="Exam" ${task.taskType === 'Exam' ? 'selected' : ''}>Exam</option>
                  <option value="Study" ${task.taskType === 'Study' ? 'selected' : ''}>Study</option>
                  <option value="Project" ${task.taskType === 'Project' ? 'selected' : ''}>Project</option>
                </select>
              </td>
              <td>
                <select onchange="updateProp('${task.id}', 'effortLevel', this.value)">
                  <option value="" ${!task.effortLevel ? 'selected' : ''}></option>
                  <option value="Low Effort" ${task.effortLevel === 'Low Effort' ? 'selected' : ''}>Low Effort</option>
                  <option value="Medium Effort" ${task.effortLevel === 'Medium Effort' ? 'selected' : ''}>Medium Effort</option>
                  <option value="High Effort" ${task.effortLevel === 'High Effort' ? 'selected' : ''}>High Effort</option>
                </select>
              </td>
            `;
            tableBody.appendChild(tr);
          });
        });
    }

    window.updateProp = function(uid, field, value) {
      fetch('/api/tasks/update', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ uid: uid, field: field, value: value })
      });
    };

    loadTasks();
});