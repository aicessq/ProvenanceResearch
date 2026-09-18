# eval/corpus/ —— 评测语料（P4 前置交付物）

固定评测语料：28 篇文档（16 篇中国法律法规 + 2 篇 NIST + 3 篇 RFC + 7 篇 arXiv 论文）。
逐篇元数据见 `manifest.jsonl`；许可与获取说明见 `LICENSES.md`（草案，待用户确认）。

## 目录

```
manifest.jsonl        # 每行一篇：doc_id/title/lang/category/source_url/retrieved_at/
                      #   filename/pages/sha256/redistributable/license_note/in_repo/
                      #   text_layer_ok/blank_page_ratio/notes
download_corpus.py    # 幂等下载 + sha256 校验（--record 为构建期回写哈希）
extract_text.py       # 页级文本镜像提取 + 文本层统计（需 PyMuPDF）
pdf/                  # 原资产（arxiv/ 子目录被 gitignore，仅本地缓存）
text/<doc_id>.pages.jsonl   # 页级镜像：{"doc_id","page","text","char_count"}，页码从 1 起
```

## 从零重建（可复现命令）

```bash
cd eval/corpus
rm -rf pdf/                     # 模拟从零开始
python3 download_corpus.py      # 重新下载全部 28 篇并逐篇核对 sha256（arXiv 自动节流 ≥3s）
knowledge_engine/.venv/bin/python extract_text.py   # 重建页级镜像与统计
cd ../questions && python3 validate_questions.py    # 题目校验（逐字命中页文本）
```

说明：
- flk 来源走 `source_url` 里的 `id`（bbbs）参数经官方 API 换取 1 小时有效的预签名地址下载，
  预签名地址每次不同，稳定引用是 manifest 里的 `source_url + sha256`；
- rfc-editor.org 已不提供 PDF，RFC 按规范格式 `.txt` 收录，`extract_text.py` 按换页符分页；
- `text_layer_ok=false` 的 5 篇为官方公报扫描件（见 LICENSES.md），OCR 属 P3 云路线，未建。

## 已知问题（待用户裁决）

1. 5 篇扫描件无文本层：`zh_cybersec_2016`、`zh_esign_2015`、`zh_ecom_2018`、
   `zh_antimon_2007`、`zh_puborder_2012`——保留 + 标记，未擅自剔除；
2. flk 无 PDF（仅 Word/OFD）而未收录：《关键信息基础设施安全保护条例》《网络数据安全管理条例》
   《商用密码管理条例（2023 现行版）》；
3. GB/T 国家标准 0 篇（openstd 合法性不确定，待用户决定）。
