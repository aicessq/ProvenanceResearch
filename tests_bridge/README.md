# tests_bridge/（待 P3 实现）

本目录用于 `knowledge_engine` 与 `researcher` 的跨模块契约测试，当前只有文档，没有可执行测试。

按 P3a–P3d 分片增加 Cloud Model Adapter、索引身份、PDF/OCR/vision 的页/区域/资产 Evidence、KB/Tavily/arXiv、工具白名单/参数/失败隔离、有界 Agent 轨迹/预算/停止、Reader 融合、引用闸门及 HTTP/SSE 回放测试。使用 fake HTTP/LLM 或已脱敏 recorded 响应，测试实际 graph/executor，不仅 stub topology。

普通 PR 不读取用户真实凭证、不上传私库文件、不调用付费云服务；真实基础设施与云 smoke 按单独授权的样本和预算运行。

- [工具、Evidence 与云模型契约](../docs/design.md)
- [P3a–P3d 前置与验收](../docs/roadmap.md)
- [旧迁移回归基线](../docs/testing.md)
