import { useCallback, useEffect, useState, type FormEvent } from "react";

type StudentTask = {
  id: number;
  title: string;
  completed: number;
  created_at: string;
  updated_at: string;
};

export default function StudentTasksPanel({ apiUrl }: { apiUrl?: string }) {
  const [tasks, setTasks] = useState<StudentTask[]>([]);
  const [title, setTitle] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  const savedUrl = localStorage.getItem("nexus_api_url");
  const currentApiUrl =
    apiUrl ||
    (savedUrl && !savedUrl.includes(":8000") ? savedUrl : "http://127.0.0.1:8001");

  const loadTasks = useCallback(async () => {
    const response = await fetch(`${currentApiUrl}/api/student/tasks`);
    if (!response.ok) {
      throw new Error(`Could not load student tasks (${response.status})`);
    }
    const data = (await response.json()) as { tasks: StudentTask[] };
    setTasks(data.tasks);
  }, [currentApiUrl]);

  useEffect(() => {
    let active = true;
    const init = async () => {
      try {
        const response = await fetch(`${currentApiUrl}/api/student/tasks`);
        if (response.ok && active) {
          const data = (await response.json()) as { tasks: StudentTask[] };
          setTasks(data.tasks);
        } else if (active) {
          setError(`Could not load student tasks (${response.status})`);
        }
      } catch (reason: unknown) {
        if (active) {
          setError(reason instanceof Error ? reason.message : "Could not load tasks.");
        }
      }
    };
    void init();
    return () => {
      active = false;
    };
  }, [currentApiUrl]);

  async function handleCreate(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const trimmed = title.trim();
    if (!trimmed) {
      setError("Please enter a task title.");
      return;
    }
    setLoading(true);
    setError("");
    try {
      const response = await fetch(`${currentApiUrl}/api/student/tasks`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ title: trimmed }),
      });
      if (!response.ok) {
        const detail = await response.text();
        throw new Error(detail || "Task could not be created.");
      }
      setTitle("");
      await loadTasks();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Task could not be created.");
    } finally {
      setLoading(false);
    }
  }

  async function handleToggle(taskId: number, completed: boolean) {
    setError("");
    try {
      const response = await fetch(`${currentApiUrl}/api/student/tasks/${taskId}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ completed: !completed }),
      });
      if (!response.ok) {
        throw new Error(`Could not update task (${response.status})`);
      }
      await loadTasks();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Task update failed.");
    }
  }

  return (
    <section className="student-tasks-panel">
      <div className="student-tasks-header">
        <div>
          <span className="eyebrow">STUDENT TASK MANAGER</span>
          <h3>Today's assignments</h3>
        </div>
        <span className="task-count">{tasks.filter((task) => !task.completed).length} open</span>
      </div>

      <form onSubmit={handleCreate} className="task-form">
        <input
          aria-label="New task title"
          value={title}
          onChange={(event) => setTitle(event.target.value)}
          placeholder="Add a new student task…"
          maxLength={200}
        />
        <button type="submit" disabled={loading || !title.trim()}>
          {loading ? "Saving…" : "Add task"}
        </button>
      </form>

      {error && <p className="task-error">{error}</p>}

      <ul className="task-list">
        {tasks.length === 0 ? (
          <li className="task-empty">No tasks yet. Add the first assignment.</li>
        ) : (
          tasks.map((task) => (
            <li key={task.id} className={`task-item ${task.completed ? "done" : ""}`}>
              <label className="task-check">
                <input
                  type="checkbox"
                  checked={Boolean(task.completed)}
                  onChange={() => void handleToggle(task.id, Boolean(task.completed))}
                />
                <span>{task.title}</span>
              </label>
            </li>
          ))
        )}
      </ul>
    </section>
  );
}
