# 题目人工核对清单（REVIEW CHECKLIST）

> 全部 56 题当前 `verified: false`。核对完成后把对应行改成 `true` 并重跑
> `python3 validate_questions.py`。语料原资产在 `eval/corpus/pdf/`，
> 页级镜像在 `eval/corpus/text/<doc_id>.pages.jsonl`。

- [ ] 我已通读 `eval/questions/README.md` 的字段语义与冲突定义


## single_source

### q001（difficulty 2，expected: answered）

《网络安全法》（2025 修正）第二十三条要求网络运营者留存网络日志的最低期限是多久？

- 定位 1：`pdf/zh_cybersec_2025.pdf` 第 3 页（第二十三条第（三）项）

  逐字摘录（需在定位页命中）：
  - [ ] 并按照规定留存相关的网 络日志不少于六个月

  注：等级保护义务中的日志留存期限。

  - [ ] 核对通过，将 `"verified": false` 改为 `true`

### q002（difficulty 2，expected: answered）

《数据安全法》界定的“国家核心数据”包括哪些数据？实行什么管理制度？

- 定位 1：`pdf/zh_datasec_2021.pdf` 第 3 页（第二十一条第二款）

  逐字摘录（需在定位页命中）：
  - [ ] 关系国家安全、国民经济命脉、重要民生、 重大公共利益等数据属于国家核心数据，实行更 加严格的管理制度。

  注：核心数据定义。

  - [ ] 核对通过，将 `"verified": false` 改为 `true`

### q003（difficulty 2，expected: answered）

《个人信息保护法》中“敏感个人信息”的定义是什么？不满多少周岁的未成年人个人信息属于敏感个人信息？

- 定位 1：`pdf/zh_persinfo_2021.pdf` 第 4 页（第二十八条）

  逐字摘录（需在定位页命中）：
  - [ ] 敏感个人信息是一旦泄露或者 非法使用，容易导致自然人的人格尊严受到侵害 或者人身、财产安全受到危害的个人信息，包括 生物识别、宗教信仰、特定身份、医疗健康、金 融账户、行踪轨迹等信息，以及不满十四周岁未 成年人的个人信息。

  注：敏感个人信息定义 + 十四周岁线。

  - [ ] 核对通过，将 `"verified": false` 改为 `true`

### q004（difficulty 2，expected: answered）

《密码法》规定核心密码与普通密码分别用于保护什么信息？各自保护信息的最高密级是什么？

- 定位 1：`pdf/zh_crypto_2019.pdf` 第 2 页（第七条）

  逐字摘录（需在定位页命中）：
  - [ ] 核心密码、普通密码用于保护国家 秘密信息，核心密码保护信息的最高密级为绝密 级，普通密码保护信息的最高密级为机密级。

  注：密级对照：绝密级/机密级。

  - [ ] 核对通过，将 `"verified": false` 改为 `true`

### q005（difficulty 2，expected: answered）

依据《电子签名法》，电子签名同时符合哪些条件时视为“可靠的电子签名”？

- 定位 1：`pdf/zh_esign_2019.pdf` 第 2 页（第十三条）

  逐字摘录（需在定位页命中）：
  - [ ] 电子签名同时符合下列条件的， 视为可靠的电子签名：
  - [ ] （一）电子签名制作数据用于电子签名时， 属于电子签名人专有；
  - [ ] （三）签署后对电子签名的任何改动能够被 发现；

  注：四条件中的代表性两项 + 引导句。

  - [ ] 核对通过，将 `"verified": false` 改为 `true`

### q006（difficulty 3，expected: answered）

《反垄断法》（2022 修正）在哪些市场份额情形下可以推定经营者具有市场支配地位？

- 定位 1：`pdf/zh_antimon_2022.pdf` 第 3 页（第二十四条）

  逐字摘录（需在定位页命中）：
  - [ ] （一）一个经营者在相关市场的市场份额达 到二分之一的； （二）两个经营者在相关市场的市场份额合 计达到三分之二的； （三）三个经营者在相关市场的市场份额合 计达到四分之三的。

  注：三个推定份额 1/2、2/3、3/4。

  - [ ] 核对通过，将 `"verified": false` 改为 `true`

### q007（difficulty 2，expected: answered）

《未成年人保护法》对网络游戏服务提供者向未成年人提供网络游戏服务的时间段作了什么限制？

- 定位 1：`pdf/zh_minor_2024.pdf` 第 9 页（第七十五条）

  逐字摘录（需在定位页命中）：
  - [ ] 网络游戏服务提供者不得在每日二十二时至 次日八时向未成年人提供网络游戏服务。

  注：22 时至次日 8 时。

  - [ ] 核对通过，将 `"verified": false` 改为 `true`

### q008（difficulty 2，expected: answered）

《治安管理处罚法》（2025 修订）对行政拘留处罚合并执行的时长上限是怎么规定的？

- 定位 1：`pdf/zh_puborder_2025.pdf` 第 3 页（第十六条）

  逐字摘录（需在定位页命中）：
  - [ ] 行政拘留处罚合 并执行的，最长不超过二十日。

  注：合并执行上限二十日。

  - [ ] 核对通过，将 `"verified": false` 改为 `true`

### q009（difficulty 2，expected: answered）

《著作权法》（2020 修正）规定，当权利人实际损失、侵权人违法所得、权利使用费均难以计算时，法院判决赔偿的上下限是多少？

- 定位 1：`pdf/zh_copyr_2020.pdf` 第 9 页（第五十四条）

  逐字摘录（需在定位页命中）：
  - [ ] 由人民法院根据侵权行为 的情节,判决给予五百元以上五百万元以下的赔 偿.

  注：法定赔偿 500 元—500 万元。

  - [ ] 核对通过，将 `"verified": false` 改为 `true`

### q010（difficulty 3，expected: answered）

《行政处罚法》（2021 修订）第八十五条规定本法中哪些天数的表述是指工作日？

- 定位 1：`pdf/zh_admin_penalty_2021.pdf` 第 10 页（第八十五条）

  逐字摘录（需在定位页命中）：
  - [ ] 本法中“二日” “三日” “五 日”“七日”的规定是指工作日，不含法定节假 日。

  注：注意 raw 文本中引号间有少量空格，提取为空白折叠形态。

  - [ ] 核对通过，将 `"verified": false` 改为 `true`

### q011（difficulty 2，expected: answered）

RFC 6749 第 1.1 节定义 OAuth 2.0 的哪四个角色？其中 resource owner 指什么？

- 定位 1：`pdf/rfc_6749.txt` 第 6 页（Section 1.1）

  逐字摘录（需在定位页命中）：
  - [ ] OAuth defines four roles: resource owner
  - [ ] An entity capable of granting access to a protected resource.

  注：四角色 + resource owner 定义。

  - [ ] 核对通过，将 `"verified": false` 改为 `true`

### q012（difficulty 2，expected: answered）

RFC 7519 规定 JWT 在紧凑序列化下的表示形式是什么？各部分如何分隔？

- 定位 1：`pdf/rfc_7519.txt` 第 6 页（Section 3）

  逐字摘录（需在定位页命中）：
  - [ ] A JWT is represented as a sequence of URL-safe parts separated by period ('.') characters.

  注：period 分隔 + base64url。

  - [ ] 核对通过，将 `"verified": false` 改为 `true`

### q013（difficulty 2，expected: answered）

NIST AI RMF 1.0 的 Core 由哪四个高层功能组成？

- 定位 1：`pdf/us_nist_ai100_1.pdf` 第 25 页（Figure 5）

  逐字摘录（需在定位页命中）：
  - [ ] the Core is composed of four functions: GOVERN, MAP, MEASURE, and MANAGE.

  注：四功能。

  - [ ] 核对通过，将 `"verified": false` 改为 `true`

### q014（difficulty 3，expected: answered）

NIST SP 800-207 第 2 节给出的零信任（ZT）定义是什么？

- 定位 1：`pdf/us_nist_sp800_207.pdf` 第 13 页（Section 2）

  逐字摘录（需在定位页命中）：
  - [ ] Zero trust (ZT) provides a collection of concepts and ideas designed to minimize uncertainty in enforcing accurate, l…

  注：ZT 官方定义。

  - [ ] 核对通过，将 `"verified": false` 改为 `true`

### q015（difficulty 2，expected: answered）

论文《Evaluating Verifiability in Generative Search Engines》（arXiv 2304.09848 v1）报告的四个生成式搜索引擎整体引用精确率（citation precision）均值是多少？

- 定位 1：`pdf/arxiv/2304.09848v1.pdf` 第 2 页（Abstract/Conclusion）

  逐字摘录（需在定位页命中）：
  - [ ] only 74.5% of citations support their associated sentence

  注：74.5%。

  - [ ] 核对通过，将 `"verified": false` 改为 `true`


## multi_hop

### q016（difficulty 4，expected: answered）

《密码法》要求关键信息基础设施运营者采购涉及商用密码、可能影响国家安全的网络产品和服务时应依据哪部法律接受国家安全审查？该法（2025 修正《网络安全法》）规定的这项审查由谁组织？

- 定位 1：`pdf/zh_crypto_2019.pdf` 第 4 页（第二十七条第二款）
- 定位 2：`pdf/zh_cybersec_2025.pdf` 第 4 页（第三十七条）

  逐字摘录（需在定位页命中）：
  - [ ] 应 当按照《中华人民共和国网络安全法》的规定， 通过国家网信部门会同国家密码管理部门等有关 部门组织的国家安全审查。
  - [ ] 关键信息基础设施的运营者采 购网络产品和服务,可能影响国家安全的,应当 通过国家网信部门会同国务院有关部门组织的国 家安全审查。

  注：跨法引用：密码法 → 网络安全法。

  - [ ] 核对通过，将 `"verified": false` 改为 `true`

### q017（difficulty 4，expected: answered）

《数据安全法》第三十一条规定关键信息基础设施运营者的重要数据出境安全管理适用哪部法律？该法要求 CII 运营者收集和产生的个人信息和重要数据应当存储在哪里？

- 定位 1：`pdf/zh_datasec_2021.pdf` 第 4 页（第三十一条）
- 定位 2：`pdf/zh_cybersec_2025.pdf` 第 4 页（第三十九条）

  逐字摘录（需在定位页命中）：
  - [ ] 关键信息基础设施的运营者在 中华人民共和国境内运营中收集和产生的重要数 据的出境安全管理，适用《中华人民共和国网络 安全法》的规定
  - [ ] 关键信息基础设施的运营者在 中华人民共和国境内运营中收集和产生的个人信 息和重要数据应当在境内存储。

  注：跨法引用：数据安全法 → 网络安全法。

  - [ ] 核对通过，将 `"verified": false` 改为 `true`

### q018（difficulty 4，expected: answered）

《个人信息保护法》为向境外提供个人信息设定了哪些条件（答出标准合同路径）？《网络安全法》对 CII 运营者确需向境外提供个人信息和重要数据的前提是什么？

- 定位 1：`pdf/zh_persinfo_2021.pdf` 第 5 页（第三十八条）
- 定位 2：`pdf/zh_cybersec_2025.pdf` 第 4 页（第三十九条）

  逐字摘录（需在定位页命中）：
  - [ ] （三）按照国家网信部门制定的标准合同与 境外接收方订立合同，约定双方的权利和义务；
  - [ ] 因业务需要,确 需向境外提供的,应当按照国家网信部门会同国 务院有关部门制定的办法进行安全评估

  注：跨境路径 + CII 安全评估。

  - [ ] 核对通过，将 `"verified": false` 改为 `true`

### q019（difficulty 4，expected: answered）

《密码法》规定涉及国家安全、国计民生、社会公共利益的商用密码产品检测认证适用哪部法律的有关规定？要避免什么？《网络安全法》对网络关键设备和网络安全专用产品的销售前置条件是什么？

- 定位 1：`pdf/zh_crypto_2019.pdf` 第 3 页（第二十六条）
- 定位 2：`pdf/zh_cybersec_2025.pdf` 第 3 页（第二十五条）

  逐字摘录（需在定位页命中）：
  - [ ] 商 用密码产品检测认证适用《中华人民共和国网络 安全法》的有关规定，避免重复检测认证。
  - [ ] 网络关键设备和网络安全专用 产品应当按照相关国家标准的强制性要求,由具 备资格的机构安全认证合格或者安全检测符合要 求后,方可销售或者提供。

  注：密码法 → 网络安全法（认证互认）。

  - [ ] 核对通过，将 `"verified": false` 改为 `true`

### q020（difficulty 4，expected: answered）

治安管理处罚中，公安机关作出多大数额罚款（或什么措施）的决定前应告知当事人有权要求听证？《行政处罚法》规定哪些处罚决定应当告知听证权利？

- 定位 1：`pdf/zh_puborder_2025.pdf` 第 16 页（第一百一十七条）
- 定位 2：`pdf/zh_admin_penalty_2021.pdf` 第 7 页（第六十三条）

  逐字摘录（需在定位页命中）：
  - [ ] 公安机关作出吊销许可证 件、处四千元以上罚款的治安管理处罚决定或者 采取责令停业整顿措施前，应当告知违反治安管 理行为人有权要求举行听证
  - [ ] （一）较大数额罚款；

  注：治安 4000 元线 × 行政处罚法听证情形。

  - [ ] 核对通过，将 `"verified": false` 改为 `true`

### q021（difficulty 4，expected: answered）

《未成年人保护法》对为未成年人提供网络直播发布者账号注册服务有什么年龄限制？《个人信息保护法》要求处理不满多少周岁未成年人个人信息应取得谁的同意？

- 定位 1：`pdf/zh_minor_2024.pdf` 第 10 页（第七十六条）
- 定位 2：`pdf/zh_persinfo_2021.pdf` 第 4 页（第三十一条）

  逐字摘录（需在定位页命中）：
  - [ ] 为年满十六周岁的未成年人提供网络 直播发布者账号注册服务时，应当对其身份信息 进行认证，并征得其父母或者其他监护人同意
  - [ ] 个人信息处理者处理不满十四 周岁未成年人个人信息的，应当取得未成年人的 父母或者其他监护人的同意。

  注：16 周岁直播线 × 14 周岁监护同意线。

  - [ ] 核对通过，将 `"verified": false` 改为 `true`

### q022（difficulty 4，expected: answered）

RAG 原始论文（arXiv 2005.11401）提出用什么记忆组合的知识来源解决知识密集任务？《Lost in the Middle》（arXiv 2307.03172）发现相关信息处于输入上下文不同位置时的性能曲线是什么形状？

- 定位 1：`pdf/arxiv/2005.11401v1.pdf` 第 1 页（Abstract）
- 定位 2：`pdf/arxiv/2307.03172v3.pdf` 第 1 页（Abstract）

  逐字摘录（需在定位页命中）：
  - [ ] models which combine pre-trained parametric and non-parametric memory for language generation
  - [ ] a U-shaped performance curve

  注：跨论文：RAG 组合记忆 × U 形曲线。

  - [ ] 核对通过，将 `"verified": false` 改为 `true`

### q023（difficulty 4，expected: answered）

RFC 8446 指出 0-RTT 数据面临哪两类重放威胁？RFC 6749 要求 refresh token 在传输和存储中如何处理？

- 定位 1：`pdf/rfc_8446.txt` 第 98 页（Appendix E.5）
- 定位 2：`pdf/rfc_6749.txt` 第 55 页（Section 10.4）

  逐字摘录（需在定位页命中）：
  - [ ] Network attackers who mount a replay attack by simply duplicating a flight of 0-RTT data.
  - [ ] Refresh tokens MUST be kept confidential in transit and storage

  注：跨 RFC：TLS 重放 × OAuth 保密。

  - [ ] 核对通过，将 `"verified": false` 改为 `true`

### q024（difficulty 4，expected: answered）

NIST AI RMF 1.0 列出的可信 AI 系统特征有哪些（至少四项）？Self-RAG（arXiv 2310.11511）通过生成什么 token 使模型在推理阶段可控？

- 定位 1：`pdf/us_nist_ai100_1.pdf` 第 17 页（Section 1.3）
- 定位 2：`pdf/arxiv/2310.11511v1.pdf` 第 1 页（Abstract）

  逐字摘录（需在定位页命中）：
  - [ ] valid and reliable, safe, secure and resilient
  - [ ] explainable and interpretable
  - [ ] privacy-enhanced
  - [ ] Generating reflection tokens makes the LM controllable during the inference phase, enabling it to tailor its behavior…

  注：跨源：NIST 特征 × Self-RAG reflection tokens。

  - [ ] 核对通过，将 `"verified": false` 改为 `true`

### q025（difficulty 4，expected: answered）

《行政处罚法》允许当场作出行政处罚决定的罚款限额（对公民、对法人或其他组织）分别是多少？治安案件中公安派出所可以自行决定的处罚范围是什么？

- 定位 1：`pdf/zh_admin_penalty_2021.pdf` 第 6 页（第五十一条）
- 定位 2：`pdf/zh_puborder_2025.pdf` 第 15 页（第一百零九条）

  逐字摘录（需在定位页命中）：
  - [ ] 对公民处以二百元以下、对法人或者其他组织处 以三千元以下罚款或者警告的行政处罚的，可以 当场作出行政处罚决定。
  - [ ] 警告、一千元以 下的罚款，可以由公安派出所决定。

  注：当场处罚 200/3000 × 派出所 1000 元权限。

  - [ ] 核对通过，将 `"verified": false` 改为 `true`


## external_only

### q026（difficulty 2，expected: answered）

提出 Transformer 架构的论文《Attention Is All You Need》的 arXiv 编号是多少？其核心主张（对新架构的表述）是什么？

- 定位 1（外部）：https://arxiv.org/abs/1706.03762  arXiv:1706.03762v7

  逐字摘录（需在定位页命中）：
  - [ ] We propose a new simple network architecture, the Transformer, based solely on attention mechanisms, dispensing with …

  注：arXiv 1706.03762；required_points 摘自 arXiv API 摘要原文，脚本无法离线复核，需人工核对。

  - [ ] 核对通过，将 `"verified": false` 改为 `true`

### q027（difficulty 2，expected: answered）

GPT-4 技术报告（arXiv 2303.08774）的开发方与 GPT-4 的模态能力是什么？

- 定位 1（外部）：https://arxiv.org/abs/2303.08774  arXiv:2303.08774v1

  逐字摘录（需在定位页命中）：
  - [ ] We report the development of GPT-4, a large-scale, multimodal model which can accept image and text inputs and produc…

  注：arXiv 2303.08774；摘自 API 摘要原文，需人工核对。

  - [ ] 核对通过，将 `"verified": false` 改为 `true`

### q028（difficulty 2，expected: answered）

BERT 论文（arXiv 1810.04805）中 BERT 的全称是什么？它与此前语言表示模型的关键区别（预训练方向性）是什么？

- 定位 1（外部）：https://arxiv.org/abs/1810.04805  arXiv:1810.04805v2

  逐字摘录（需在定位页命中）：
  - [ ] BERT, which stands for Bidirectional Encoder Representations from Transformers
  - [ ] BERT is designed to pre-train deep bidirectional representations from unlabeled text by jointly conditioning on both …

  注：arXiv 1810.04805；摘自 API 摘要原文，需人工核对。

  - [ ] 核对通过，将 `"verified": false` 改为 `true`

### q029（difficulty 2，expected: answered）

InstructGPT 论文（arXiv 2203.02155）对“把语言模型做得更大”与“遵循用户意图”之间的关系给出了什么论断？

- 定位 1（外部）：https://arxiv.org/abs/2203.02155  arXiv:2203.02155v1

  逐字摘录（需在定位页命中）：
  - [ ] Making language models bigger does not inherently make them better at following a user's intent.

  注：arXiv 2203.02155；摘自 API 摘要原文，需人工核对。

  - [ ] 核对通过，将 `"verified": false` 改为 `true`

### q030（difficulty 2，expected: answered）

TLS 1.2 由哪个 RFC 定义？其完整标题是什么？

- 定位 1（外部）：https://www.rfc-editor.org/info/rfc5246

  逐字摘录（需在定位页命中）：
  - [ ] The Transport Layer Security (TLS) Protocol Version 1.2
  - [ ] RFC 5246

  注：RFC 5246；标题经 rfc-editor.org 核对，需人工复核。

  - [ ] 核对通过，将 `"verified": false` 改为 `true`

### q031（difficulty 2，expected: answered）

《生成式人工智能服务管理暂行办法》自何时起施行？由几部门联合发布？

- 定位 1（外部）：http://www.cac.gov.cn/2023-07/13/c_1690898327029107.htm

  逐字摘录（需在定位页命中）：
  - [ ] 自2023年8月15日起施行
  - [ ] 七部门

  注：构建时经 WebFetch 核对（国家网信办等七部门第15号令，2023-07-10 发布）；需人工复核原文。

  - [ ] 核对通过，将 `"verified": false` 改为 `true`

### q032（difficulty 3，expected: answered）

《关键信息基础设施安全保护条例》自何时起施行？（注意：该条例因 flk 无 PDF 版本未收入语料，需联网获取）

- 定位 1（外部）：https://flk.npc.gov.cn/detail?id=ff8081817b63b935017b7bcc49877e0b

  逐字摘录（需在定位页命中）：
  - [ ] 2021年9月1日

  注：构建时经 flk 官方 API 核对（sxrq=2021-09-01，国务院 2021-07-30 公布）；需人工复核。

  - [ ] 核对通过，将 `"verified": false` 改为 `true`

### q033（difficulty 2，expected: answered）

本系统向量检索使用的 Qdrant 的默认服务端口（HTTP）是多少？

- 定位 1（外部）：https://qdrant.tech/documentation/guides/install/

  逐字摘录（需在定位页命中）：
  - [ ] 6333

  注：构建时经 WebFetch 官方文档核对（gRPC 6334）；需人工复核。

  - [ ] 核对通过，将 `"verified": false` 改为 `true`


## version_contrast

### q034（difficulty 4，expected: answered）

2025 年修正《网络安全法》新增的人工智能促进条款经修改决定列为第几条？成为新法第几条？该条第一款的完整表述是什么？

- 定位 1：`pdf/zh_cybersec_amend_2025.pdf` 第 1 页（三、）
- 定位 2：`pdf/zh_cybersec_2025.pdf` 第 2 页（第二十条）

  逐字摘录（需在定位页命中）：
  - [ ] 三、增加一条,作为第二十条: “国家支持 人工智能基础理论研究和算法等关键技术研发, 推进训练数据资源、算力等基础设施建设,完善 人工智能伦理规范,加强风险监测评估和安全监 管,促进人工智能应用和健康发展。
  - [ ] 第二十条 国家支持人工智能基础理论研究 和算法等关键技术研发,推进训练数据资源、算 力等基础设施建设,完善人工智能伦理规范,加 强风险监测评估和安全监管,促进人工智能应用 和健康发展。

  注：修改决定第三项 ↔ 2025 新法第二十条（2016 版无此条，2016 版为扫描件无文本层）。

  - [ ] 核对通过，将 `"verified": false` 改为 `true`

### q035（difficulty 4，expected: answered）

《关于修改〈中华人民共和国网络安全法〉的决定》与根据该决定重新公布的《网络安全法》分别自何时起施行？两者为何不同？

- 定位 1：`pdf/zh_cybersec_amend_2025.pdf` 第 3 页（末段）
- 定位 2：`pdf/zh_cybersec_2025.pdf` 第 10 页（第八十一条）

  逐字摘录（需在定位页命中）：
  - [ ] 本决定自2026年1月1日起施行。
  - [ ] 第八十一条 本法自2017年6月1日起施 行。

  forbidden（回答中不得出现）：2026年1月1日施行

  注：陷阱题：本法条文仍保留 2017 年施行日期（修正不改变原施行日），修改决定自身自 2026-01-01 施行；forbidden 为不得把“本法自2017年6月1日起施行”说成 2026 年施行。

  - [ ] 核对通过，将 `"verified": false` 改为 `true`

### q036（difficulty 4，expected: answered）

2025 修正将原第五十九条改为第六十一条并加重处罚：造成关键信息基础设施丧失主要功能等特别严重危害网络安全后果的，对运营者罚款幅度是多少？对直接责任人员的幅度是多少？

- 定位 1：`pdf/zh_cybersec_amend_2025.pdf` 第 2 页（五、）
- 定位 2：`pdf/zh_cybersec_2025.pdf` 第 7 页（第六十一条）

  逐字摘录（需在定位页命中）：
  - [ ] 造成 关键信息基础设施丧失主要功能等特别严重危害 网络安全后果的,处二百万元以上一千万元以下 罚款,对直接负责的主管人员和其他直接责任人 员处二十万元以上一百万元以下罚款。”
  - [ ] 造成关 键信息基础设施丧失主要功能等特别严重危害网 络安全后果的,处二百万元以上一千万元以下罚 款,对直接负责的主管人员和其他直接责任人员 处二十万元以上一百万元以下罚款。

  注：修改决定第五项 ↔ 新法第六十一条第三款；注意 2016 版原文无此梯度（旧版为扫描件）。

  - [ ] 核对通过，将 `"verified": false` 改为 `true`

### q037（difficulty 4，expected: answered）

2025 修正决定第八项对“责令暂停相关业务”等表述做了什么修改？修改后的处罚表述新增了哪种关停对象？

- 定位 1：`pdf/zh_cybersec_amend_2025.pdf` 第 2 页（八、）
- 定位 2：`pdf/zh_cybersec_2025.pdf` 第 7 页（第六十四条）

  逐字摘录（需在定位页命中）：
  - [ ] “并可以由有关主管部门责令暂停相关业务、停 业整顿、关闭网站、吊销相关业务许可证或者吊 销营业执照”修改为“并可以责令暂停相关业 务、停业整顿、关闭网站或者应用程序、吊销相 关业务许可证或者吊销营业执照”
  - [ ] 责令暂停相关业务、停业整顿、关闭网站或 者应用程序、吊销相关业务许可证或者吊销营业 执照

  注：旧表述“关闭网站”→ 新表述“关闭网站或者应用程序”；原 forbidden 短语与修改决定引文中的旧表述重叠、会误伤正确答案，已移除，陷阱说明保留在本注记。

  - [ ] 核对通过，将 `"verified": false` 改为 `true`

### q038（difficulty 4，expected: answered）

arXiv 2304.09848 的 v1 与 v2 对“引用指标与感知有用性的相关性”表述有何差异？v2 补充了什么数值？

- 定位 1：`pdf/arxiv/2304.09848v1.pdf` 第 2 页（Section 1）
- 定位 2：`pdf/arxiv/2304.09848v2.pdf` 第 2 页（Section 1）

  逐字摘录（需在定位页命中）：
  - [ ] citation recall and precision are inversely correlated with ﬂuency and perceived utility
  - [ ] citation precision is inversely correlated with perceived utility (r = −0.96)

  注：v1: recall 和 precision 都与流畅度/感知有用性负相关；v2: 收敛为 precision 与 perceived utility 负相关并给出 r=-0.96。注意 v1 原文含 ﬂ 连字（ﬂ）。

  - [ ] 核对通过，将 `"verified": false` 改为 `true`


## insufficient

### q039（difficulty 2，expected: refused）

《欧盟通用数据保护条例》（GDPR）第 17 条“被遗忘权”要求控制者在收到删除请求后多少天内完成删除？


  forbidden（回答中不得出现）：30天；三十天；45天；四十五天；90天
  refuse_reason：topic_absent

  注：语料不含 GDPR；且 GDPR 原文为“without undue delay”并无固定天数——任何具体天数都属无据推断。

  - [ ] 核对通过，将 `"verified": false` 改为 `true`

### q040（difficulty 2，expected: refused）

美国《加州消费者隐私法》（CCPA）要求企业在收到消费者删除请求后多长时间内完成删除？


  forbidden（回答中不得出现）：45天；四十五天
  refuse_reason：topic_absent

  注：语料不含 CCPA；真实答案有期限数字，用于拦截无据编造。

  - [ ] 核对通过，将 `"verified": false` 改为 `true`

### q041（difficulty 2，expected: refused）

《上海市数据条例》对公共数据授权运营机制作了哪些规定？

  refuse_reason：topic_absent

  注：语料为全国性法律与境外公开文件，不含地方性法规。

  - [ ] 核对通过，将 `"verified": false` 改为 `true`

### q042（difficulty 3，expected: refused）

《个人信息保护法》第五十八条“用户数量巨大”具体指多少用户？达到什么数量需要指定个人信息保护负责人？

- 定位 1：`pdf/zh_persinfo_2021.pdf` 第 6 页（第五十二条）

  逐字摘录（需在定位页命中）：
  - [ ] 处理个人信息达到国家网信部 门规定数量的个人信息处理者应当指定个人信息 保护负责人

  forbidden（回答中不得出现）：一百万；100万；5000万；五千万人
  refuse_reason：missing_key_fact

  注：主题相关但语料只写“国家网信部门规定数量”，未给出具体数字；不得用任何数字补齐。

  - [ ] 核对通过，将 `"verified": false` 改为 `true`

### q043（difficulty 3，expected: refused）

《数据安全法》要求制定“重要数据目录”——目前正式发布的重要数据目录具体覆盖了哪些行业？

- 定位 1：`pdf/zh_datasec_2021.pdf` 第 3 页（第二十一条）

  逐字摘录（需在定位页命中）：
  - [ ] 国家数据安全工作协调机制统筹协调有关 部门制定重要数据目录，加强对重要数据的保 护。
  refuse_reason：missing_key_fact

  注：语料只有制度性表述，无目录内容。

  - [ ] 核对通过，将 `"verified": false` 改为 `true`

### q044（difficulty 3，expected: refused）

《网络安全法》第二十三条提到“网络安全等级保护制度”——该制度共分为几个等级？

- 定位 1：`pdf/zh_cybersec_2025.pdf` 第 3 页（第二十三条）

  逐字摘录（需在定位页命中）：
  - [ ] 国家实行网络安全等级保护制 度。

  forbidden（回答中不得出现）：五个等级；5个等级；五级
  refuse_reason：missing_key_fact

  注：等保分级数在配套国家标准（GB 17859 等）中，语料未收录任何国家标准。

  - [ ] 核对通过，将 `"verified": false` 改为 `true`

### q045（difficulty 3，expected: refused）

2015 年修正版《电子签名法》第十八条规定的电子认证服务许可审批时限与 2019 年修正版一致吗？具体是多少日？

- 定位 1：`pdf/zh_esign_2019.pdf` 第 3 页（第十八条）

  逐字摘录（需在定位页命中）：
  - [ ] 自接到申请之 日起四十五日内作出许可或者不予许可的决定。

  forbidden（回答中不得出现）：与2019年修正版完全一致；两版完全相同
  refuse_reason：missing_key_fact

  注：语料中 2015 版为扫描件（text_layer_ok=false），无文本层证据，不得由 2019 版推断 2015 版内容。

  - [ ] 核对通过，将 `"verified": false` 改为 `true`

### q046（difficulty 3，expected: refused）

2007 年公布的《反垄断法》对达成并实施垄断协议的经营者规定的罚款幅度与 2022 年修正版一致吗？

- 定位 1：`pdf/zh_antimon_2022.pdf` 第 7 页（第五十六条）

  逐字摘录（需在定位页命中）：
  - [ ] 并处上一年度销售额百 分之一以上百分之十以下的罚款

  forbidden（回答中不得出现）：与2022年修正版完全一致；两版完全相同
  refuse_reason：missing_key_fact

  注：语料中 2007 版为扫描件（text_layer_ok=false），无文本层证据。

  - [ ] 核对通过，将 `"verified": false` 改为 `true`

### q047（difficulty 3，expected: refused）

自《个人信息保护法》2021 年施行以来，依据该法对单一企业开出的最高罚款金额是多少？

- 定位 1：`pdf/zh_persinfo_2021.pdf` 第 8 页（第六十六条）

  逐字摘录（需在定位页命中）：
  - [ ] 并处五千万元以下或者上一年度 营业额百分之五以下罚款

  forbidden（回答中不得出现）：80.26亿；80.26亿元
  refuse_reason：missing_key_fact

  注：语料只有法定上限，无执法案例数据；80.26 亿系滴滴案（网络安全法等），易被误接到个保法。

  - [ ] 核对通过，将 `"verified": false` 改为 `true`

### q048（difficulty 2，expected: refused）

IETF 计划在什么时间发布 TLS 1.4？

- 定位 1：`pdf/rfc_8446.txt` 第 1 页（标题页）
  refuse_reason：requires_prediction

  注：要求预测未来标准发布时间；语料只有 TLS 1.3。

  - [ ] 核对通过，将 `"verified": false` 改为 `true`

### q049（difficulty 2，expected: refused）

NIST 预计何时发布 AI RMF 2.0？

- 定位 1：`pdf/us_nist_ai100_1.pdf` 第 1 页（标题页）
  refuse_reason：requires_prediction

  注：要求预测未发布的标准版本。

  - [ ] 核对通过，将 `"verified": false` 改为 `true`

### q050（difficulty 3，expected: refused）

按 NIST AI RMF 的四个核心功能对 GPT-4 逐项打分，GOVERN 功能应得多少分？

- 定位 1：`pdf/us_nist_ai100_1.pdf` 第 25 页（Figure 5）
  refuse_reason：requires_prediction

  注：要求主观评价而非事实检索；框架本身不提供模型评分。

  - [ ] 核对通过，将 `"verified": false` 改为 `true`


## near_miss

### q051（difficulty 3，expected: answered）

《电子签名法》第二十三条：电子认证服务提供者拟暂停或终止服务时，提前通知有关各方与向国务院信息产业主管部门报告的期限分别是多少日？

- 定位 1：`pdf/zh_esign_2019.pdf` 第 3 页（第二十三条）

  逐字摘录（需在定位页命中）：
  - [ ] 应当在暂停或者终止服 务九十日前，就业务承接及其他有关事项通知有 关各方。
  - [ ] 应当在暂停或者终止服务六十日前向 国务院信息产业主管部门报告

  forbidden（回答中不得出现）：九十日前向国务院信息产业主管部门报告；六十日前就业务承接及其他有关事项通知有关各方

  注：相邻两句 90 日/60 日，数字对调即错。

  - [ ] 核对通过，将 `"verified": false` 改为 `true`

### q052（difficulty 4，expected: answered）

《行政处罚法》第六十四条：当事人要求听证应在告知后几日内提出？行政机关应在听证举行几日前通知当事人？这些“日”按什么计算？

- 定位 1：`pdf/zh_admin_penalty_2021.pdf` 第 8 页（第六十四条）

  逐字摘录（需在定位页命中）：
  - [ ] 当事人要求听证的，应当在行政机关 告知后五日内提出；
  - [ ] 行政机关应当在举行听证的七日前， 通知当事人及有关人员听证的时间、地点

  forbidden（回答中不得出现）：告知后七日内提出；举行听证的五日前

  注：5 日/7 日对调陷阱；“日”的工作日口径见第八十五条（q010）。

  - [ ] 核对通过，将 `"verified": false` 改为 `true`

### q053（difficulty 4，expected: answered）

《密码法》第三十七条：CII 运营者未按要求使用商用密码或未开展应用安全性评估的罚款标准是什么？使用未经安全审查或审查未通过的产品的罚款标准又是什么？

- 定位 1：`pdf/zh_crypto_2019.pdf` 第 5 页（第三十七条）

  逐字摘录（需在定位页命中）：
  - [ ] 处十万元以上一百万元以下罚款，对直接负责的 主管人员处一万元以上十万元以下罚款。
  - [ ] 处采购金额一倍以上十倍以下罚 款

  forbidden（回答中不得出现）：未按要求使用商用密码处采购金额一倍以上十倍以下罚款

  注：同条两款：固定金额幅度 × 采购金额倍数，主体对调即错。

  - [ ] 核对通过，将 `"verified": false` 改为 `true`

### q054（difficulty 4，expected: answered）

《反垄断法》第五十六条：对“达成并实施”垄断协议与“达成但尚未实施”的罚款有什么不同？

- 定位 1：`pdf/zh_antimon_2022.pdf` 第 7 页（第五十六条）

  逐字摘录（需在定位页命中）：
  - [ ] 并处上一年度销售额百 分之一以上百分之十以下的罚款
  - [ ] 尚未实施所 达成的垄断协议的，可以处三百万元以下的罚 款。

  forbidden（回答中不得出现）：尚未实施所达成的垄断协议的，并处上一年度销售额百分之一以上百分之十以下的罚款

  注：已实施=销售额百分比；尚未实施=300 万以下。

  - [ ] 核对通过，将 `"verified": false` 改为 `true`

### q055（difficulty 4，expected: answered）

《个人信息保护法》第六十六条：违法处理个人信息“拒不改正”的罚款上限与“情节严重”的罚款标准分别是什么？

- 定位 1：`pdf/zh_persinfo_2021.pdf` 第 8 页（第六十六条）

  逐字摘录（需在定位页命中）：
  - [ ] 拒不改正的，并处一百万元以下罚款
  - [ ] 并处五千万元以下或者上一年度 营业额百分之五以下罚款

  forbidden（回答中不得出现）：情节严重的，并处一百万元以下罚款

  注：同一法条两档：100 万 vs 5000 万/5%。

  - [ ] 核对通过，将 `"verified": false` 改为 `true`

### q056（difficulty 4，expected: answered）

RFC 8446：0-RTT 数据的安全性质与其他 TLS 数据相比如何？其前向保密性如何、仅用什么派生的密钥加密？

- 定位 1：`pdf/rfc_8446.txt` 第 19 页（Section 2.3）

  逐字摘录（需在定位页命中）：
  - [ ] The security properties for 0-RTT data are weaker than those for other kinds of TLS data.
  - [ ] This data is not forward secret, as it is encrypted solely under keys derived using the offered PSK.

  forbidden（回答中不得出现）：0-RTT data is forward secret

  注：0-RTT 弱安全性质 + 仅 PSK 派生密钥、无前向保密。

  - [ ] 核对通过，将 `"verified": false` 改为 `true`
