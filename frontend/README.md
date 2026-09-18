# frontend/（待 P5 实现）

本目录用于统一研究前端与用户云服务配置，当前只有文档，不添加应用代码或依赖。

P5 在公共 HTTP/SSE、Evidence、ToolCall 契约冻结且评测通过后实施：三栏研究/证据/会话界面，工具调用状态，PDF 页与 OCR/图像区域引用定位，云 LLM/embedding/reranker/OCR/vision 与来源的受控配置入口。凭证仅交后端加密存储，不进入 localStorage 或 GET 响应；配置与出站授权分别管理。

两套旧子项目前端暂作过渡资产，统一前端通过替代验收后再删除。

- [目标设计](../docs/design.md)
- [P5 前置与验收](../docs/roadmap.md#p5--统一前端及云服务配置)
