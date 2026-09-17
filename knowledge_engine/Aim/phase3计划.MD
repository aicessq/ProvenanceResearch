# Phase 3 实施计划（文档解析与清洗）

> 本计划基于当前仓库 **Phase 0 已完成、Phase 1 已完成、Phase 2 将完成上传与异步任务入口** 的前提编写。
> 
> 本阶段目标是：在不越过规格边界的前提下，完成 **PDF / Markdown / TXT 解析、页码保留、基础文本清洗，以及解析失败时 ingest_task 状态回写**。

---

## 一、Phase 3 的目标

根据权威规格，Phase 3 的唯一目标是：

**从上传后的原始文件中提取结构化文本与页码，并对文本做基础清洗，为后续 Phase 4 的结构化切分打基础。**

这一阶段要解决的问题是：

- 如何从 PDF 中逐页抽取文本
- 如何从 Markdown / TXT 中得到可统一处理的文档结构
- 如何保留页码信息
- 如何清洗掉无意义噪声
- 如何在解析失败时把任务状态正确回写到数据库

但 Phase 3 仍然**不是**切分阶段，也不是索引阶段。
真正的 chunk 切分、chunk_hash、parent-child、embedding、Qdrant、FTS 都属于后续 Phase。

---

## 二、必须严格遵守的范围边界

### 2.1 本阶段必须完成

按照规格，Phase 3 必须完成：

1. 实现 PDF parser
2. 实现 Markdown parser
3. 实现 TXT parser
4. 保留页码
5. 实现基础文本清洗
6. 记录解析失败状态

### 2.2 本阶段不要提前实现

本阶段不要越界实现以下内容：

- 不要实现法规 / 标准 / 教材的结构化切分
- 不要实现 parent-child chunk
- 不要实现 chunk_hash
- 不要实现 `chapter / section / article_no` 的正式抽取逻辑
- 不要实现 embedding
- 不要实现 reranker
- 不要实现 Qdrant 写入
- 不要实现 PostgreSQL FTS 建索引
- 不要实现 query pipeline
- 不要实现 replace / chunk diff

### 2.3 关于“metadata 中保留页码”的理解

规格中的“chunk metadata 中能保留 `page_start/page_end`”，在 Phase 3 不应理解为必须已经有完整 chunk 持久化。

更合理的实现边界是：

- parser 输出的页级结构中已经带有 `page_number`
- cleaner 不破坏页码映射
- 后续 Phase 4 在切 chunk 时，能够把页码带进 chunk metadata

也就是说，Phase 3 的责任是**保住页码信息**，不是提前把 chunk 写出来。

---

## 三、当前仓库现状与 Phase 3 的前置条件

### 3.1 当前已具备的基础

当前仓库在进入 Phase 3 前，理论上应已具备：

- Phase 0：FastAPI / Docker / 基础设施 / 健康检查
- Phase 1：ORM 模型、Alembic、数据库基础
- Phase 2：上传接口、原始文件落盘、`document` / `document_version` / `ingest_task` 创建、Celery 任务入口

### 3.2 Phase 3 的关键依赖

本阶段实现应依赖：

- 已存在的 `document_versions.storage_path`
- 已存在的 `ingest_tasks` 状态更新能力
- 已存在的 Celery worker 任务入口

如果 Phase 2 还没有把文件上传与任务投递打通，那么 Phase 3 最终无法形成完整闭环。

---

## 四、Phase 3 的实施原则

### 4.1 parser 负责“提取”，cleaner 负责“整理”

职责要清晰分离：

- `parser_service.py`：负责把文件内容尽量原始、可靠地提取出来
- `cleaner_service.py`：负责统一换行、空白、页眉页脚清理、断行修复等基础整理

不要把清洗逻辑全塞进 parser 中，否则后续会很难调试和替换。

### 4.2 统一输出结构

即使来源文件不同，也应统一转成规格中定义的结构，例如：

- `ParsedPage`
- `ParsedDocument`

这样 Phase 4 的 chunk_service 就不需要关心输入文件原本是 PDF、Markdown 还是 TXT。

### 4.3 先保证稳定提取，再追求复杂格式还原

第一版 parser 重点应放在：

- 能稳定提取文本
- 能保留页码
- 能基本保留表格/代码块/段落边界

不要在 Phase 3 追求：

- 高质量 OCR
- 复杂版式还原
- 复杂图片理解
- DOCX / EPUB / HTML / PPTX 支持

### 4.4 解析失败必须进入任务状态链路

一旦解析失败，不能只打日志。
还必须：

- 更新 `ingest_task.status = failed`
- 写入 `error_message`
- 写入必要日志

否则上传链路对调用方就是“静默失败”。

---

## 五、建议的实现拆分

建议把 Phase 3 拆成 6 个步骤执行。

---

## 六、Step 1：定义统一解析数据结构

### 目标

让所有 parser 最终输出统一结构。

### 推荐文件

- `backend/app/services/parser_service.py`
- 如有需要，也可在 `backend/app/schemas/` 下放内部 schema，但不必强求对外暴露

### 建议结构

可按规格定义：

```python
class ParsedPage(BaseModel):
    page_number: int
    text: str
    tables: list[str] = []
    images: list[str] = []

class ParsedDocument(BaseModel):
    title: str
    pages: list[ParsedPage]
    metadata: dict = {}
```

### 设计要求

- 输出结构必须统一
- 即便 Markdown / TXT 没有天然页码，也要给出一致策略
- `metadata` 允许保留解析过程的补充信息

### 关于 Markdown / TXT 的页码策略

推荐做法：

- Markdown / TXT 在 Phase 3 统一视作单页文档
- `page_number = 1`

这样可以保持接口一致，也不会影响后续 chunk 逻辑。

---

## 七、Step 2：实现 PDF parser

### 目标

支持从 PDF 中逐页提取文本并保留页码。

### 推荐技术

根据规格，第一版可使用：

- `PyMuPDF`
- `pdfplumber`

### 推荐文件

- `backend/app/services/parser_service.py`

### 最低要求

1. 逐页解析 PDF
2. 每页保留 `page_number`
3. 每页提取 `text`
4. 能处理空页
5. 表格尽量转成 Markdown 文本（如果能稳定实现）
6. 解析异常时抛出明确错误

### 实现建议

推荐优先级：

- 先用一种库完成稳定文本提取主路径
- 如果需要，再用另一种库补强表格识别
- 第一版不要把 parser 设计得过度复杂

### 注意点

- 不要在 parser 阶段删除正文中可能有意义的编号
- 不要在 parser 阶段做过强的清洗
- 页眉页脚问题优先留给 cleaner 处理

---

## 八、Step 3：实现 Markdown / TXT parser

### 目标

支持文本类文档的统一解析。

### 推荐文件

- `backend/app/services/parser_service.py`

### Markdown parser 最低要求

1. 正确读取 UTF-8 内容
2. 保留原始换行和标题结构
3. 作为单页 `ParsedDocument` 输出

### TXT parser 最低要求

1. 正确读取文本
2. 尽量兼容常见编码（如 UTF-8，必要时可做有限 fallback）
3. 作为单页 `ParsedDocument` 输出

### 注意点

- Markdown 不需要在 Phase 3 转 HTML
- 不要在本阶段做标题层级结构化识别
- TXT 不需要复杂段落语义分析

---

## 九、Step 4：实现基础文本清洗

### 目标

对 parser 输出的文本做最低必要的标准化处理。

### 推荐文件

- `backend/app/services/cleaner_service.py`

### 按规格必须覆盖的规则

1. 统一换行
2. 去除多余空格
3. 去除重复页眉页脚
4. 修复 PDF 抽取导致的断行
5. 保留标题、条款号、编号
6. 保留代码块
7. 保留表格结构
8. 不得破坏法规条款编号、标准编号、CVE 编号和术语

### 推荐拆分函数

例如：

- `normalize_whitespace(text: str) -> str`
- `clean_page_text(text: str) -> str`
- `remove_repeated_headers_footers(pages: list[ParsedPage]) -> list[ParsedPage]`

### 清洗边界

本阶段 cleaner 应该是“保守清洗”：

- 去掉明显噪声
- 不改变语义
- 不做结构化切分
- 不抽取章节
- 不重写内容

### 最容易出错的地方

#### 1. 误删编号

像下面这些内容绝不能被清洗破坏：

- `第二十一条`
- `GB/T 22239`
- `CVE-2024-12345`
- `3.2.1`
- `1.` / `1.1` / `1.1.1`

#### 2. 误合并代码块或表格

教材类内容里可能有：

- shell 命令
- Python 代码
- 配置片段
- 表格

不要因为“去空白”就把它们压坏。

---

## 十、Step 5：把解析与清洗接入 worker

### 目标

让 Phase 2 的异步任务入口真正开始做“解析 + 清洗”。

### 推荐文件

- `backend/app/workers/ingest_worker.py`

### 本阶段 worker 应做的事情

建议主流程：

1. 读取 `document_id / version_id / task_id / file_path`
2. 将任务状态更新为 `processing`
3. 调用 parser 提取 `ParsedDocument`
4. 调用 cleaner 做清洗
5. 输出中间结果（当前可先不持久化 chunk）
6. 更新任务状态

### 关于“完成状态”的建议

这里有一个边界问题：

- Phase 3 只完成了解析和清洗
- 但完整入库还没到 chunk / embedding / index

因此建议不要把 `completed` 理解成“知识入库完成”，而是要看你在任务语义上如何定义。

更稳妥的方式有两种：

#### 策略 A：任务继续作为总入库任务，暂不在本阶段宣称完整完成
如果整个 ingest task 代表完整入库流程，那此阶段可以只做阶段内验证，不急于把生产语义完全固定。

#### 策略 B：临时占位完成，但在文档中明确说明仅代表解析阶段成功
如果当前实现为了便于验收需要把任务走通，也必须在 README / 实现文档中明确说明这只是阶段性完成。

无论哪种策略，**解析失败必须明确写成 `failed`**。

### 失败链路要求

出现以下情况时必须进入失败状态：

- 文件不存在
- 文件无法读取
- PDF 解析异常
- 文本解码异常且无法 fallback
- cleaner 发生不可恢复错误

失败时至少要做：

- `ingest_task.status = failed`
- `error_message = 结构化错误信息`
- 记录日志

---

## 十一、Step 6：测试与验收

### 目标

验证 Phase 3 的 parser / cleaner / worker 行为可用。

### 建议新增测试文件

- `backend/tests/test_parser.py`
- `backend/tests/test_cleaner.py`
- `backend/tests/test_ingest_worker.py`

### 至少要覆盖的测试

#### 1. PDF parser

- 能读取测试 PDF
- 能输出多页 `ParsedPage`
- 每页带 `page_number`
- 空页不会导致崩溃

#### 2. Markdown parser

- 能正确读取 `.md`
- 输出单页结果
- 标题与换行基本保留

#### 3. TXT parser

- 能正确读取 `.txt`
- 输出单页结果

#### 4. cleaner

- 能统一换行
- 能去掉多余空格
- 能识别重复页眉页脚并移除
- 不会破坏条款编号 / 标准编号 / CVE 编号

#### 5. worker

- 成功解析时能进入预期状态
- 解析失败时能把 `ingest_task` 标记为 `failed`
- `error_message` 有内容

### 测试数据建议

建议在测试目录下准备少量样例文件，例如：

- 一个 2~3 页的小 PDF
- 一个 Markdown 文档
- 一个 TXT 文档
- 一个故意损坏的 PDF 文件

样例要小、稳定、可重复运行。

### 验收命令建议

请优先在项目专用环境中运行 Python 相关命令，不要用全局 Python。

如果使用 conda：

```bash
conda run -n rag_sec_phase1 pytest backend/tests/test_parser.py
conda run -n rag_sec_phase1 pytest backend/tests/test_cleaner.py
conda run -n rag_sec_phase1 pytest backend/tests/test_ingest_worker.py -m integration
```

如果使用 venv：

```bash
.venv\Scripts\python -m pytest backend/tests/test_parser.py
.venv\Scripts\python -m pytest backend/tests/test_cleaner.py
.venv\Scripts\python -m pytest backend/tests/test_ingest_worker.py -m integration
```

### Phase 3 验收标准

必须达到：

- 上传 PDF 后能提取每页文本
- 后续 chunk metadata 所需的 `page_start/page_end` 基础页码信息已保留
- Markdown / TXT 能正常解析
- 解析失败时 `ingest_task.status = failed`

---

## 十二、推荐文件改动清单

以下是执行 Phase 3 时大概率会涉及的文件。

### 需要新增或完善的文件

- `backend/app/services/parser_service.py`
- `backend/app/services/cleaner_service.py`
- `backend/app/workers/ingest_worker.py`
- `backend/tests/test_parser.py`
- `backend/tests/test_cleaner.py`
- `backend/tests/test_ingest_worker.py`

### 可能需要调整的现有文件

- `backend/app/config.py`
- `backend/app/services/crud_service.py`
- `backend/app/models/ingest_task.py`
- `README.md`
- `pyproject.toml`

### 可能需要新增测试资源

例如：

- `backend/tests/fixtures/sample.pdf`
- `backend/tests/fixtures/sample.md`
- `backend/tests/fixtures/sample.txt`
- `backend/tests/fixtures/broken.pdf`

---

## 十三、建议的实现顺序

推荐顺序如下：

1. 定义统一解析输出结构
2. 实现 PDF parser
3. 实现 Markdown / TXT parser
4. 实现 cleaner
5. 将 parser + cleaner 接入 ingest worker
6. 准备测试样例文件
7. 编写 parser / cleaner / worker 测试
8. 更新 README 的 Phase 3 说明
9. 验收

---

## 十四、实现时最容易踩的坑

### 1. 过早进入 chunk 逻辑

Phase 3 的核心是“提取 + 清洗”，不是切分。
如果一开始就写 chunk 逻辑，很容易把 Phase 4 提前做掉。

### 2. parser 和 cleaner 职责混乱

如果 parser 同时做了大量清洗，后面会很难定位问题到底来自“提取错误”还是“清洗错误”。

### 3. Markdown / TXT 没有统一输出结构

如果不同文件类型返回格式不一致，后续 chunk_service 会变得很乱。

### 4. 为了清洗而破坏原文结构

尤其是：

- 条款号
- 标准编号
- CVE 编号
- 代码块
- 表格

这些一旦清坏，后面很难补救。

### 5. 解析失败没有回写任务状态

这会导致上传看似成功，但后台实际早已失败，用户无法感知。

### 6. 测试样例过大或不稳定

测试 PDF 应尽量小，避免：

- 运行太慢
- 依赖环境差异明显
- 结果不稳定

---

## 十五、建议给 Claude Code 的执行提示

如果后续要让 Claude Code 直接实现 Phase 3，提示词应强调：

- 当前仓库已完成 Phase 0 和 Phase 1，Phase 2 应已具备上传与异步入口
- 只实现 parser、cleaner、页码保留、失败状态回写
- 不要提前实现 chunk、embedding、索引、检索逻辑
- 所有新增代码保留完整中文注释
- Python 相关命令必须在项目专用 conda / venv 环境中运行
- 输出必须包含：修改文件、运行命令、测试命令、验收方法

---

## 十六、最终结论

Phase 3 的本质是：

**把“可上传文件的系统”，升级为“能把原始文件可靠转成可处理文本的系统”。**

完成本阶段后，系统将具备：

- 多文件类型的统一解析入口
- 可靠的页码保留能力
- 基础文本清洗能力
- 失败任务状态的明确反馈

这正是 Phase 4 进行结构化切分与 metadata 组织的前提。
