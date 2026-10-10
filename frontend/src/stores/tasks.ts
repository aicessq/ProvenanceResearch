/** 会话任务 + SSE 时间线状态（多会话切换不串流：任一时刻只挂一条事件流）。 */

import { defineStore } from "pinia";
import { computed, ref } from "vue";
import { api, openTaskStream, type StreamHandlers } from "../api";
import type { AnswerView, SseEvent, TaskView } from "../types";

export type StreamState = "idle" | "connecting" | "live" | "done" | "error";

export const useTasksStore = defineStore("tasks", () => {
  const tasks = ref<TaskView[]>([]);
  const activeTaskId = ref<string | null>(null);
  const events = ref<SseEvent[]>([]);
  const streamState = ref<StreamState>("idle");
  const streamNote = ref("");
  const selectedCitation = ref<string | null>(null);
  const submitting = ref(false);
  const fatalError = ref<string | null>(null);

  let closeStream: (() => void) | null = null;

  const activeTask = computed<TaskView | null>(
    () => tasks.value.find((t) => t.task_id === activeTaskId.value) ?? null,
  );
  const answer = computed<AnswerView | null>(() => activeTask.value?.answer ?? null);
  const isRunning = computed(() => {
    const status = activeTask.value?.status;
    return status === "pending" || status === "running";
  });

  async function refresh() {
    try {
      const list = await api.listTasks();
      tasks.value = list.tasks;
    } catch (err) {
      fatalError.value = err instanceof Error ? err.message : String(err);
    }
  }

  function detachStream() {
    if (closeStream) {
      closeStream();
      closeStream = null;
    }
  }

  async function select(taskId: string) {
    detachStream();
    activeTaskId.value = taskId;
    events.value = [];
    selectedCitation.value = null;
    streamNote.value = "";
    fatalError.value = null;

    try {
      const task = await api.getTask(taskId);
      upsertTask(task);
    } catch (err) {
      fatalError.value = err instanceof Error ? err.message : String(err);
      return;
    }

    streamState.value = "connecting";
    const handlers: StreamHandlers = {
      onOpen: () => {
        streamState.value = "live";
      },
      onEvent: (event) => handleEvent(taskId, event),
      onError: (message) => {
        streamNote.value = message;
      },
    };
    closeStream = openTaskStream(taskId, handlers);
  }

  function handleEvent(taskId: string, event: SseEvent) {
    if (taskId !== activeTaskId.value) return; // 切走后旧流事件不进面板（不串流）
    if (events.value.some((e) => e.sequence === event.sequence)) return; // 重放去重
    events.value.push(event);

    if (event.type === "done") {
      streamState.value = "done";
      streamNote.value = "";
      void refreshTask(taskId);
    } else if (event.type === "error") {
      const payload = event.payload as { fatal?: boolean; reason?: string };
      if (payload.fatal === true) {
        streamState.value = "error";
        streamNote.value = "";
        void refreshTask(taskId);
      }
    }
  }

  function upsertTask(task: TaskView) {
    const idx = tasks.value.findIndex((t) => t.task_id === task.task_id);
    if (idx >= 0) tasks.value[idx] = task;
    else tasks.value.unshift(task);
  }

  async function refreshTask(taskId: string) {
    try {
      upsertTask(await api.getTask(taskId));
    } catch (err) {
      fatalError.value = err instanceof Error ? err.message : String(err);
    }
  }

  async function submit(query: string) {
    submitting.value = true;
    fatalError.value = null;
    try {
      const task = await api.createTask(query);
      upsertTask(task);
      await select(task.task_id);
    } catch (err) {
      fatalError.value = err instanceof Error ? err.message : String(err);
    } finally {
      submitting.value = false;
    }
  }

  async function cancel() {
    if (!activeTaskId.value) return;
    try {
      await api.cancelTask(activeTaskId.value);
      await refreshTask(activeTaskId.value);
    } catch (err) {
      fatalError.value = err instanceof Error ? err.message : String(err);
    }
  }

  async function remove(taskId: string) {
    try {
      await api.deleteTask(taskId);
      if (activeTaskId.value === taskId) {
        detachStream();
        activeTaskId.value = null;
        events.value = [];
      }
      await refresh();
    } catch (err) {
      fatalError.value = err instanceof Error ? err.message : String(err);
    }
  }

  function selectCitation(citationId: string | null) {
    selectedCitation.value = selectedCitation.value === citationId ? null : citationId;
  }

  function newSession() {
    detachStream();
    activeTaskId.value = null;
    events.value = [];
    selectedCitation.value = null;
    streamState.value = "idle";
    streamNote.value = "";
    fatalError.value = null;
  }

  return {
    tasks,
    activeTaskId,
    activeTask,
    answer,
    events,
    streamState,
    streamNote,
    selectedCitation,
    submitting,
    isRunning,
    fatalError,
    refresh,
    select,
    submit,
    cancel,
    remove,
    selectCitation,
    newSession,
  };
});
