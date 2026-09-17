# Bug 修复记录：并发任务事件路由竞态条件

**状态**：已修复
**影响**：高；并发研究任务的 SSE 事件可能被发送到错误会话

本文记录一次重要的并发安全修复，并说明当前实现必须保持的约束。相关代码路径均以 `deep_research_system/` 为工作目录。

## 1. 问题

当同一拓扑的 Task A 尚未完成时启动 Task B，Task A 的 `stage_start`、`stage_complete`、`agent_stream_token` 等事件可能被错误发送到 Task B 的订阅队列。用户可见症状包括：

- 当前会话出现另一任务的 Agent 节点；
- token 流与查询内容不匹配；
- 原任务缺失后续阶段更新；
- 长时间运行的并行 search、reader 或 debate 阶段尤其容易暴露问题。

## 2. 根因

`ResearchService` 会复用懒加载的 `HierarchicalTopology` / `DebateTopology`，拓扑又复用相应 GraphRunner。修复前，`GraphRunner.run()` 把当前调用的 `on_event` 存入共享实例字段：

```python
# 修复前的概念代码
async def run(self, state, on_event=None):
    self._active_on_event = on_event
    try:
        return await self.graph.ainvoke({"state": state})
    finally:
        self._active_on_event = None
```

节点在跨越 `await` 后继续读取 `self._active_on_event`。如果另一任务已覆盖该字段，前一任务便会调用后一任务的回调。

```text
Task A: run(on_event_A) → self._active_on_event = on_event_A
Task A: await agent.run(...)                         ─┐
Task B: run(on_event_B) → self._active_on_event = on_event_B
Task A: 恢复并读取 self._active_on_event → on_event_B  ✗
```

`ResearchService._execute()` 中的回调闭包捕获自己的 `task_id`，因此调用错误回调不仅会贴错 ID，还会把事件广播到错误任务的 SSE 队列。

## 3. 当前修复

修复将请求级回调迁移到 LangGraph 的 `GraphContext`。

### 3.1 GraphContext

`app/graphs/graph_state.py` 定义共享类型别名与图上下文：

```python
EventCallback = Callable[[dict], Awaitable[None]] | Callable[[dict], None] | None

class GraphContext(TypedDict):
    state: ResearchState
    on_event: NotRequired[EventCallback]
    last_validation: NotRequired[dict]
    supplementary_result: NotRequired[dict | None]
    repair_attempt: NotRequired[int]
    supplementary_loop_count: NotRequired[int]
    last_plan_result: NotRequired[dict]
```

### 3.2 每次运行创建独立上下文

`app/graphs/hierarchical_graph.py` 和 `app/graphs/debate_graph.py` 的 `run()` 每次都创建新的 context：

```python
context: GraphContext = {
    "state": state,
    "on_event": on_event,
    # 本次执行的其他图状态
}
result = await self.graph.ainvoke(context)
```

每个节点从收到的 context 中读取回调：

```python
async def _planner(self, context: GraphContext):
    state = context["state"]
    on_event = context.get("on_event")
    emit(on_event, {"type": "stage_start", "agent": "planner"})
    plan_result = await self.planner.run(state, on_event=on_event)
```

并行子任务通过 `app/graphs/events.py` 的 `wrap_agent_name(on_event, name)` 包装当前 context 中的回调，而不是访问 runner 字段。

### 3.3 拓扑层保持无请求状态

`app/topology/hierarchical.py` 与 `app/topology/debate.py` 仍可懒加载和复用 runner，因为它们只执行：

```python
return await self._get_graph().run(state, on_event=on_event)
```

共享的是无请求状态的编排对象；`ResearchState`、`on_event`、验证结果和循环计数均属于本次调用的 `GraphContext`。

## 4. 为什么修复有效

```text
Task A → context_A {state_A, on_event_A} → graph.ainvoke(context_A)
Task B → context_B {state_B, on_event_B} → graph.ainvoke(context_B)
```

即使两个协程交错执行：

1. 每次 `run()` 都分配独立 context；
2. 节点只读取自己调用链中的 context；
3. 事件辅助函数显式接收回调，不读取全局或实例状态；
4. 不需要用锁串行化整个研究流程；
5. 共享 Agent/runner 上不得新增 task ID、回调或中间结果等请求级可变字段。

## 5. 涉及文件

- `app/graphs/graph_state.py`：定义 `GraphContext` 与 `EventCallback`；
- `app/graphs/hierarchical_graph.py`：层级式节点从 context 读取事件回调；
- `app/graphs/debate_graph.py`：辩论式节点采用相同模式；
- `app/graphs/events.py`：显式接收回调的 `emit()` / `wrap_agent_name()`；
- `app/topology/hierarchical.py`、`app/topology/debate.py`：无请求状态的薄委托；
- `app/services/research_service.py`：为每个任务创建捕获其 `task_id` 的回调闭包。

## 6. 可重复验证

### 自动化检查

从 `deep_research_system/` 执行：

```bash
python -m pytest tests/ -v
```

不要在文档中固定通过数量；测试集扩充后该数字会自然变化。重点应覆盖 graph topology、ResearchService、API、取消流程和事件路由。

### 手动并发验收

1. 启动后端：`python main.py`。
2. 创建两个耗时足以重叠的同类型任务，记录 `task_id_a` 和 `task_id_b`。
3. 分别连接 SSE（所有研究接口均有 `/api` 前缀）：

```bash
curl -N http://localhost:8000/api/research/{task_id_a}/stream
curl -N http://localhost:8000/api/research/{task_id_b}/stream
```

4. 确认每条流中的 `task_id` 始终匹配对应任务。
5. 确认 `searcher_{id}`、`reader_{id}` 或动态 `h_{index}` 节点及 token 内容不跨任务混入。
6. 确认两个任务均能独立进入终态。
7. 在二者运行时取消 Task A：

```text
POST /api/research/{task_id_a}/cancel
```

8. 确认 Task A 收到 `cancelled`，Task B 继续运行。

## 7. 相关但独立的 Redis 降级行为

`app/core/redis_client.py` 在 Redis 不可用时采用冷却期降级，避免每次进度持久化都产生重复连接日志；`app/services/task_state_store.py` 也避免把降级期间的“任务不存在”放大为高等级噪声。该行为改善了并发任务期间的可观测性，但不是事件串流修复本身的正确性前提：实时 SSE 路由由每任务队列和 context 中的回调隔离保证。
