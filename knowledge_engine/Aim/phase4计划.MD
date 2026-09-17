# Phase 4 实施计划（结构化切分）

> 本计划基于当前仓库 **Phase 0 已完成、Phase 1 已完成、Phase 2 将完成上传与任务入口、Phase 3 将完成解析与清洗** 的前提编写。
> 
> 本阶段目标是：在不越过规格边界的前提下，完成 **法规/标准切分、教材切分、fallback recursive chunker、parent-child chunk、chunk_hash 生成以及基础 metadata 组织**。

---

## 一、Phase 4 的目标

根据权威规格，Phase 4 的唯一目标是：

**把经过解析与清洗的文档文本，转换为后续可检索、可引用、可增量更新的 chunk 结构。**

这一阶段要解决的问题是：

- 如何对法规 / 标准文本按章、节、条切分
- 如何对教材 / 手册 / 笔记按章节与语义段落切分
- 如何在结构不明确时使用 fallback recursive chunker
- 如何建立 parent-child chunk 关系
- 如何为每个 chunk 生成稳定的 `chunk_hash`
- 如何保留 `chapter / section / article_no / page_start / page_end` 等 metadata

但 Phase 4 仍然**不是**索引阶段，也不是检索阶段。
Qdrant、FTS、embedding、reranker、RRF、query API 都属于后续 Phase。

---

## 二、必须严格遵守的范围边界

### 2.1 本阶段必须完成

按照规格，Phase 4 必须完成：

1. 实现 law / standard chunker
2. 实现 textbook chunker
3. 实现 fallback recursive chunker
4. 实现 parent-child chunk
5. 保存 `chunk_hash`
6. 保存 `chapter / section / article_no / page`

### 2.2 本阶段不要提前实现

本阶段不要越界实现以下内容：

- 不要实现 embedding 向量生成
- 不要实现 reranker
- 不要实现 Qdrant upsert
- 不要实现 PostgreSQL FTS 建索引逻辑
- 不要实现 query pipeline
- 不要实现 answer generation
- 不要实现 replace / chunk diff 更新逻辑
- 不要实现最终检索排序与召回策略

### 2.3 关于“保存 chunk”的边界

Phase 4 的“保存 chunk”更合理的理解应是：

- worker 在解析与清洗后，完成 chunk 生成
- 将 chunk 记录落入 PostgreSQL `chunks` 表
- 但**只到数据库持久化为止**
- 不进入向量库，不进入关键词索引

也就是说，Phase 4 结束时，系统应已经具备“数据库中的 chunk 基础数据”，但还没有检索能力。

---

## 三、当前仓库现状与 Phase 4 的前置条件

### 3.1 当前已具备的基础

进入 Phase 4 前，理论上应已具备：

- Phase 0：基础工程、健康检查、Docker 与基础设施联通
- Phase 1：ORM 模型、Alembic、核心表与基础 CRUD
- Phase 2：上传接口、文件落盘、`document / version / ingest_task` 创建、Celery 入口
- Phase 3：PDF / Markdown / TXT parser、cleaner、失败状态回写

### 3.2 Phase 4 的关键依赖

本阶段实现依赖以下已有能力：

- `ParsedDocument / ParsedPage` 统一输出结构
- 清洗后的文档文本
- `document_versions` 与 `chunks` 表已可写
- `ingest_task` 状态可更新
- `hash_utils.py` 中至少具备基础 hash 支持，或在本阶段补齐文本 hash 能力

如果 Phase 3 还没把解析与清洗稳定下来，不建议直接进入 Phase 4。
因为切分质量高度依赖前面文本质量。

---

## 四、Phase 4 的实施原则

### 4.1 先保证“可解释的结构化切分”，再追求复杂语义切分

这一阶段重点不是花哨，而是：

- 切分规则清晰
- metadata 来源可解释
- 后续可调试
- `chunk_hash` 稳定

### 4.2 law / standard 与 textbook 必须分开策略

法规、标准和教材的文本结构完全不同，不能用一个通用切分器硬套。

- `law / regulation / standard / policy`：以章、节、条为主
- `textbook / manual / note`：以章、节、小节、语义段落为主

### 4.3 child chunk 是未来唯一索引单元

虽然索引在 Phase 5 才实现，但 Phase 4 必须从现在开始遵守：

- child chunk：未来用于检索
- parent chunk：未来用于上下文回填
- parent 不应被当作未来索引主单元

### 4.4 chunk_hash 必须稳定

后续 Phase 9 的增量更新依赖 `chunk_hash`。
因此本阶段设计时就必须保证：

- hash 基于 `normalized_text`
- 对无意义空白的变化不敏感
- 对编号、术语、标点等关键内容敏感
- 相同内容在重复处理时能生成相同 hash

---

## 五、建议的实现拆分

建议把 Phase 4 拆成 7 个步骤执行。

---

## 六、Step 1：定义统一 Chunk 数据结构

### 目标

让所有 chunker 的输出统一，便于后续落库和测试。

### 推荐文件

- `backend/app/services/chunk_service.py`

### 建议结构

可按规格定义：

```python
class Chunk(BaseModel):
    text: str
    chunk_type: str
    chunk_index: int
    parent_chunk_id: str | None = None
    page_start: int | None = None
    page_end: int | None = None
    chapter: str | None = None
    section: str | None = None
    article_no: str | None = None
    keywords: list[str] = []
    metadata: dict = {}
```

### 设计要求

- 输出必须能表达 parent / child
- 必须包含页码区间字段
- 必须能承载章节与条款信息
- `metadata` 允许保留扩展字段，但第一版不要塞入复杂多层结构

---

## 七、Step 2：实现法规 / 标准切分器

### 目标

支持 `law / regulation / standard / policy` 类型文档的结构化切分。

### 切分规则

按规格必须遵守：

- 一级：按章切
- 二级：按节切
- 三级：按条切
- 单条超过 **800 tokens** 时，再按自然段拆 child chunk
- 条款编号必须保留在每个子 chunk 中
- 保留页码范围
- 保留章节路径

### 推荐识别模式

至少支持识别：

- `第[一二三四五六七八九十百]+章`
- `第[一二三四五六七八九十百]+节`
- `第[一二三四五六七八九十百]+条`
- `1.` / `1.1` / `1.1.1`
- 其他常见标准编号段落模式

### 设计要求

- 如果识别到明确条款，优先以条款为边界
- 条款很长时，child chunk 切分后仍需保留 `article_no`
- 若正文中同时存在章、节、条，则 metadata 应尽量完整继承

### 注意点

- 不要把“条款编号”从 child chunk 文本中清掉
- 不要只按固定字数切，忽略法律文本结构
- 遇到识别不清的情况，可降级但不能胡乱编造 `article_no`

---

## 八、Step 3：实现教材 / 手册 / 笔记切分器

### 目标

支持 `textbook / manual / note` 类型文档的结构化与语义化切分。

### 切分规则

按规格建议：

- 一级：按章
- 二级：按节
- 三级：按小节
- 四级：按语义段落
- 如果没有明显标题结构，则使用 recursive fallback
- 代码块必须整体保留
- 表格必须整体保留
- child chunk 建议 300-600 tokens
- parent chunk 建议 1000-2000 tokens
- child overlap 建议 80 tokens

### 设计要求

- 对 Markdown 标题可适度利用其天然层级
- 对教材 PDF，则更多依赖标题模式与段落边界
- 代码块、命令块、表格优先视作不可随意拆开的结构单元

### 注意点

- 不要因为追求 token 长度一致而破坏代码块
- 不要强行抽取法律式 `article_no`
- 若章节识别不到，可允许 `chapter / section = null`

---

## 九、Step 4：实现 fallback recursive chunker

### 目标

在结构识别不足时，仍能稳定输出可用 chunk。

### 适用场景

- PDF 文本结构混乱
- TXT 没有标题层次
- Markdown 标题缺失或不规范
- 章节识别失败

### 设计要求

- 优先按自然段 / 空行边界切
- 再按 token 长度做递归拆分
- 尽量避免在句中粗暴截断
- 尽量保留文本局部连续性

### 推荐策略

可以采用类似“优先级切分分隔符”的思路：

1. 双换行
2. 单换行
3. 句号/分号等句界
4. 空格
5. 最后才做硬切

### 注意点

fallback 只是兜底，不应成为主路径。
如果主文档类型本该能按结构切，就优先使用专用 chunker。

---

## 十、Step 5：实现 parent-child chunk 关系

### 目标

形成后续检索与答案生成依赖的两层 chunk 结构。

### 按规格必须遵守

- child chunk：未来用于检索，300-600 tokens
- parent chunk：未来用于答案生成，1000-2000 tokens
- child 保存 `parent_chunk_id`
- parent 不进入未来向量检索主路径

### 推荐做法

1. 先生成较大语义单元作为 parent
2. 再在 parent 内切出多个 child
3. 每个 child 都带 `parent_chunk_id`
4. parent 与 child 的页码范围应可追溯

### 设计要求

- parent 内容应尽量覆盖 child 的上文下文
- child 命中后能自然回取 parent 作为上下文
- 若某个 child 找不到合适 parent，可允许 fallback，但不应成为主路径

### 注意点

- 不要让 parent 和 child 完全一样而失去分层意义
- 不要把 parent 设计得过大，影响后续答案上下文效率

---

## 十一、Step 6：实现 chunk_hash 与 metadata 组织

### 目标

让 chunk 可持久化、可追踪、可增量更新。

### 推荐文件

- `backend/app/utils/hash_utils.py`
- `backend/app/services/chunk_service.py`

### 必须覆盖的内容

1. 基于 `normalized_text` 生成 `chunk_hash`
2. 生成并组织以下 metadata：
   - `doc_id`
   - `version_id`
   - `chunk_id`
   - `doc_type`
   - `doc_title`
   - `chapter`
   - `section`
   - `article_no`
   - `page_start`
   - `page_end`
   - `file_hash`
   - `chunk_hash`
   - `chunk_type`
   - `parent_chunk_id`

### 重要边界

- 如果 `chapter / section / article_no` 无法识别，必须为 `null`
- 不允许伪造条款号
- `normalized_text` 可以清理无意义空白，但不能破坏语义信息

### 持久化建议

在本阶段可将 chunk 记录写入 `chunks` 表，包括：

- parent chunk
- child chunk
- `normalized_text`
- `chunk_hash`
- metadata 相关字段

但不要在本阶段写入 Qdrant 或 FTS。

---

## 十二、Step 7：接入 worker、测试与验收

### 目标

把解析 → 清洗 → 切分 → chunk 落库链路闭环打通。

### 推荐文件

- `backend/app/workers/ingest_worker.py`
- `backend/tests/test_chunk_service.py`
- `backend/tests/test_ingest_worker.py`

### worker 在本阶段应做的事情

建议主流程：

1. 读取上传生成的 `document_id / version_id / task_id / file_path`
2. 更新任务状态为 `processing`
3. 调用 parser
4. 调用 cleaner
5. 调用 chunk_service 生成 parent / child chunks
6. 将 chunks 写入 PostgreSQL
7. 根据当前阶段策略更新任务状态

### 关于任务状态的建议

如果当前 ingest task 被定义为“完整入库链路”，那么严格来说到 Phase 4 也还未完成全部索引工作。

但从阶段实现角度看，如果你为了阶段验收让任务走到 `completed`，必须在实现文档中明确说明：

- 当前 `completed` 仅表示“已完成解析、清洗、切分与 chunk 落库”
- 向量索引与关键词索引将在 Phase 5 再补齐

### 至少要补的测试

#### 1. chunk_service 测试

建议覆盖：

- 法规文档按条款切分
- 长条款 > 800 tokens 时继续拆 child chunk
- 教材文档按章节 / 小节切分
- fallback recursive chunker 可工作
- parent-child 关系正确
- 每个 chunk 都有 hash
- metadata 含页码与章节信息

#### 2. worker 集成测试

建议覆盖：

- 上传后的文档能生成 chunks
- chunks 能写入 PostgreSQL
- 解析/切分失败能正确回写任务状态

### 测试样例建议

建议准备：

- 小型法规 PDF
- 小型标准 PDF
- 小型教材 PDF 或 Markdown
- 无明显结构的 TXT
- 一个长条款样例
- 一个包含代码块与表格的教材样例

### 验收命令建议

请优先在项目专用环境中运行 Python 相关命令。

如果使用 conda：

```bash
conda run -n rag_sec_phase1 pytest backend/tests/test_chunk_service.py
conda run -n rag_sec_phase1 pytest backend/tests/test_ingest_worker.py -m integration
```

如果使用 venv：

```bash
.venv\Scripts\python -m pytest backend/tests/test_chunk_service.py
.venv\Scripts\python -m pytest backend/tests/test_ingest_worker.py -m integration
```

### Phase 4 验收标准

必须达到：

- 法规文档能按条款切分
- 长条款超过 800 tokens 时可继续拆 child chunk
- 教材能按章节 / 小节切分
- 每个 chunk 有 hash
- 每个 chunk 有 metadata
- parent-child 关系正确

---

## 十三、推荐文件改动清单

以下是执行 Phase 4 时大概率会涉及的文件。

### 需要新增或完善的文件

- `backend/app/services/chunk_service.py`
- `backend/app/utils/hash_utils.py`
- `backend/app/workers/ingest_worker.py`
- `backend/tests/test_chunk_service.py`
- `backend/tests/test_ingest_worker.py`

### 可能需要调整的现有文件

- `backend/app/services/parser_service.py`
- `backend/app/services/cleaner_service.py`
- `backend/app/services/crud_service.py`
- `backend/app/models/chunk.py`
- `README.md`
- `pyproject.toml`

### 可能需要新增测试资源

例如：

- `backend/tests/fixtures/law_sample.pdf`
- `backend/tests/fixtures/standard_sample.pdf`
- `backend/tests/fixtures/textbook_sample.md`
- `backend/tests/fixtures/plain_note.txt`

---

## 十四、建议的实现顺序

推荐顺序如下：

1. 定义 Chunk 数据结构
2. 实现法规 / 标准 chunker
3. 实现教材 chunker
4. 实现 fallback recursive chunker
5. 实现 parent-child 关系生成
6. 实现 `chunk_hash` 与 metadata 组织
7. 接入 worker 并写入 PostgreSQL
8. 准备测试样例
9. 编写 chunk / worker 测试
10. 更新 README 的 Phase 4 说明
11. 验收

---

## 十五、实现时最容易踩的坑

### 1. 过早把索引逻辑塞进来

Phase 4 只负责“把文本变成 chunk 并落库”。
一旦提前引入 embedding、Qdrant 或 FTS，就越界了。

### 2. 结构化切分规则不透明

如果 chunk 规则太隐式，后面调试时很难解释为什么某段文本被这样切开。
因此建议优先使用明确规则，而不是过早引入复杂黑盒分块策略。

### 3. 条款编号在 child chunk 中丢失

这是法律 / 标准文档里非常致命的问题。
一旦拆分后丢掉 `article_no`，后续引用会严重受影响。

### 4. chunk_hash 不稳定

如果 hash 对空白、换行、格式化过于敏感，后续 Phase 9 的 chunk diff 会产生大量伪变化。

### 5. parent 和 child 设计失衡

- parent 太小：失去上下文回填意义
- parent 太大：后续回答上下文过重
- child 太大：召回粒度差
- child 太小：语义碎片化严重

### 6. 把无法识别的章节信息硬填进去

如果识别不到 `chapter / section / article_no`，就应该是 `null`，不能猜。

---

## 十六、建议给 Claude Code 的执行提示

如果后续要让 Claude Code 直接实现 Phase 4，提示词应强调：

- 当前仓库已完成 Phase 0、Phase 1，且 Phase 2/3 已具备上传、解析与清洗基础
- 只实现结构化切分、parent-child、chunk_hash、metadata 与 chunk 落库
- 不要提前实现 embedding、Qdrant、FTS、检索逻辑
- 条款号必须保留，无法识别时返回 `null`
- 所有新增代码保留完整中文注释
- Python 相关命令必须在项目专用 conda / venv 环境中运行
- 输出必须包含：修改文件、运行命令、测试命令、验收方法

---

## 十七、最终结论

Phase 4 的本质是：

**把“可解析的文档文本”，升级为“可被后续检索系统索引和引用的结构化 chunk 数据”。**

完成本阶段后，系统将具备：

- 面向法规 / 标准 / 教材的差异化切分能力
- parent-child 两层 chunk 结构
- 稳定的 `chunk_hash`
- 可追溯的章节、条款、页码 metadata
- `chunks` 表中的基础数据沉淀

这正是 Phase 5 进入 embedding、索引与检索基础设施接入的前提。
