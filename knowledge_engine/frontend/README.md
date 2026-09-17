# frontend

当前前端工程是为 `RAG_Sec` 后端补齐的独立 React + TypeScript + Vite MVP。

## 启动方式

在 `frontend/` 目录下执行：

```bash
npm install
npm run dev
```

默认开发地址：

- `http://localhost:5173`

## 后端地址配置

复制环境变量示例：

```bash
cp .env.example .env
```

默认后端：

```env
VITE_API_BASE_URL=http://localhost:8000
```

## 当前页面

- Dashboard
- Upload
- Retrieve
- Rewrite
- Answer
- Eval

## 当前目标

- 本地可运行
- 对接现有 FastAPI API
- 保持工程演示可用
- 便于后续继续扩展
