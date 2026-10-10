<script setup lang="ts">
import { reactive, ref } from "vue";
import { useConfigStore } from "../stores/config";

const store = useConfigStore();
const forms = reactive<Record<string, { provider: string; model: string; base_url: string; api_key: string }>>({});
const rotateForm = ref("");

const CAP_LABELS: Record<string, string> = {
  llm: "生成 / 规划 / 验证 LLM",
  embedding: "Embedding",
  reranker: "Reranker（可选）",
  ocr: "云 OCR",
  vision: "云视觉",
};

function form(capability: string) {
  if (!forms[capability]) {
    const current = store.view?.capabilities[capability];
    forms[capability] = {
      provider: current?.provider ?? "",
      model: current?.model ?? "",
      base_url: current?.base_url ?? "",
      api_key: "", // 只写不读：不回填旧密钥
    };
  }
  return forms[capability];
}

async function save(capability: string) {
  const f = form(capability);
  const payload: Record<string, string> = { provider: f.provider, model: f.model, base_url: f.base_url };
  if (f.api_key) payload.api_key = f.api_key;
  await store.save(capability, payload);
  f.api_key = "";
}
</script>

<template>
  <div v-if="store.open" class="overlay" role="dialog" aria-label="云服务设置" @click.self="store.hide()">
    <section class="panel">
      <header>
        <h2>云服务设置</h2>
        <button class="ghost" @click="store.hide()">关闭</button>
      </header>

      <p v-if="store.notice" class="notice">{{ store.notice }}</p>
      <p v-if="store.error" class="err">{{ store.error }}</p>
      <p v-if="store.view && !store.view.vault_enabled" class="err">
        CONFIG_ENCRYPTION_KEY 未配置：凭证保存被拒绝（不回退明文）。请在启动环境设置主密钥后重启。
      </p>

      <div v-if="store.view" class="body scroll">
        <article v-for="(label, cap) in CAP_LABELS" :key="cap" class="card">
          <div class="card-head">
            <h3>{{ label }}</h3>
            <span class="badge" :class="store.view.capabilities[cap]?.configured ? 'ok' : 'warn'">
              {{ store.view.capabilities[cap]?.configured ? "已配置" : "未配置" }}
            </span>
            <span class="badge">{{ store.view.capabilities[cap]?.source === "override" ? "运行时覆盖" : "环境变量" }}</span>
            <span v-if="store.view.capabilities[cap]?.index_migration_pending" class="badge warn">待索引迁移</span>
          </div>

          <div class="grid-form">
            <label>provider<input v-model="form(cap).provider" placeholder="deepseek / openai …" /></label>
            <label>model<input v-model="form(cap).model" placeholder="deepseek-chat" /></label>
            <label class="wide">base_url<input v-model="form(cap).base_url" placeholder="https://api.deepseek.com（留空用官方默认）" /></label>
            <label class="wide"
              >api_key（只写不读）
              <input
                v-model="form(cap).api_key"
                type="password"
                autocomplete="new-password"
                :placeholder="store.view.capabilities[cap]?.api_key === 'configured' ? '已保存密钥（不回显），输入新值覆盖' : 'sk-…'"
              />
            </label>
          </div>

          <div class="actions">
            <button class="primary" :disabled="store.busy" @click="save(cap)">保存</button>
            <button :disabled="store.busy" @click="store.test(cap, false)">静态验证</button>
            <button :disabled="store.busy" @click="store.restore(cap)">恢复环境值</button>
          </div>
        </article>

        <article class="card">
          <div class="card-head">
            <h3>云出站授权</h3>
            <span class="badge" :class="store.view.outbound.upload_allowed ? 'ok' : 'err'">
              总开关 CLOUD_DATA_UPLOAD_ALLOWED={{ store.view.outbound.upload_allowed }}
            </span>
          </div>
          <p class="muted small">
            出站会外送问题/证据/文件的第三方调用受逐能力授权：指纹=能力+provider+endpoint+model（不含密钥）；
            provider/endpoint/model 变更后旧授权自动失效，需重新确认。供应商留存政策不因说明而改变。
          </p>
          <table>
            <thead>
              <tr><th>能力</th><th>指纹</th><th>状态</th><th></th></tr>
            </thead>
            <tbody>
              <tr v-for="(item, cap) in store.view.outbound.capabilities" :key="cap">
                <td>{{ cap }}</td>
                <td class="mono">{{ item.fingerprint.slice(0, 12) }}…</td>
                <td>
                  <span class="badge" :class="item.approved ? 'ok' : 'warn'">{{ item.approved ? "已授权" : item.reason }}</span>
                </td>
                <td>
                  <button :disabled="store.busy || !store.view.outbound.upload_allowed" @click="store.approve(cap)">
                    授权
                  </button>
                </td>
              </tr>
            </tbody>
          </table>
        </article>

        <article class="card">
          <div class="card-head"><h3>主密钥轮换</h3></div>
          <p class="muted small">先全量重加密并验证可解再替换；失败保留旧密文。轮换后须同步更新启动环境 CONFIG_ENCRYPTION_KEY。</p>
          <div class="actions">
            <input
              v-model="rotateForm"
              type="password"
              autocomplete="new-password"
              placeholder="新的 CONFIG_ENCRYPTION_KEY（urlsafe-base64 32 字节）"
              class="grow"
            />
            <button :disabled="store.busy || !rotateForm" @click="store.rotateKey(rotateForm)">轮换</button>
          </div>
        </article>
      </div>
    </section>
  </div>
</template>

<style scoped>
.overlay {
  position: fixed;
  inset: 0;
  background: oklch(0 0 0 / 0.55);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 50;
  padding: 1.5rem;
}

.panel {
  width: min(880px, 100%);
  max-height: 88vh;
  display: flex;
  flex-direction: column;
  background: var(--background);
  border: 1px solid var(--border-strong);
  border-radius: var(--radius);
  box-shadow: var(--shadow);
  overflow: hidden;
}

.panel > header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 1rem 1.25rem;
  border-bottom: 1px solid var(--border);
}

.panel h2 {
  margin: 0;
  font-size: 16px;
}

.notice {
  margin: 0.5rem 1.25rem 0;
  padding: 0.5rem 0.75rem;
  border-radius: var(--radius-sm);
  background: oklch(0.3 0.05 155 / 0.18);
  color: var(--success);
  font-size: 12.5px;
}

.err {
  margin: 0.5rem 1.25rem 0;
  padding: 0.5rem 0.75rem;
  border-radius: var(--radius-sm);
  background: oklch(0.3 0.07 25 / 0.2);
  color: oklch(0.8 0.1 25);
  font-size: 12.5px;
}

.body {
  padding: 1rem 1.25rem 1.25rem;
  display: flex;
  flex-direction: column;
  gap: 1rem;
}

.card {
  border: 1px solid var(--border);
  border-radius: var(--radius);
  padding: 0.9rem 1rem;
  background: var(--surface);
}

.card-head {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  flex-wrap: wrap;
  margin-bottom: 0.65rem;
}

.card-head h3 {
  margin: 0;
  font-size: 13.5px;
}

.grid-form {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 0.6rem;
}

.grid-form label {
  display: flex;
  flex-direction: column;
  gap: 0.25rem;
  font-size: 11.5px;
  color: var(--muted-foreground);
}

.grid-form .wide {
  grid-column: 1 / -1;
}

.grid-form input {
  font: inherit;
  color: var(--foreground);
  background: var(--paper);
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  padding: 0.45rem 0.6rem;
}

.actions {
  display: flex;
  gap: 0.55rem;
  margin-top: 0.75rem;
  align-items: center;
  flex-wrap: wrap;
}

.actions .grow {
  flex: 1;
  min-width: 220px;
  font: inherit;
  color: var(--foreground);
  background: var(--paper);
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  padding: 0.45rem 0.6rem;
}

.small {
  font-size: 12px;
  margin: 0.25rem 0 0.65rem;
}

table {
  width: 100%;
  border-collapse: collapse;
  font-size: 12.5px;
}

th,
td {
  text-align: left;
  padding: 0.4rem 0.5rem;
  border-bottom: 1px solid var(--border);
}

th {
  color: var(--muted-foreground);
  font-weight: 600;
}
</style>
