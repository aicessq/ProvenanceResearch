# Windows 本机运行记录（2026-10-26）

目录 `D:/Code_MyProject/ProvenanceResearch`，分支 dev。正式 P4 质量对照未运行。

## 当前入口

- 统一前端：http://127.0.0.1:5173/
- 后端文档：http://127.0.0.1:8000/docs
- 经前端代理的 `/api/v1/config`、`/api/v1/tasks` 均返回 200。
- PostgreSQL 5432、Redis 6379、Qdrant 6333：Docker healthy，均只发布至 127.0.0.1。

## 配置及限制

凭证保存在 Git 忽略的根 `.env`，没有写入源码。Agnes 使用 agnes-3.0-flash，百度 OCR 使用 general，视觉使用 qwen3-vl-plus，公开搜索为 Tavily/arXiv。按用户本次明确的运行要求登记配置指纹；供应商数据地域和留存政策尚未核实，不据此宣称隐私合规验收。

初次启动时 Embedding 未配置，reranker 关闭；当时知识引擎未启动。本日后续用户明确选择本地 BGE Embedding，下文记录该例外配置；OCR/Vision 完整入库集成仍未验收。

## 重启电脑后的运行方法

启动 Docker Desktop，在仓库根 PowerShell 执行：

```powershell
docker compose -f docker-compose.yml -f .env.run/compose.local.yml up -d postgres redis qdrant
```

后端在一个终端执行：

```powershell
.venv/Scripts/python.exe -X utf8 .env.run/backend.py
```

前端在另一个终端执行：

```powershell
cd frontend
npm.cmd run dev -- --host 127.0.0.1
```

本机忽略目录 `.env.run/` 中保存回环端口覆盖、加载根配置的真实后端启动脚本及日志，不随仓库分发。当前前后端在后台运行，避免重复启动。终端启动时使用 Ctrl+C 停止前后端；基础设施使用上述两个 compose 文件执行 `stop postgres redis qdrant`，保留数据卷。

## 验证结果

五项独立云合成检查成功：Agnes 返回 OK；百度 OCR、Qwen-VL 均转录 HELLO 2026；Tavily、arXiv 各返回一份证据。没有上传用户文档。

两个预算受限的真实 Agent 任务均完成生命周期，但没有通过正常作答验收。第一次搜索成功后，模型把摘要引用声明为全文，引用校验拒答；第二次规划格式校验未通过而拒答。没有放宽引用门禁或修改提示词掩盖结果。因此连接与运行环境已确认，回答质量和规划稳定性仍未验收。正式评测、金标准人工核验及完整 KE 集成仍待后续执行。

合成检查记录保存在本机忽略目录中的 cloud-smoke.json、smoke-task.json、smoke-events.txt、fulltext-task.json，不是正式质量评测报告。


## 本地 Embedding 例外配置（2026-10-26 后续）

用户明确选择 BAAI/bge-base-en-v1.5，revision a5beb1e3e68b9ab74eb54cfd186867f64f240e1a。模型目录为 knowledge_engine/models/bge-base-en-v1.5（忽略），向量为 768 维、归一化；独立 collection 为 bge_base_en_v15_768_a5beb1e3，不混用旧索引。运行时只读取本地文件，不执行模型仓库远程代码，不启用测试编码器。其他模型继续使用云端，reranker 保持关闭。

根配置已设置 EMBEDDING_PROVIDER=local、对应模型路径和维度，研究服务的 KB_INTERNAL_BASE_URL 指向 http://127.0.0.1:8001。本地 Embedding 无需云 API key，也不登记云出站许可；配置面显示“已配置”表示配置存在，实际加载结果需另行验证。

知识库本机启动脚本位于忽略目录 .env.run/knowledge.py，支持 migrate（现有 Alembic 迁移）、api（回环端口 8001）、worker（Windows solo 进程）和 embedding-smoke（真实本地向量检查）。使用根 .venv 执行，API 与 Worker 为两个独立进程，共用根环境和存储目录。

知识库启动和全量测试曾被 app/services/safety_guard.py 读取时反复消失阻断。用户处理本机安全软件后，按 HEAD 恢复原文件，KE 全量单元测试通过（100 passed / 34 deselected），文件本身与业务安全逻辑没有修改。独立 Embedding 验证与完整知识库验收分别记录，不将配置存在当作全链路通过。

本地向量真实冒烟已通过：三个输入均生成 768 维有限值向量；相关文本余弦相似度约 0.902，无关文本约 0.301。该小样例只证明真实模型正常推理，不代表正式召回质量评测。API 就绪检查中 PostgreSQL、Redis、Qdrant、一个已注册所需任务的 Worker 均正常。记录位于忽略的 .env.run/local-embedding-model.json 和 local-embedding-smoke.json。
