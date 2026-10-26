# Windows 本机运行记录（2026-10-26）

目录 `D:/Code_MyProject/ProvenanceResearch`，分支 dev。正式 P4 质量对照未运行。

## 当前入口

- 统一前端：http://127.0.0.1:5173/
- 后端文档：http://127.0.0.1:8000/docs
- 经前端代理的 `/api/v1/config`、`/api/v1/tasks` 均返回 200。
- PostgreSQL 5432、Redis 6379、Qdrant 6333：Docker healthy，均只发布至 127.0.0.1。

## 配置及限制

凭证保存在 Git 忽略的根 `.env`，没有写入源码。Agnes 使用 agnes-3.0-flash，百度 OCR 使用 general，视觉使用 qwen3-vl-plus，公开搜索为 Tavily/arXiv。按用户本次明确的运行要求登记配置指纹；供应商数据地域和留存政策尚未核实，不据此宣称隐私合规验收。

Embedding 未配置，reranker 关闭。历史知识引擎 Worker 未启动，完整上传、OCR/Vision 入库、私库向量检索尚未验收，没有下载或加载本地模型。当前研究请使用公开搜索来源。

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
