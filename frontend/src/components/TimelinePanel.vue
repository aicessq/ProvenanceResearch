<script setup lang="ts">
import { computed } from "vue";
import { useTasksStore } from "../stores/tasks";
import type { KnowledgeGapView, SseEvent } from "../types";

const store = useTasksStore();

const ICONS: Record<string, string> = {
  meta: "◉",
  plan: "ℬ",
  tool_call: "⚙",
  tool_result: "↣",
  source_status: "≋",
  evidence: "▤",
  token_delta: "ϟ",
  citation: "✦",
  done: "✔",
  error: "⚠",
};

const TITLE: Record<string, string> = {
  meta: "任务开始",
  plan: "规划",
  tool_call: "调用工具",
  tool_result: "工具返回",
  source_status: "来源状态",
  evidence: "登记证据",
  token_delta: "用量",
  citation: "引用闸门",
  done: "终态",
  error: "诊断",
};

function time(iso: string): string {
  return iso.slice(11, 19);
}

function summary(event: SseEvent): string {
  const p = event.payload as Record<string, unknown>;
  switch (event.type) {
    case "meta":
      return `预算 ${JSON.stringify(p.budget ?? {})}`;
    case "plan": {
      const gaps = p.gaps as KnowledgeGapView[] | undefined;
      if (gaps?.length) {
        return `第 ${p.round} 轮 · 缺口已解决 ${gaps.filter(g => g.status === "resolved").length}/${gaps.length}`;
      }
      return p.progress === undefined ? `第 ${p.round} 轮` : `第 ${p.round} 轮（有新证据: ${p.progress ? "是" : "否"}）`;
    }
    case "tool_call":
      return `${p.tool}(${JSON.stringify(p.args ?? {})})`.slice(0, 90);
    case "tool_result":
      return `${p.tool} → ${p.status}${p.error ? ` (${p.error})` : ""}`;
    case "source_status":
      return `${p.source} / ${p.provider} → ${p.status}${p.error_code ? ` (${p.error_code})` : ""}`;
    case "evidence":
      return `${p.citation_id} · ${p.source_type} · ${p.content_scope}`;
    case "token_delta":
      return `${p.stage} +${Number(p.prompt_tokens ?? 0)}/${Number(p.completion_tokens ?? 0)} tokens`;
    case "citation":
      return `第 ${Number(p.attempt ?? 0) + 1} 次生成，${p.claims} 条结论`;
    case "done": {
      const taskStatus = p.task_status as string;
      const answer = p.answer as { status?: string; refusal_reason?: string } | undefined;
      return taskStatus === "cancelled"
        ? "任务已取消"
        : answer?.status === "refused"
          ? `拒答（${answer.refusal_reason}）`
          : `完成（已回答）`;
    }
    case "error": {
      const fatal = p.fatal === true;
      return `${fatal ? "任务失败" : "过程诊断"}: ${p.reason ?? (p.error as { message?: string })?.message ?? ""}`;
    }
    default:
      return "";
  }
}

const stopReason = computed(() => {
  const answer = store.answer;
  return answer ? answer.stop_reason : null;
});

const budget = computed(() => store.answer?.budget_report ?? null);
const tokens = computed(() => {
  let prompt = 0;
  let completion = 0;
  for (const e of store.events) {
    if (e.type !== "token_delta") continue;
    const p = e.payload as { prompt_tokens?: number; completion_tokens?: number };
    prompt += p.prompt_tokens ?? 0;
    completion += p.completion_tokens ?? 0;
  }
  return { prompt, completion };
});
</script>

<template>
  <section class="timeline scroll">
    <header class="panel-head">
      <h3>任务时间线</h3>
      <span v-if="store.streamState === 'live'" class="badge ok">● 实时</span>
      <span v-else-if="store.streamState === 'connecting'" class="badge warn">连接中</span>
      <span v-else-if="store.streamState === 'done'" class="badge">已结束</span>
      <span v-else-if="store.streamState === 'error'" class="badge err">错误</span>
    </header>

    <p v-if="store.streamNote" class="muted note">{{ store.streamNote }}</p>

    <p v-if="!store.events.length" class="muted empty">
      暂无事件。选择或发起一个任务后，这里按顺序显示 meta → 计划 → 工具 → 证据 → 引用 → 终态。
    </p>

    <ol class="events">
      <li v-for="event in store.events" :key="event.event_id" class="event fade-up" :class="event.type">
        <span class="icon" :class="event.type">{{ ICONS[event.type] ?? "·" }}</span>
        <div class="body">
          <div class="head">
            <span class="title">{{ TITLE[event.type] ?? event.type }}</span>
            <span class="mono muted">{{ time(event.occurred_at) }}</span>
          </div>
          <div class="detail mono">{{ summary(event) }}</div>
        </div>
      </li>
    </ol>

    <footer v-if="stopReason || budget" class="footer">
      <div v-if="stopReason" class="row">
        <span class="muted">停止原因</span>
        <span class="mono">{{ stopReason }}</span>
      </div>
      <div v-if="budget" class="row">
        <span class="muted">预算</span>
        <span class="mono"
          >工具 {{ budget.tool_calls ?? 0 }} 次 · 轮次 {{ budget.rounds ?? 0 }} · tokens {{ budget.tokens ?? 0 }}</span
        >
      </div>
      <div class="row">
        <span class="muted">本流用量</span>
        <span class="mono">↑{{ tokens.prompt }} ↓{{ tokens.completion }}</span>
      </div>
    </footer>
  </section>
</template>

<style scoped>
.timeline {
  padding: 1.25rem;
  height: 100%;
  display: flex;
  flex-direction: column;
  gap: 0.75rem;
}

.panel-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  position: sticky;
  top: 0;
  background: var(--background);
  padding-bottom: 0.5rem;
  z-index: 1;
}

.panel-head h3 {
  margin: 0;
  font-size: 13px;
  letter-spacing: 0.06em;
  text-transform: uppercase;
  color: var(--muted-foreground);
}

.note {
  font-size: 12px;
}

.events {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 0.35rem;
}

.event {
  display: flex;
  gap: 0.65rem;
  padding: 0.45rem 0.55rem;
  border-radius: var(--radius-sm);
  border-left: 2px solid transparent;
}

.event:hover {
  background: var(--surface);
}

.event.done {
  border-left-color: var(--success);
  background: oklch(0.3 0.05 155 / 0.12);
}

.event.error {
  border-left-color: var(--warning);
}

.icon {
  flex: 0 0 1.25rem;
  text-align: center;
  color: var(--muted-foreground);
}

.icon.done { color: var(--success); }
.icon.error { color: var(--warning); }
.icon.tool_call,
.icon.tool_result { color: var(--primary); }
.icon.evidence { color: var(--accent); }

.body {
  min-width: 0;
  flex: 1;
}

.head {
  display: flex;
  justify-content: space-between;
  gap: 0.5rem;
}

.title {
  font-size: 12.5px;
  font-weight: 600;
}

.detail {
  color: var(--muted-foreground);
  font-size: 11.5px;
  overflow-wrap: anywhere;
}

.footer {
  margin-top: auto;
  border-top: 1px solid var(--border);
  padding-top: 0.75rem;
  display: flex;
  flex-direction: column;
  gap: 0.35rem;
}

.row {
  display: flex;
  justify-content: space-between;
  gap: 1rem;
  font-size: 12px;
}
</style>
