/** 云服务配置状态：凭证只写不读（输入框值不落任何客户端存储）。 */

import { defineStore } from "pinia";
import { ref } from "vue";
import { configApi, type CapabilityPayload, type ConfigView } from "../api";

export const useConfigStore = defineStore("config", () => {
  const view = ref<ConfigView | null>(null);
  const open = ref(false);
  const busy = ref(false);
  const notice = ref("");
  const error = ref("");

  async function load() {
    error.value = "";
    try {
      view.value = await configApi.get();
    } catch (err) {
      error.value = err instanceof Error ? err.message : String(err);
    }
  }

  function show() {
    open.value = true;
    notice.value = "";
    void load();
  }

  function hide() {
    open.value = false;
  }

  async function save(capability: string, payload: CapabilityPayload) {
    busy.value = true;
    error.value = "";
    try {
      await configApi.update(capability, payload);
      notice.value = `${capability} 配置已保存（密钥仅加密存储）`;
      await load();
    } catch (err) {
      // 校验失败保留旧值（后端语义）；这里只提示
      error.value = err instanceof Error ? err.message : String(err);
    } finally {
      busy.value = false;
    }
  }

  async function restore(capability: string) {
    busy.value = true;
    try {
      await configApi.remove(capability);
      notice.value = `${capability} 已恢复环境值`;
      await load();
    } catch (err) {
      error.value = err instanceof Error ? err.message : String(err);
    } finally {
      busy.value = false;
    }
  }

  async function test(capability: string, probe: boolean, confirmFingerprint?: string) {
    busy.value = true;
    try {
      const result = await configApi.test(capability, { probe, confirm_fingerprint: confirmFingerprint });
      notice.value = `${capability} 验证：${result.validation}`;
      await load();
    } catch (err) {
      error.value = err instanceof Error ? err.message : String(err);
    } finally {
      busy.value = false;
    }
  }

  async function approve(capability: string) {
    busy.value = true;
    try {
      await configApi.approveOutbound(capability);
      notice.value = `${capability} 出站授权已登记（配置变更后需重新授权）`;
      await load();
    } catch (err) {
      error.value = err instanceof Error ? err.message : String(err);
    } finally {
      busy.value = false;
    }
  }

  async function rotateKey(newKey: string) {
    busy.value = true;
    try {
      const result = await configApi.rotateKey(newKey);
      notice.value = `主密钥轮换完成（${result.rotated} 条）；${result.note}`;
    } catch (err) {
      error.value = err instanceof Error ? err.message : String(err);
    } finally {
      busy.value = false;
    }
  }

  return { view, open, busy, notice, error, load, show, hide, save, restore, test, approve, rotateKey };
});
