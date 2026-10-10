<script setup lang="ts">
import { computed } from "vue";
import { useTasksStore } from "../stores/tasks";
import type { AnsweredOutcome, RefusedOutcome } from "../types";

const store = useTasksStore();

const answered = computed(() =>
  store.answer && store.answer.status === "answered" ? (store.answer as AnsweredOutcome) : null,
);
const refused = computed(() =>
  store.answer && store.answer.status === "refused" ? (store.answer as RefusedOutcome) : null,
);

const refusalLabels: Record<string, string> = {
  no_evidence: "没有找到任何登记证据",
  citation_gate_failed: "引用闸门未通过（结论无法被证据支持）",
  budget_exhausted: "预算耗尽仍无充分证据",
  no_supported_claim: "没有任何可验证的结论",
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

      <article v-if="store.activeTask.status === 'failed' && store.activeTask.error" class="message error fade-up">
        <div class="who">任务失败</div>
        <p class="mono">{{ store.activeTask.error.code }} — {{ store.activeTask.error.message }}</p>
      </article>

      <article v-if="answered" class="message agent fade-up">
        <div class="who">
          回答
          <span class="badge ok">已验证引用 {{ answered.citations.length }}</span>
          <span v-if="answered.latency_ms" class="badge">{{ (answered.latency_ms / 1000).toFixed(1) }}s</span>
        </div>
        <p class="answer-text">{{ answered.text }}</p>
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
          拒答
          <span class="badge warn">证据不足不作答</span>
        </div>
        <p>{{ label(refused) }}</p>
        <p class="mono muted">stop_reason: {{ refused.stop_reason }}</p>
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
