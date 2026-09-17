import { defineStore } from 'pinia'
import { computed, ref } from 'vue'
import { createResearch, getResearch, listResearch, streamResearch, cancelResearch, deleteResearch, type TaskResult } from '../api/research'

export interface AgentDetail {
  model?: string
  message?: string
  output?: any
  streamContent?: string
  latencyMs?: number
  tokens?: number
  activityLog: string[]
}

export interface ResearchSession {
  task?: TaskResult
  query: string
  taskType: string
  depth: string
  events: any[]
  nodeStates: Record<string, string>
  agentDetails: Record<string, AgentDetail>
  loading: boolean
  subscribed: boolean
  isDraft?: boolean
}

const NEW_SESSION_ID = 'draft:new'

export const useResearchStore = defineStore('research', () => {
  const sessions = ref<Record<string, ResearchSession>>({})
  const sessionOrder = ref<string[]>([])
  const activeSessionId = ref<string | null>(null)
  const draftSession = ref<ResearchSession | null>(null)

  const sseSources = new Map<string, EventSource>()
  const pollIntervals = new Map<string, ReturnType<typeof setInterval>>()
  const tokenBuffers = new Map<string, Record<string, string>>()
  const tokenFlushTimers = new Map<string, ReturnType<typeof setTimeout>>()
  const lastActiveSessionStorageKey = 'deep-research:last-active-task-id'

  const activeSession = computed(() => {
    if (!activeSessionId.value) return null
    if (activeSessionId.value === NEW_SESSION_ID) return draftSession.value
    return sessions.value[activeSessionId.value] || null
  })
  const currentTask = computed(() => activeSession.value?.task || null)
  const loading = computed(() => activeSession.value?.loading || false)
  const events = computed(() => activeSession.value?.events || [])
  const nodeStates = computed(() => activeSession.value?.nodeStates || {})
  const agentDetails = computed(() => activeSession.value?.agentDetails || {})
  const hasDraftSession = computed(() => Boolean(draftSession.value))

  function isTerminalStatus(status?: string) {
    return status === 'completed' || status === 'failed' || status === 'cancelled'
  }

  function buildDraftSession(): ResearchSession {
    return {
      query: '',
      taskType: 'industry_report',
      depth: 'standard',
      events: [],
      nodeStates: {},
      agentDetails: {},
      loading: false,
      subscribed: false,
      isDraft: true,
    }
  }

  function ensureSessionOrder(taskId: string) {
    sessionOrder.value = [taskId, ...sessionOrder.value.filter(id => id !== taskId)]
  }

  function createSession(task: TaskResult, meta?: Partial<Pick<ResearchSession, 'query' | 'taskType' | 'depth'>>) {
    const existing = sessions.value[task.task_id]
    sessions.value[task.task_id] = {
      task,
      query: meta?.query ?? existing?.query ?? '',
      taskType: meta?.taskType ?? existing?.taskType ?? '',
      depth: meta?.depth ?? existing?.depth ?? '',
      events: existing?.events ?? [],
      nodeStates: existing?.nodeStates ?? {},
      agentDetails: existing?.agentDetails ?? {},
      loading: existing?.loading ?? task.status === 'running',
      subscribed: existing?.subscribed ?? false,
      isDraft: false,
    }
    ensureSessionOrder(task.task_id)
    return sessions.value[task.task_id]
  }

  function persistActiveSession(taskId: string | null) {
    if (typeof window === 'undefined') return
    if (taskId && taskId !== NEW_SESSION_ID) {
      window.localStorage.setItem(lastActiveSessionStorageKey, taskId)
    } else {
      window.localStorage.removeItem(lastActiveSessionStorageKey)
    }
  }

  function setActiveSession(taskId: string | null) {
    activeSessionId.value = taskId
    persistActiveSession(taskId)
  }

  function getTokenBuffer(taskId: string) {
    let buffer = tokenBuffers.get(taskId)
    if (!buffer) {
      buffer = {}
      tokenBuffers.set(taskId, buffer)
    }
    return buffer
  }

  function flushAgentTokens(taskId: string, agent: string) {
    const session = sessions.value[taskId]
    if (!session) return
    const buffer = getTokenBuffer(taskId)
    const tokens = buffer[agent]
    if (!tokens) return
    delete buffer[agent]
    if (!session.agentDetails[agent]) {
      session.agentDetails[agent] = { activityLog: [] }
    }
    const detail = session.agentDetails[agent]
    if (!detail.streamContent) detail.streamContent = ''
    detail.streamContent += tokens
    detail.message = detail.streamContent.slice(-80)
  }

  function flushTokens(taskId: string) {
    const session = sessions.value[taskId]
    if (!session) return
    const timer = tokenFlushTimers.get(taskId)
    if (timer) {
      clearTimeout(timer)
      tokenFlushTimers.delete(taskId)
    }
    const buffer = getTokenBuffer(taskId)
    for (const [agent, tokens] of Object.entries(buffer)) {
      if (!tokens) continue
      if (!session.agentDetails[agent]) {
        session.agentDetails[agent] = { activityLog: [] }
      }
      const detail = session.agentDetails[agent]
      if (!detail.streamContent) detail.streamContent = ''
      detail.streamContent += tokens
      detail.message = detail.streamContent.slice(-80)
    }
    tokenBuffers.set(taskId, {})
  }

  function stopRuntime(taskId: string) {
    const source = sseSources.get(taskId)
    if (source) {
      source.close()
      sseSources.delete(taskId)
    }
    const interval = pollIntervals.get(taskId)
    if (interval) {
      clearInterval(interval)
      pollIntervals.delete(taskId)
    }
    const timer = tokenFlushTimers.get(taskId)
    if (timer) {
      clearTimeout(timer)
      tokenFlushTimers.delete(taskId)
    }
    tokenBuffers.delete(taskId)
  }

  function markSessionTerminal(taskId: string) {
    const session = sessions.value[taskId]
    if (!session) return
    flushTokens(taskId)
    session.loading = false
    session.subscribed = false
    stopRuntime(taskId)
  }

  function addEvent(taskId: string, event: any) {
    const session = sessions.value[taskId]
    if (!session) return
    const timestamp = new Date().toLocaleTimeString('zh-CN', { hour12: false })

    if (event.type === 'agent_stream_token') {
      if (event.agent) {
        const buffer = getTokenBuffer(taskId)
        if (!buffer[event.agent]) buffer[event.agent] = ''
        buffer[event.agent] += event.token
        if (!tokenFlushTimers.get(taskId)) {
          const timer = setTimeout(() => flushTokens(taskId), 50)
          tokenFlushTimers.set(taskId, timer)
        }
      }
      return
    }

    session.events.push({ ...event, _time: timestamp })
    if (session.events.length > 200) {
      session.events.splice(0, session.events.length - 200)
    }

    if (event.type === 'state' && event.data) {
      const taskData = event.data as TaskResult
      if (!taskData.result && session.task?.result) {
        taskData.result = session.task.result
      }
      session.task = taskData
      session.loading = taskData.status === 'running'
      return
    }

    if (event.agent) {
      const agent = event.agent
      if (!session.agentDetails[agent]) {
        session.agentDetails[agent] = { activityLog: [] }
      }
      const detail = session.agentDetails[agent]

      if (event.type === 'stage_start') {
        session.nodeStates[agent] = 'running'
        detail.streamContent = ''
      } else if (event.type === 'stage_complete') {
        session.nodeStates[agent] = 'completed'
        flushAgentTokens(taskId, agent)
      }

      if (event.type === 'agent_model_selected') {
        detail.model = event.model
        detail.activityLog.push(`[${timestamp}] ${event.message}`)
      }
      if (event.type === 'agent_thinking') {
        detail.message = event.message
        if (event.latency_ms) detail.latencyMs = event.latency_ms
        if (event.tokens) detail.tokens = event.tokens
        detail.activityLog.push(`[${timestamp}] ${event.message}`)
      }
      if (event.type === 'agent_output') {
        detail.output = event.output
        detail.message = event.message
        detail.activityLog.push(`[${timestamp}] ${event.message}`)
      }
      if (event.type === 'subtask_complete') {
        detail.activityLog.push(`[${timestamp}] ${event.message}`)
      }
    }

    if (session.task) {
      if (event.progress !== undefined) {
        session.task.progress = event.progress
      }
      if (event.current_stage) {
        session.task.current_stage = event.current_stage
      } else if (event.agent) {
        session.task.current_stage = event.agent
      }
    }

    if (event.type === 'report_update' && event.output && session.task) {
      if (!session.task.result) {
        session.task.result = { report: event.output, metrics: {}, audit_trail: [] }
      } else {
        session.task.result.report = event.output
      }
    }

    if ((event.type === 'done' || event.type === 'cancelled' || event.type === 'error') && session.task) {
      if (event.type === 'done') {
        const incoming = event.result
        if (incoming && !incoming.report && session.task.result?.report) {
          incoming.report = session.task.result.report
        }
        if (incoming) {
          session.task.result = incoming
        }
        session.task.status = 'completed'
        session.task.progress = 100
        session.task.current_stage = event.current_stage || 'completed'
      }
      if (event.type === 'cancelled') {
        session.task.status = 'cancelled'
      }
      if (event.type === 'error') {
        session.task.status = 'failed'
        session.task.error = event.error || session.task.error
      }
      markSessionTerminal(taskId)
    }
  }

  function ensureSubscribed(taskId: string) {
    const session = sessions.value[taskId]
    if (!session?.task || isTerminalStatus(session.task.status) || sseSources.has(taskId)) return

    const source = streamResearch(taskId, (event) => {
      addEvent(taskId, event)
    }, () => {
      sseSources.delete(taskId)
      const target = sessions.value[taskId]
      if (!target?.task || isTerminalStatus(target.task.status)) return
      if (target.loading) {
        target.loading = false
      }
    })

    sseSources.set(taskId, source)
    session.subscribed = true
  }

  function pollTask(taskId: string) {
    const existing = pollIntervals.get(taskId)
    if (existing) clearInterval(existing)

    const interval = setInterval(async () => {
      const session = sessions.value[taskId]
      if (!session?.task) {
        stopRuntime(taskId)
        return
      }
      try {
        const task = await getResearch(taskId)
        if (!task.result && session.task.result) {
          task.result = session.task.result
        }
        if (task.result && !task.result.report && session.task.result?.report) {
          task.result.report = session.task.result.report
        }
        session.task = task
        session.loading = task.status === 'running'

        if (isTerminalStatus(task.status)) {
          markSessionTerminal(taskId)
        }
      } catch {
        markSessionTerminal(taskId)
      }
    }, 2000)

    pollIntervals.set(taskId, interval)
  }

  function startNewSessionDraft() {
    draftSession.value = buildDraftSession()
    setActiveSession(NEW_SESSION_ID)
  }

  function selectFallbackSession(removedTaskId?: string) {
    const remaining = sessionOrder.value.filter(id => id !== removedTaskId)
    if (remaining.length) {
      setActiveSession(remaining[0])
      return
    }
    startNewSessionDraft()
  }

  function removeSessionLocally(taskId: string) {
    stopRuntime(taskId)
    delete sessions.value[taskId]
    sessionOrder.value = sessionOrder.value.filter(id => id !== taskId)
  }

  async function loadTasks() {
    const tasks = await listResearch()
    for (const task of tasks.sort((a, b) => (b.created_at || '').localeCompare(a.created_at || ''))) {
      createSession(task)
      if (task.status === 'running') {
        ensureSubscribed(task.task_id)
        pollTask(task.task_id)
      }
    }

    const lastActiveTaskId = typeof window === 'undefined'
      ? null
      : window.localStorage.getItem(lastActiveSessionStorageKey)

    if (lastActiveTaskId && sessions.value[lastActiveTaskId]) {
      setActiveSession(lastActiveTaskId)
      return
    }

    if (!activeSessionId.value && sessionOrder.value.length) {
      setActiveSession(sessionOrder.value[0])
      return
    }

    if (!activeSessionId.value) {
      startNewSessionDraft()
    }
  }

  async function submitResearch(query: string, taskType: string, depth: string) {
    const task = await createResearch({ query, task_type: taskType, depth })
    const session = createSession(task, { query, taskType, depth })
    session.events = []
    session.nodeStates = {}
    session.agentDetails = {}
    session.loading = true
    session.subscribed = true
    draftSession.value = null
    setActiveSession(task.task_id)
    ensureSubscribed(task.task_id)
    pollTask(task.task_id)
    return task
  }

  async function selectSession(taskId: string) {
    if (taskId === NEW_SESSION_ID) {
      startNewSessionDraft()
      return
    }

    const existing = sessions.value[taskId]
    setActiveSession(taskId)
    if (existing) {
      if (existing.task?.status === 'running') {
        ensureSubscribed(taskId)
        if (!pollIntervals.has(taskId)) pollTask(taskId)
      }
      return
    }

    const task = await getResearch(taskId)
    createSession(task)
    if (task.status === 'running') {
      ensureSubscribed(taskId)
      pollTask(taskId)
    }
  }

  async function cancelTask(taskId: string) {
    await cancelResearch(taskId)
    const session = sessions.value[taskId]
    if (session?.task) {
      session.task.status = 'cancelled'
      session.loading = false
    }
  }

  async function deleteSession(taskId: string) {
    if (taskId === NEW_SESSION_ID) {
      draftSession.value = null
      if (activeSessionId.value === NEW_SESSION_ID) {
        selectFallbackSession()
      }
      return
    }

    const session = sessions.value[taskId]
    if (session?.task?.status === 'running') {
      throw new Error('运行中的任务不能删除，请先终止任务')
    }

    await deleteResearch(taskId)
    const deletingActive = activeSessionId.value === taskId
    removeSessionLocally(taskId)

    if (deletingActive) {
      selectFallbackSession(taskId)
    }
  }

  function reset() {
    for (const taskId of sessionOrder.value) {
      stopRuntime(taskId)
    }
    sessions.value = {}
    sessionOrder.value = []
    draftSession.value = null
    setActiveSession(null)
    tokenBuffers.clear()
    startNewSessionDraft()
  }

  return {
    sessions,
    sessionOrder,
    activeSessionId,
    activeSession,
    currentTask,
    loading,
    events,
    nodeStates,
    agentDetails,
    hasDraftSession,
    NEW_SESSION_ID,
    loadTasks,
    startNewSessionDraft,
    submitResearch,
    selectSession,
    cancelTask,
    deleteSession,
    addEvent,
    reset,
  }
})
