<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import ConversationView from "./components/ConversationView.vue";
import EvidencePanel from "./components/EvidencePanel.vue";
import TimelinePanel from "./components/TimelinePanel.vue";
import { useTasksStore } from "./stores/tasks";

const store = useTasksStore();
const question = ref("");

onMounted(() => {
  void store.refresh();
});

const statusLabel = computed(() => {
  switch (store.activeTask?.status) {
    case "running":
    case "pending":
      return { text: "运行中", cls: "ok" };
    case "completed":
      return { text: "已完成", cls: "" };
    case "failed":
      return { text: "失败", cls: "err" };
    case "cancelled":
      return { text: "已取消", cls: "warn" };
    default:
      return { text: "就绪", cls: "" };
  }
});

async function submit() {
  const q = question.value.trim();
  if (!q || store.submitting) return;
  question.value = "";
  await store.submit(q);
}

function onKeydown(event: KeyboardEvent) {
  if (event.key === "Enter" && !event.shiftKey) {
    event.preventDefault();
    void submit();
  }
}
</script>

<template>
  <div class="shell">
    <header class="topbar">
      <div class="brand">
        <span class="logo">◆</span>
        <div>
          <div class="name">Provenance Research</div>
          <div class="tag muted">证据可溯源 Agentic RAG · 每条结论经引用闸门验证</div>
        </div>
      </div>

      <div class="top-actions">
        <label class="task-picker">
          <span class="muted">会话</span>
          <select :value="store.activeTaskId ?? ''" @change="store.select(($event.target as HTMLSelectElement).value)">
            <option value="" disabled>选择任务…</option>
            <option v-for="task in store.tasks" :key="task.task_id" :value="task.task_id">
              {{ task.query.slice(0, 32) }} — {{ task.status }}
            </option>
          </select>
        </label>
        <span v-if="store.activeTask" class="badge" :class="statusLabel.cls">{{ statusLabel.text }}</span>
        <button
          v-if="store.activeTask && !store.activeTask.completed_at"
          class="danger"
          @click="store.cancel()"
        >
          取消
        </button>
        <button
          v-if="store.activeTask"
          class="ghost"
          title="删除任务"
          @click="store.remove(store.activeTask.task_id)"
        >
          删除
        </button>
        <button class="primary" @click="store.newSession()">新提问</button>
      </div>
    </header>

    <p v-if="store.fatalError" class="fatal" role="alert">
      {{ store.fatalError }}
    </p>

    <main class="grid">
      <div class="col conversation-col">
        <ConversationView />
        <footer class="composer">
          <textarea
            v-model="question"
            rows="2"
            placeholder="输入研究问题，Enter 发送（Shift+Enter 换行）…"
            :disabled="store.submitting"
            @keydown="onKeydown"
          ></textarea>
          <div class="composer-actions">
            <span class="muted">预算默认 3 轮 / 12 次工具 / 180s；证据不足将拒答</span>
            <button class="primary" :disabled="!question.trim() || store.submitting" @click="submit()">
              {{ store.submitting ? "提交中…" : "提问" }}
            </button>
          </div>
        </footer>
      </div>
      <div class="col"><EvidencePanel /></div>
      <div class="col"><TimelinePanel /></div>
    </main>
  </div>
</template>

<style scoped>
.shell {
  height: 100%;
  display: flex;
  flex-direction: column;
}

.topbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 1rem;
  padding: 0.85rem 1.25rem;
  border-bottom: 1px solid var(--border);
  background: oklch(0.18 0.013 265 / 0.9);
  backdrop-filter: blur(8px);
}

.brand {
  display: flex;
  align-items: center;
  gap: 0.75rem;
}

.logo {
  font-size: 20px;
  color: var(--primary);
}

.name {
  font-weight: 700;
  letter-spacing: 0.01em;
}

.tag {
  font-size: 12px;
}

.top-actions {
  display: flex;
  align-items: center;
  gap: 0.6rem;
  flex-wrap: wrap;
}

.task-picker {
  display: flex;
  align-items: center;
  gap: 0.45rem;
  font-size: 13px;
}

.task-picker select {
  font: inherit;
  color: var(--foreground);
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  padding: 0.4rem 0.55rem;
  max-width: 240px;
}

.fatal {
  margin: 0;
  padding: 0.55rem 1.25rem;
  background: oklch(0.32 0.08 25 / 0.35);
  border-bottom: 1px solid oklch(0.5 0.14 25 / 0.5);
  color: oklch(0.85 0.1 25);
  font-size: 13px;
}

.grid {
  flex: 1;
  min-height: 0;
  display: grid;
  grid-template-columns: minmax(340px, 1.25fr) minmax(280px, 1fr) minmax(280px, 1fr);
}

.col {
  min-width: 0;
  min-height: 0;
  display: flex;
  flex-direction: column;
  border-right: 1px solid var(--border);
}

.col:last-child {
  border-right: none;
}

.conversation-col {
  position: relative;
}

.composer {
  border-top: 1px solid var(--border);
  padding: 0.9rem 1.25rem 1.1rem;
  background: var(--background);
}

.composer-actions {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 1rem;
  margin-top: 0.55rem;
  font-size: 12px;
}

@media (max-width: 1100px) {
  .grid {
    grid-template-columns: 1fr 1fr;
    grid-template-rows: 1fr 1fr;
  }

  .conversation-col {
    grid-column: 1 / -1;
  }
}

@media (max-width: 720px) {
  .grid {
    grid-template-columns: 1fr;
  }

  .topbar {
    flex-direction: column;
    align-items: flex-start;
  }
}
</style>
