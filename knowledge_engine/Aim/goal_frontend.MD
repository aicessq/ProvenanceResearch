# goal_frontend.MD

目标：为当前项目 `D:\Code_MyProject\RAG_Sec` 生成一个**完整可运行的前端工程**，供 Claude Code 按此指令直接实施。

---

## 1. 项目背景

当前仓库是一个网络安全领域 RAG 知识库后端项目。

现状：

- 后端技术栈：FastAPI + PostgreSQL + Redis + Qdrant + Celery
- 当前后端已经可以启动，健康检查接口可用：
  - `GET /health`
  - `GET /api/v1/health`
  - `GET /api/v1/health/ready`
- 当前仓库**没有独立前端工程**
- 当前最直观的接口入口只有 Swagger：`http://localhost:8000/docs`

目标是补齐一个前端，使项目从“只有后端 API”升级为“有可操作页面的完整系统原型”。

---

## 2. Claude Code 的工作目标

请你在当前仓库中创建一个**独立前端工程**，并与现有后端 API 对接，形成一个最小但完整的前端可用版本。

前端工程要求：

1. 必须是独立前端目录，不要把前端代码混进 `backend/`
2. 优先选择现代主流方案，推荐：
   - React
   - TypeScript
   - Vite
3. UI 可以使用简洁组件方案，但不要过度复杂
4. 页面应能本地运行并连接当前 FastAPI 后端
5. 所有实现以“可运行、可演示、可继续扩展”为优先

---

## 3. 前端功能范围（MVP）

请实现一个**面向当前后端能力的最小前端 MVP**，至少包含以下页面或模块。

### 3.1 系统首页 / 仪表盘

展示：

- 项目名称
- 后端连接状态
- PostgreSQL / Redis / Qdrant 就绪状态
- 到主要功能页面的导航入口

后端状态来源：

- `GET /health`
- `GET /api/v1/health/ready`

### 3.2 文档上传页面

提供一个上传页面，支持：

- 选择文件上传
- 输入标题 `title`
- 输入文档类型 `doc_type`
- 可选填写 `security_domain`
- 可选填写 `tags`
- 可选填写 `publish_date`
- 可选填写 `effective_date`
- 可选填写 `version_status`

要求：

- 使用表单提交到后端上传接口
- 成功后展示返回的 `document_id` / `version_id` / `task_id`
- 失败时展示后端错误信息

说明：

如果后端上传接口当前未在 docs 中暴露，前端仍按后端代码中的既定接口路径设计，后续只需等待后端修复。

### 3.3 检索调试页面

提供一个页面，对接检索接口，支持：

- 输入 query
- 设置 top_k
- 可选 debug 开关
- 展示返回的 chunk 列表
- 每条结果展示：
  - chunk_id
  - doc_title
  - doc_type
  - score
  - page_start / page_end
  - chunk_text

### 3.4 Query Rewrite 调试页面

提供一个页面，对接 rewrite 接口，展示：

- 原始 query
- safety 判断结果
- intent 分类结果
- expanded_terms
- rewritten_query
- search_keywords
- sub_queries
- filters

### 3.5 问答页面

提供一个问答页面，对接 answer 接口，支持：

- 输入问题
- 提交后展示 answer
- 展示 citations
- 展示 confidence
- 展示 evidence_status
- 如果返回 blocked / refuse / redirect，也要做清晰展示

### 3.6 Eval 页面

提供一个简单页面，对接 eval run 接口，支持：

- 输入或选择 dataset_name
- 触发 eval
- 展示：
  - run_id
  - total_count
  - recall_at_k
  - mrr
  - citation_accuracy
  - refusal_accuracy
  - average_latency_ms
  - status

---

## 4. 前端工程结构要求

请按独立前端项目组织，建议类似：

```text
frontend/
  src/
    api/
    components/
    pages/
    hooks/
    types/
    utils/
    App.tsx
    main.tsx
  public/
  package.json
  vite.config.ts
  tsconfig.json
```

要求：

- API 请求统一封装，不要把 fetch/axios 散落在页面里
- 页面与组件分层清晰
- 类型定义尽量基于后端返回结构
- 不要过度设计状态管理；若无必要，不要上复杂全局状态库

---

## 5. 与后端联调要求

Claude Code 在生成前端时，请默认后端地址可配置，例如：

- `VITE_API_BASE_URL=http://localhost:8000`

前端请求路径需兼容以下风格：

- `/health`
- `/api/v1/health`
- `/api/v1/health/ready`
- `/api/v1/documents/upload`
- `/api/v1/query/retrieve`
- `/api/v1/query/rewrite`
- `/api/v1/query/answer`
- `/api/v1/eval/run`
- `/api/v1/documents/{document_id}/replace`
- `DELETE /api/v1/documents/{document_id}`

即使当前后端 docs 暂未完整暴露，也不要因此放弃前端结构设计。

---

## 6. UI / UX 要求

请做成“工程演示可用”的风格，而不是只堆表单：

1. 页面布局清晰
2. 有左侧导航或顶部导航
3. 状态提示明确
4. 加载中、成功、失败三态要有
5. 返回 JSON 时要适度结构化展示，不要原始一坨文本
6. 风格偏简洁、专业、工程化
7. 不要使用占位图片

---

## 7. Claude Code 的执行要求

请按以下顺序执行：

1. 先创建前端工程
2. 安装依赖
3. 建立基础布局与路由
4. 封装 API 客户端
5. 实现各页面
6. 配置本地开发启动方式
7. 尽可能本地运行验证
8. 输出最终说明：
   - 新增了哪些文件
   - 如何启动前端
   - 前端连接哪个后端地址
   - 当前哪些功能已可演示
   - 如果某些后端接口未真正暴露，前端是如何预留对接的

---

## 8. 重要约束

1. 不要改乱现有 `backend/` 目录结构
2. 不要把前端代码塞到后端目录里
3. 优先新增 `frontend/` 目录
4. 保持实现简洁，不要过度抽象
5. 以前端 MVP 可运行演示为第一目标
6. 如果需要新增文档，只写最必要的启动说明

---

## 9. 希望 Claude Code 最终交付的结果

至少应交付：

- 一个可运行的前端工程
- 能本地启动的命令
- 至少 5 个页面/模块：
  - Dashboard
  - Upload
  - Retrieve
  - Rewrite
  - Answer
  - Eval（可与其他页合并，但功能必须存在）
- 与当前 FastAPI API 的基础对接能力

---

## 10. 给 Claude Code 的一句话任务描述

请为当前 `RAG_Sec` 仓库创建一个独立的 React + TypeScript + Vite 前端工程，提供 Dashboard、文档上传、检索调试、Rewrite 调试、问答、Eval 等页面，并与现有 FastAPI 后端 API 对接，做到本地可运行、可演示、可继续扩展。
