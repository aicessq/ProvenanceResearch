# frontend/ —— 统一研究前端（P5 第一版）

三栏作品集 Demo 界面，直连 `/api/v1` 公共契约与 SSE v1 事件流：

- **Conversation**：提问、回答（逐条 claims + 引用芯片）、拒答（原因/停止原因）、失败与取消可观察。
- **Evidence**：证据卡（来源 kb/web/paper、内容范围 fulltext/abstract/snippet、文档页码/URL、原文摘录）；点引用芯片高亮对应证据。
- **Task Timeline**：SSE 事件实时流（meta → plan → tool_call → tool_result → source_status → evidence → token_delta → citation → done/error），含停止原因、预算与用量摘要；不展示模型隐私推理。

## 运行

```bash
cd frontend && npm install
npm run dev        # http://localhost:5173，/api 代理到 127.0.0.1:8000
npm run build      # vue-tsc 类型检查 + vite 构建（CI 门禁）
```

后端用生产方式启动（`uvicorn main:app`，缺云配置任务显式失败）；
前端联调冒烟可用 `python3 scripts/ui_smoke_server.py`（**FAKE 运行时**，仅测试，
其产出不是评测结论，见该脚本头部说明）。

## 行为约定

- 多会话不串流：切换任务即断开旧 SSE 流；重连由浏览器 EventSource 自动携带
  `Last-Event-ID` 续传（断线提示可见）。
- 回答结局与任务生命周期分开渲染：拒答是 completed 任务的正常结局（黄色卡），
  任务失败才进错误卡。
- 凭证不进 localStorage/GET/日志（P5 云配置面落地后此约束继续成立）。

## 状态

P5 第一版（三栏 Demo + 联调）已交付；云服务配置面板（provider/model/base_url/key、
来源与出站授权）随后落地。旧两套前端在替代功能验收后删除。

- [目标设计](../docs/design.md) · [P5 前置与验收](../docs/roadmap.md)
