<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { useResearchStore } from '../stores/research'
import { exportMarkdown, exportPdf, exportWord } from '../utils/export'
import ResearchForm from '../components/research/ResearchForm.vue'
import SessionSidebar from '../components/research/SessionSidebar.vue'
import TopologyGraph from '../components/research/TopologyGraph.vue'
import ProgressBar from '../components/research/ProgressBar.vue'
import MetricsCard from '../components/research/MetricsCard.vue'
import ReportViewer from '../components/research/ReportViewer.vue'
import AuditTrail from '../components/research/AuditTrail.vue'
import DetailPanel from '../components/research/DetailPanel.vue'

const store = useResearchStore()
const selectedAgent = ref<string | null>(null)
const loadingTasks = ref(false)

const activeSession = computed(() => store.activeSession)
const currentTask = computed(() => activeSession.value?.task || null)
const topology = computed(() => currentTask.value?.selected_topology || 'hierarchical')
const report = computed(() => currentTask.value?.result?.report)
const metrics = computed(() => currentTask.value?.result?.metrics)
const trail = computed(() => currentTask.value?.result?.audit_trail || [])
const claimGraph = computed(() => currentTask.value?.result?.claim_graph || [])
const currentNodeStates = computed(() => activeSession.value?.nodeStates || {})
const currentAgentDetails = computed(() => activeSession.value?.agentDetails || {})
const currentEvents = computed(() => activeSession.value?.events || [])

const debateBranches = computed(() => {
  return Object.keys(currentNodeStates.value).filter(k => k.startsWith('h_'))
})
const hasSupplementarySearch = computed(() => {
  return Object.keys(currentNodeStates.value).includes('supplementary_search')
})

onMounted(async () => {
  loadingTasks.value = true
  try {
    await store.loadTasks()
  } catch {
    ElMessage.error('加载研究会话失败')
  } finally {
    loadingTasks.value = false
  }
})

async function handleSubmit(query: string, taskType: string, depth: string) {
  selectedAgent.value = null
  try {
    await store.submitResearch(query, taskType, depth)
  } catch (e: any) {
    ElMessage.error(e?.message || '研究任务启动失败，请重试')
  }
}

function handleSelectAgent(agent: string) {
  selectedAgent.value = selectedAgent.value === agent ? null : agent
}

async function handleSelectSession(taskId: string) {
  selectedAgent.value = null
  try {
    await store.selectSession(taskId)
  } catch {
    ElMessage.error('切换研究会话失败')
  }
}

function handleNewSession() {
  selectedAgent.value = null
  store.startNewSessionDraft()
}

async function handleDeleteSession(taskId: string) {
  try {
    await ElMessageBox.confirm('删除后将无法从历史会话中恢复，确定继续吗？', '删除历史会话', {
      type: 'warning',
      confirmButtonText: '删除',
      cancelButtonText: '取消',
    })
  } catch {
    return
  }

  selectedAgent.value = null
  try {
    await store.deleteSession(taskId)
    ElMessage.success('历史会话已删除')
  } catch (e: any) {
    ElMessage.error(e?.message || '删除历史会话失败')
  }
}

async function handleCancel() {
  if (!currentTask.value) return
  try {
    await store.cancelTask(currentTask.value.task_id)
    ElMessage.info('已发送终止请求')
  } catch {
    ElMessage.error('终止失败')
  }
}
</script>

<template>
  <div class="flex h-full min-h-0">
    <SessionSidebar
      :sessions="store.sessions"
      :session-order="store.sessionOrder"
      :active-session-id="store.activeSessionId"
      :has-draft-session="store.hasDraftSession"
      :new-session-id="store.NEW_SESSION_ID"
      @select="handleSelectSession"
      @delete="handleDeleteSession"
      @new-session="handleNewSession"
    />

    <div class="flex-1 min-w-0 overflow-auto">
      <ResearchForm @submit="handleSubmit" />

      <div v-if="currentTask" class="px-6 pb-4">
        <div class="flex items-center gap-2 mb-3">
          <span class="text-[10px] font-display tracking-widest text-gray-500">TOPOLOGY</span>
          <span class="text-xs font-mono px-2 py-0.5 rounded border"
            :class="topology === 'debate' ? 'text-cyber-purple border-cyber-purple/30 bg-cyber-purple/10' : 'text-cyber-cyan border-cyber-cyan/30 bg-cyber-cyan/10'">
            {{ topology.toUpperCase() }}
          </span>
          <span class="text-[10px] font-mono text-gray-600 ml-auto">{{ currentTask.task_id }}</span>
          <el-button
            v-if="currentTask.status === 'running'"
            type="danger"
            size="small"
            plain
            @click="handleCancel"
            class="!ml-2"
          >
            终止
          </el-button>
          <el-dropdown v-if="report && (currentTask.status === 'completed' || currentTask.status === 'failed')" trigger="click" class="!ml-2">
            <el-button size="small" plain>
              下载报告
            </el-button>
            <template #dropdown>
              <el-dropdown-menu>
                <el-dropdown-item @click="exportMarkdown(report)">导出 Markdown</el-dropdown-item>
                <el-dropdown-item @click="exportPdf(report)">导出 PDF</el-dropdown-item>
                <el-dropdown-item @click="exportWord(report)">导出 Word</el-dropdown-item>
              </el-dropdown-menu>
            </template>
          </el-dropdown>
        </div>

        <ProgressBar :progress="currentTask.progress" :stage="currentTask.current_stage" />

        <div class="mt-3">
          <TopologyGraph
            :topology="topology"
            :node-states="currentNodeStates"
            :agent-details="currentAgentDetails"
            :debate-branches="debateBranches"
            :has-supplementary-search="hasSupplementarySearch"
            @select-agent="handleSelectAgent"
          />
        </div>

        <div v-if="selectedAgent" class="mt-3">
          <DetailPanel
            :agent="selectedAgent"
            :detail="currentAgentDetails[selectedAgent]"
            @close="selectedAgent = null"
          />
        </div>

        <div v-if="currentEvents.length" class="mt-3 bg-cyber-card rounded-xl border border-cyber-border px-6 py-4">
          <h3 class="font-display text-xs text-cyber-cyan mb-3 tracking-wider">ACTIVITY LOG</h3>
          <div class="max-h-48 overflow-auto space-y-0.5">
            <div
              v-for="(event, i) in currentEvents"
              :key="i"
              class="text-xs font-mono text-gray-400 py-0.5 flex gap-2"
            >
              <span class="text-gray-600 shrink-0">{{ event._time }}</span>
              <span v-if="event.agent" class="text-cyber-cyan shrink-0">[{{ event.agent }}]</span>
              <span class="truncate">{{ event.message || event.type }}</span>
            </div>
          </div>
        </div>

        <div v-if="metrics" class="mt-4">
          <MetricsCard :metrics="metrics" />
        </div>

        <div v-if="report && (currentTask.status === 'completed' || currentTask.status === 'failed')" class="mt-4 bg-cyber-card rounded-xl border border-cyber-border">
          <div class="flex items-center justify-between px-6 pt-4 pb-2">
            <h3 class="font-display text-xs text-cyber-cyan tracking-wider">REPORT</h3>
            <div class="flex gap-2">
              <button
                class="px-3 py-1 text-xs font-mono rounded border border-cyber-cyan/40 text-cyber-cyan hover:bg-cyber-cyan/10 transition-colors"
                @click="exportMarkdown(report)"
              >MD</button>
              <button
                class="px-3 py-1 text-xs font-mono rounded border border-cyber-purple/40 text-cyber-purple hover:bg-cyber-purple/10 transition-colors"
                @click="exportPdf(report)"
              >PDF</button>
              <button
                class="px-3 py-1 text-xs font-mono rounded border border-cyber-green/40 text-cyber-green hover:bg-cyber-green/10 transition-colors"
                @click="exportWord(report)"
              >Word</button>
            </div>
          </div>
          <ReportViewer :report="report" :claim-graph="claimGraph" />
        </div>

        <div v-if="trail.length" class="mt-4 bg-cyber-card rounded-xl border border-cyber-border">
          <AuditTrail :trail="trail" />
        </div>

        <div v-if="currentTask.status === 'failed'" class="mt-4 p-4 rounded-xl bg-cyber-pink/10 border border-cyber-pink/30">
          <div class="text-sm text-cyber-pink font-display">ERROR</div>
          <div class="text-xs text-gray-400 mt-1 font-mono">{{ currentTask.error }}</div>
        </div>
      </div>

      <div v-else class="flex flex-col items-center justify-center h-[60vh] text-gray-600">
        <div class="font-display text-4xl mb-4 tracking-widest opacity-20">DR</div>
        <div class="text-sm">{{ loadingTasks ? '正在加载研究会话...' : '已进入新会话，输入研究主题开始' }}</div>
      </div>
    </div>
  </div>
</template>
