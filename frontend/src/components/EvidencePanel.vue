<script setup lang="ts">
import { computed } from "vue";
import { useTasksStore } from "../stores/tasks";
import type { EvidenceView } from "../types";

const store = useTasksStore();

/** 已作答：完整证据卡；运行中：从 evidence 事件先占位（id/类型/范围）。 */
const evidenceCards = computed(() => {
  const fromAnswer: EvidenceView[] = store.answer?.evidence ?? [];
  if (fromAnswer.length) return fromAnswer.map((ev) => ({ ev, placeholder: false }));
  const seen = new Set<string>();
  const placeholders: { ev: EvidenceView; placeholder: boolean }[] = [];
  for (const event of store.events) {
    if (event.type !== "evidence") continue;
    const payload = event.payload as { citation_id: string; source_type: string; content_scope: string };
    if (seen.has(payload.citation_id)) continue;
    seen.add(payload.citation_id);
    placeholders.push({
      ev: {
        citation_id: payload.citation_id,
        source_type: payload.source_type,
        content_scope: payload.content_scope,
        raw_text: null,
        provenance: { provider: "" },
        locator: {},
      },
      placeholder: true,
    });
  }
  return placeholders;
});

function sourceBadge(ev: EvidenceView): string {
  if (ev.source_type === "kb_chunk") return "kb";
  if (ev.source_type === "paper") return "paper";
  return "web";
}

function sourceLabel(ev: EvidenceView): string {
  if (ev.source_type === "kb_chunk") return "知识库";
  if (ev.source_type === "paper") return "论文";
  return "网页";
}

function scopeLabel(scope: string): string {
  return { fulltext: "全文", abstract: "摘要", snippet: "片段", region: "区域" }[scope] ?? scope;
}

function locationLabel(ev: EvidenceView): string {
  const parts: string[] = [];
  if (ev.provenance.doc_title || ev.provenance.doc_id) parts.push(ev.provenance.doc_title || ev.provenance.doc_id || "");
  if (ev.locator.page) parts.push(`第 ${ev.locator.page} 页`);
  if (ev.provenance.arxiv_id) parts.push(`arXiv ${ev.provenance.arxiv_id}${ev.provenance.arxiv_version ?? ""}`);
  if (ev.provenance.canonical_url || ev.locator.url) parts.push(ev.provenance.canonical_url || ev.locator.url || "");
  return parts.filter(Boolean).join(" · ");
}
</script>

<template>
  <section class="evidence scroll">
    <header class="panel-head">
      <h3>证据</h3>
      <span class="badge">{{ evidenceCards.length }} 条</span>
    </header>

    <p v-if="!evidenceCards.length" class="muted empty">尚无证据。发起提问后，Agent 登记的来源会实时出现在这里。</p>

    <article
      v-for="({ ev, placeholder }, i) in evidenceCards"
      :key="ev.citation_id + i"
      class="card fade-up"
      :class="{ active: store.selectedCitation === ev.citation_id }"
      role="button"
      :aria-label="`证据 ${ev.citation_id}`"
      @click="store.selectCitation(ev.citation_id)"
    >
      <div class="card-head">
        <span class="mono cid">{{ ev.citation_id }}</span>
        <span class="badge" :class="sourceBadge(ev)">{{ sourceLabel(ev) }}</span>
        <span class="badge" :class="{ warn: ev.content_scope !== 'fulltext' }">{{ scopeLabel(ev.content_scope) }}</span>
      </div>
      <div v-if="locationLabel(ev)" class="loc muted">{{ locationLabel(ev) }}</div>
      <p v-if="ev.raw_text" class="text">{{ ev.raw_text.slice(0, 420) }}{{ ev.raw_text.length > 420 ? " …" : "" }}</p>
      <p v-else class="muted text">采集中…（完成后展示原文与页码）</p>
    </article>
  </section>
</template>

<style scoped>
.evidence {
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

.empty {
  margin-top: 2rem;
}

.card {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  padding: 0.8rem 0.9rem;
  cursor: pointer;
  transition: border-color 150ms ease-out, transform 150ms ease-out;
}

.card:hover {
  transform: translateY(-1px);
  border-color: var(--border-strong);
}

.card.active {
  border-color: var(--primary);
  box-shadow: 0 0 0 1px oklch(0.72 0.14 172 / 0.35);
}

.card-head {
  display: flex;
  align-items: center;
  gap: 0.45rem;
  flex-wrap: wrap;
}

.cid {
  color: var(--primary);
}

.loc {
  font-size: 12px;
  margin: 0.35rem 0;
}

.text {
  margin: 0.35rem 0 0;
  font-size: 13px;
  line-height: 1.65;
  white-space: pre-wrap;
}
</style>
