<script setup lang="ts">
import { computed } from 'vue'
import { Delete, Plus } from '@element-plus/icons-vue'
import type { ResearchSession } from '../../stores/research'

const props = defineProps<{
  sessions: Record<string, ResearchSession>
  sessionOrder: string[]
  activeSessionId: string | null
  hasDraftSession?: boolean
  newSessionId: string
}>()

const emit = defineEmits<{
  select: [taskId: string]
  delete: [taskId: string]
  newSession: []
}>()

const orderedSessions = computed(() => {
  return props.sessionOrder
    .map(taskId => props.sessions[taskId])
    .filter((session): session is ResearchSession => Boolean(session))
})

function statusClass(status: string) {
  if (status === 'completed') return 'text-cyber-green border-cyber-green/30 bg-cyber-green/10'
  if (status === 'failed') return 'text-cyber-pink border-cyber-pink/30 bg-cyber-pink/10'
  if (status === 'cancelled') return 'text-gray-400 border-gray-500/30 bg-gray-500/10'
  return 'text-cyber-cyan border-cyber-cyan/30 bg-cyber-cyan/10'
}

function sessionTitle(session: ResearchSession) {
  if (session.isDraft) return '新会话'
  return session.query || session.task?.task_id || '未命名会话'
}

function handleDelete(taskId: string, event: MouseEvent) {
  event.stopPropagation()
  emit('delete', taskId)
}
</script>

<template>
  <aside class="w-80 shrink-0 border-r border-cyber-border bg-cyber-card/40 backdrop-blur-sm">
    <div class="px-4 py-4 border-b border-cyber-border space-y-3">
      <div>
        <div class="font-display text-xs tracking-widest text-cyber-cyan">RESEARCH SESSIONS</div>
        <div class="text-xs text-gray-500 mt-1">每个研究任务都是一个可切换会话</div>
      </div>
      <el-button type="primary" plain class="!w-full" @click="emit('newSession')">
        <el-icon class="mr-1"><Plus /></el-icon>
        新建会话
      </el-button>
    </div>

    <div v-if="hasDraftSession || orderedSessions.length" class="p-3 space-y-2 overflow-auto h-[calc(100vh-129px)]">
      <button
        v-if="hasDraftSession"
        class="w-full text-left rounded-xl border px-3 py-3 transition-all"
        :class="activeSessionId === newSessionId
          ? 'border-cyber-purple bg-cyber-purple/10 shadow-glow-sm'
          : 'border-cyber-border bg-cyber-card hover:border-cyber-purple/40 hover:bg-cyber-purple/5'"
        @click="emit('select', newSessionId)"
      >
        <div class="flex items-start gap-2">
          <div class="min-w-0 flex-1">
            <div class="text-sm text-gray-200">新会话</div>
            <div class="mt-1 text-[10px] font-mono text-gray-500">draft</div>
          </div>
          <span class="shrink-0 rounded border px-2 py-0.5 text-[10px] font-mono uppercase text-cyber-purple border-cyber-purple/30 bg-cyber-purple/10">
            draft
          </span>
        </div>
        <div class="mt-3 text-[11px] text-gray-500">尚未开始研究，可直接输入新主题</div>
      </button>

      <button
        v-for="session in orderedSessions"
        :key="session.task?.task_id"
        class="w-full text-left rounded-xl border px-3 py-3 transition-all"
        :class="session.task?.task_id === activeSessionId
          ? 'border-cyber-cyan bg-cyber-cyan/10 shadow-glow-sm'
          : 'border-cyber-border bg-cyber-card hover:border-cyber-cyan/40 hover:bg-cyber-cyan/5'"
        @click="session.task && emit('select', session.task.task_id)"
      >
        <div class="flex items-start gap-2">
          <div class="min-w-0 flex-1">
            <div class="text-sm text-gray-200 line-clamp-2 break-all">{{ sessionTitle(session) }}</div>
            <div class="mt-1 text-[10px] font-mono text-gray-500">{{ session.task?.task_id }}</div>
          </div>
          <div class="flex items-start gap-2 shrink-0">
            <span
              class="rounded border px-2 py-0.5 text-[10px] font-mono uppercase"
              :class="statusClass(session.task?.status || 'running')"
            >
              {{ session.task?.status }}
            </span>
            <el-button
              v-if="session.task"
              circle
              size="small"
              plain
              class="!border-cyber-pink/30 !text-cyber-pink"
              :disabled="session.task.status === 'running'"
              @click="handleDelete(session.task.task_id, $event)"
            >
              <el-icon><Delete /></el-icon>
            </el-button>
          </div>
        </div>

        <div class="mt-3 flex items-center justify-between text-[11px] text-gray-500">
          <span>{{ session.task?.selected_topology }}</span>
          <span>{{ session.task?.progress }}%</span>
        </div>

        <div class="mt-1 h-1.5 rounded-full bg-cyber-border overflow-hidden">
          <div
            class="h-full rounded-full bg-gradient-to-r from-cyber-cyan to-cyber-purple transition-all"
            :style="{ width: `${session.task?.progress || 0}%` }"
          />
        </div>
      </button>
    </div>

    <div v-else class="h-[calc(100vh-129px)] flex items-center justify-center px-6 text-center text-sm text-gray-500">
      还没有研究会话，先点击上方按钮新建会话。
    </div>
  </aside>
</template>
