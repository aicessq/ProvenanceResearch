<script setup lang="ts">
import { computed, ref, watch } from "vue";
import { api } from "../api";
import { useTasksStore } from "../stores/tasks";
import type { AnsweredOutcome, RefusedOutcome } from "../types";

const store = useTasksStore();

const answered = computed(() =>
  store.answer && store.answer.status === "answered" ? (store.answer as AnsweredOutcome) : null,
);
const refused = computed(() =>
  store.answer && store.answer.status === "refused" ? (store.answer as RefusedOutcome) : null,
);

const clarification = computed(() => {
  if (!store.isRunning) return null;
  const event = [...store.events].reverse().find(({ type, payload }) =>
    type === "plan" && typeof payload.action === "string" && payload.action.startsWith("clarification_"),
  );
  if (event?.payload.action !== "clarification_requested") return null;
  const { round, question } = event.payload;
  if (typeof round !== "number" || typeof question !== "string") return null;
  return { taskId: event.task_id, round, question, eventId: event.event_id };
});
const clarificationText = ref("");
const clarificationError = ref("");
const sendingClarification = ref(false);
const sentEventId = ref("");

watch(() => clarification.value?.eventId, () => {
  clarificationText.value = "";
  clarificationError.value = "";
});

async function submitClarification() {
  const pending = clarification.value;
  const answer = clarificationText.value.trim();
  if (!pending || !answer || sendingClarification.value) return;
  sendingClarification.value = true;
  clarificationError.value = "";
  try {
    await api.clarifyTask(pending.taskId, pending.round, answer);
    sentEventId.value = pending.eventId;
  } catch (error) {
    if (clarification.value?.eventId === pending.eventId) {
      clarificationError.value = error instanceof Error ? error.message : "未能提交补充信息";
    }
  } finally {
    sendingClarification.value = false;
  }
}

const refusalLabels: Record<string, string> = {
  clarification_required: "需要补充信息，当前无法确定研究范围",
  out_of_scope: "此任务超出当前研究能力范围",
  no_evidence: "没有找到任何登记证据",
  invalid_writer_output: "模型未生成可核验的结构化断言",
  writer_output_truncated: "模型的结构化断言未能完整生成",
  citation_gate_failed: "引用闸门未通过（结论无法被证据支持）",
  budget_exhausted: "预算耗尽仍无充分证据",
  no_supported_claim: "没有任何可验证的结论",
  invalid_planner_output: "研究规划格式无效，无法安全继续",
  deadline_exceeded: "研究时限已到，未能完成证据验证",
};

const searchStatus: Record<string, string> = {
  ok: "找到材料",
  empty: "没有命中",
  error: "调用失败",
  timeout: "已超时",
};

function label(refusal: RefusedOutcome): string {
  return refusalLabels[refusal.refusal_reason] ?? refusal.refusal_reason;
}
</script>

<template>
  <section class="conversation scroll">
    <template v-if="store.activeTask">
      <article class="message user fade-up">
        <div class="who">问题</div>
        <p>{{ store.activeTask.query }}</p>
      </article>

      <article v-if="store.isRunning" class="message system fade-up">
        <div class="who">Agent 运行中</div>
        <p class="muted">
          检索与验证进行中…右侧时间线实时显示计划、工具调用与证据。
          <button class="danger" style="margin-left: 0.5rem" @click="store.cancel()">取消任务</button>
        </p>
      </article>

      <form v-if="clarification && sentEventId !== clarification.eventId"
            class="message system clarification" @submit.prevent="submitClarification">
        <label for="clarification-answer">{{ clarification.question }}</label>
        <textarea id="clarification-answer" v-model="clarificationText" rows="2" maxlength="4000" />
        <button class="primary" :disabled="!clarificationText.trim() || sendingClarification">
          {{ sendingClarification ? "提交中…" : "补充信息" }}
        </button>
        <p v-if="clarificationError" role="alert">{{ clarificationError }}</p>
      </form>

      <article v-if="store.activeTask.status === 'failed' && store.activeTask.error" class="message error fade-up">
        <div class="who">任务失败</div>
        <p class="mono">{{ store.activeTask.error.code }} — {{ store.activeTask.error.message }}</p>
      </article>

      <article v-if="answered" class="message agent fade-up">
        <div class="who">
          {{ answered.partial ? '部分回答' : '回答' }}
          <span class="badge ok">已验证引用 {{ answered.citations.length }}</span>
          <span v-if="answered.latency_ms" class="badge">{{ (answered.latency_ms / 1000).toFixed(1) }}s</span>
        </div>
        <p class="answer-text">{{ answered.text }}</p>
        <div v-if="answered.limitations?.length" class="claims" role="note" aria-label="研究局限">
          <div class="claims-title">研究局限</div>
          <ul><li v-for="item in answered.limitations" :key="item">{{ item }}</li></ul>
        </div>
        <div v-if="answered.claims.length" class="claims">
          <div class="claims-title">逐条结论与依据</div>
          <ul>
            <li v-for="(claim, i) in answered.claims" :key="i">
              <span>{{ claim.claim }}</span>
              <span
                v-for="cid in claim.citations"
                :key="cid"
                class="cite-chip"
                :class="{ active: store.selectedCitation === cid }"
                role="button"
                :aria-label="`查看证据 ${cid}`"
                @click="store.selectCitation(cid)"
                >{{ cid }}</span
              >
            </li>
          </ul>
        </div>
      </article>

      <article v-if="refused" class="message refused fade-up">
        <div class="who">
          无结论报告
        </div>
        <p>{{ label(refused) }}</p>
        <p v-if="refused.refusal_detail">{{ refused.refusal_detail }}</p>
        <ul v-if="refused.search_summary?.length">
          <li v-for="(search, index) in refused.search_summary" :key="index">
            {{ search.tool }} {{ search.query || search.source_id }}（{{ searchStatus[search.status] ?? search.status }}）
            <span v-if="search.error_detail"> {{ search.error_detail }}</span>
          </li>
        </ul>
        <p v-else-if="refused.searched_tools?.length">已尝试 {{ refused.searched_tools.join("、") }}</p>
        <p class="mono muted">stop_reason: {{ refused.stop_reason }}</p>
      </article>

      <article v-if="store.answer && (store.answer.missing_questions?.length || store.answer.assumptions?.length || store.answer.plan_changes?.length)" class="message system">
        <div v-if="store.answer.missing_questions?.length">
          <strong>仍待核对</strong>
          <ul><li v-for="question in store.answer.missing_questions" :key="question">{{ question }}</li></ul>
        </div>
        <div v-if="store.answer.assumptions?.length">
          <strong>研究假设</strong>
          <ul><li v-for="assumption in store.answer.assumptions" :key="assumption">{{ assumption }}</li></ul>
        </div>
        <div v-if="store.answer.plan_changes?.length">
          <strong>研究计划变更</strong>
          <ul>
            <li v-for="(change, index) in store.answer.plan_changes" :key="index">
              <template v-if="change.question === null">删除「{{ change.previous }}」</template>
              <template v-else-if="change.previous">「{{ change.previous }}」改为「{{ change.question }}」</template>
              <template v-else>新增「{{ change.question }}」</template>
              （{{ change.reason }}）
            </li>
          </ul>
        </div>
      </article>
    </template>

    <div v-else class="welcome">
      <h2>可溯源研究</h2>
      <p class="muted">
        提问后 Agent 在预算内检索私有语料、网页与论文，每个事实性结论都经过引用闸门验证；
        证据不足时如实拒答。
      </p>
      <ul class="hints">
        <li>《网络安全法》（2025 修正）第二十三条要求留存网络日志多久？</li>
        <li>TLS 1.2 由哪个 RFC 定义？完整标题是什么？</li>
        <li>IETF 计划什么时间发布 TLS 1.4？（预期拒答）</li>
      </ul>
    </div>
  </section>
</template>

<style scoped>
.conversation {
  display: flex;
  flex-direction: column;
  gap: 1rem;
  padding: 1.25rem;
  height: 100%;
}

.message {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  padding: 0.9rem 1rem;
}

.clarification {
  display: grid;
  gap: 0.6rem;
}

.clarification button {
  justify-self: start;
}

.message.user {
  background: oklch(0.24 0.03 220 / 0.35);
  border-color: oklch(0.4 0.07 220 / 0.4);
}

.message.refused {
  border-color: oklch(0.5 0.1 85 / 0.5);
}

.message.error {
  border-color: oklch(0.5 0.14 25 / 0.5);
}

.who {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  font-size: 12px;
  font-weight: 600;
  letter-spacing: 0.04em;
  color: var(--muted-foreground);
  margin-bottom: 0.45rem;
}

.answer-text {
  white-space: pre-wrap;
  font-size: 15px;
  line-height: 1.7;
  margin: 0.25rem 0 0.75rem;
}

.claims-title {
  font-size: 12px;
  font-weight: 600;
  color: var(--muted-foreground);
  margin-bottom: 0.4rem;
}

.claims ul {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 0.55rem;
}

.claims li {
  display: flex;
  flex-direction: column;
  gap: 0.25rem;
  padding: 0.55rem 0.7rem;
  background: var(--paper);
  border-radius: var(--radius-sm);
}

.welcome {
  margin: auto;
  max-width: 460px;
  text-align: left;
}

.welcome h2 {
  font-size: 22px;
  margin-bottom: 0.5rem;
}

.hints {
  margin-top: 1rem;
  padding-left: 1.1rem;
  color: var(--muted-foreground);
  display: flex;
  flex-direction: column;
  gap: 0.45rem;
}
</style>
