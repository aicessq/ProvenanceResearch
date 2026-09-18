# eval/corpus 语料许可与获取说明（草案，待用户逐条确认）

> 本文件按任务要求逐篇记录许可依据与获取方式。凡标"待确认"的条目，未经用户确认不得视为定稿。
> 访问日期统一为 2026-09-18（见各 manifest 条目 `retrieved_at`）。sha256 以 `manifest.jsonl` 为准。

## 汇总

| 类别 | 篇数 | 入库（提交 PDF/文本镜像） | 仅 manifest | 许可依据 |
| --- | --- | --- | --- | --- |
| 中国法律法规（cn_law） | 16 | 16 | 0 | 《著作权法》第五条：法律、法规……不适用著作权保护 |
| 美国政府出版物（us_gov，NIST） | 2 | 2 | 0 | 美国政府作品，公共领域（17 U.S.C. §105） |
| IETF RFC（ietf_rfc） | 3 | 3 | 0 | IETF Trust 版权条款，允许自由分发 |
| arXiv 论文（arxiv） | 7 | 0 | 7 | 元数据未声明具体 license，按不可再分发处理 |
| 国家标准（GB/T） | 0 | — | — | 未收录，待用户决定（见"待确认"） |

## 一、中国法律法规（16 篇，来源：国家法律法规数据库 flk.npc.gov.cn）

**许可结论：可再分发、入库。** 依据《中华人民共和国著作权法》（2020 修正）第五条：
"本法不适用于：（一）法律、法规，国家机关的决议、决定、命令和其他具有立法、行政、司法性质的文件，及其官方正式译文；"
即法律、行政法规的官方文本不受著作权保护，可自由复制与再分发。

**获取方式**：flk.npc.gov.cn 官方数据库。下载链路（`download_corpus.py` 已实现）：
`manifest.source_url`（`https://flk.npc.gov.cn/detail?id=<bbbs>...`）→
`GET /law-search/download/pc?format=pdf&bbbs=<id>&fileId=` 返回 1 小时有效的预签名地址（flkoss.obs-bj2.cucloud.cn）→
GET 该地址得到 PDF。预签名地址每次不同，因此**稳定引用是 manifest 里的 source_url 与 sha256，而不是直链**。

逐篇明细（doc_id / 文件 / 备注）：

- `zh_cybersec_2016`（网络安全法 2016 公布版）：**扫描件，无文本层**，OCR 路线未建，暂只作版本对照锚点与原资产。
- `zh_cybersec_2025`（网络安全法 2025 修正版）：文本型 PDF。
- `zh_cybersec_amend_2025`（关于修改《网络安全法》的决定）：文本型 PDF。
- `zh_datasec_2021` / `zh_persinfo_2021` / `zh_crypto_2019` / `zh_esign_2019` / `zh_minor_2024` /
  `zh_antimon_2022` / `zh_puborder_2025` / `zh_admin_penalty_2021` / `zh_copyr_2020`：文本型 PDF，现行有效版。
- `zh_esign_2015` / `zh_antimon_2007` / `zh_puborder_2012` / `zh_ecom_2018`：**扫描件，无文本层**（历史版本多为公报扫描件）。

**页级文本镜像**（`text/zh_*.pages.jsonl`）为上述 PDF 的逐页纯文本提取，是官方文本的机械变换，同样可再分发。

## 二、NIST 出版物（2 篇，来源：nvlpubs.nist.gov）

**许可结论：可再分发、入库。** NIST 出版物由美国国家标准技术研究院（联邦机构）雇员完成，属美国政府作品，
依 17 U.S.C. §105 不受美国版权保护（NIST 官方声明亦明确其出版物属 public domain）。

- `us_nist_sp800_207`：NIST Special Publication 800-207, *Zero Trust Architecture*（2020-08）。
- `us_nist_ai100_1`：NIST AI 100-1, *Artificial Intelligence Risk Management Framework (AI RMF 1.0)*（2023-01）。

## 三、IETF RFC（3 篇，来源：rfc-editor.org）

**许可结论：可再分发、入库。** RFC 文本由 IETF Trust 按文档内版权声明发布（5378 之后版本为 BSD 风格许可，
明确授予复制与分发权，条件是保留版权与免责声明；RFC 8446/6749/7519 均适用）。

- `rfc_8446`（TLS 1.3）、`rfc_6749`（OAuth 2.0）、`rfc_7519`（JWT）。
- **格式说明（决策记录）**：rfc-editor.org 已不再提供 `rfcXXXX.pdf` 直链（404），datatracker 的 PDF 需登录。
  故按 **RFC 规范格式 `.txt`** 收录——该格式自带换页符分页与 `[Page N]` 页码，页级镜像按换页符切页，页码忠实保留。

## 四、arXiv 论文（7 篇，来源：arxiv.org）

**许可结论：不再分发、不入库（仅 manifest + 本地缓存）。**
经 arXiv API 查询，7 篇论文的元数据均**未声明具体 license**（默认适用 arXiv 非独占分发许可，不等于再分发授权）。
按任务纪律"许可不明不猜测"处理：PDF 与页级镜像只留在本地（已 gitignore），仓库只提交 manifest
（含 arXiv ID、版本、sha256、来源 URL），任何人可用 `download_corpus.py` 重新获取。

- `ax_2005.11401`（RAG, Lewis et al.）v1
- `ax_2304.09848v1` / `ax_2304.09848v2`（Evaluating Verifiability, v1/v2 版本对照对）
- `ax_2307.03172`（Lost in the Middle）v3
- `ax_2310.11511`（Self-RAG）v1
- `ax_2202.03629`（Hallucination Survey）v7
- `ax_2312.10997`（RAG Survey, Gao et al.）v1

注意：`zh_cybersec_2016` 等扫描件 PDF 为官方公报扫描图像，其页级镜像（OCR 产物）若日后生成，
OCR 输出同样属于官方文本的机械变换，可再分发。

## 待用户确认事项

1. 5 篇扫描件（`zh_cybersec_2016`、`zh_esign_2015`、`zh_antimon_2007`、`zh_puborder_2012`、`zh_ecom_2018`）
   的去留：保留待 P3 OCR / 剔除 / 换源。当前按"保留 + 标记"处理，未擅自剔除。
   另注：`knowledge_engine/Data/网络安全法.pdf`（用户既有文件）为 2016 版文本型 PDF（23 页），
   但来源 URL 不明、不可复现下载，故未纳入语料，仅在此记录为可选替代。
2. GB/T 国家标准是否收录（0–2 篇，仅 manifest）。标准全文需经"标准全文公开系统"（openstd.samr.gov.cn）
   在线预览或购买，自动抓取的合法性不确定，按"许可不明不猜测"原则本轮未收录。
3. flk 未提供 PDF（仅 Word/OFD）而未收录的行政法规：《关键信息基础设施安全保护条例》《网络数据安全管理条例》
   《商用密码管理条例（2023 现行版）》——是否需要换源（gov.cn HTML/公报）由用户决定。
4. RFC 以 .txt 规范格式入库的决策是否认可（PDF 已不可公开直链获取）。
