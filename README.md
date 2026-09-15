# 亿心对话智能体平台

双模式对话智能体 Web 产品：

- **普通对话模式**：用户消息直接送入 LLM（GLM），流式回复
- **工作模式**：Agent（LangGraph）完成任务（文档 / 表格 / PPT / 海报 / 数据处理），
  产物可预览、可按反馈增量修改（版本链）、满意后签名 URL 下载

需求与设计文档见 [`openspec/changes/add-dual-mode-chat-agent/`](openspec/changes/add-dual-mode-chat-agent/)。

## 仓库结构

```
├── backend/            # Python / FastAPI / LangGraph
│   ├── app/
│   │   ├── agent/      # LangGraph 执行图 + TaskRunner（插话注入/预览中断/反馈链）
│   │   ├── api/        # 路由与依赖
│   │   ├── llm/        # GLM 客户端（直答流式 / Agent 工具循环）
│   │   ├── models/     # SQLAlchemy 模型（全部含 user_id，对外多用户）
│   │   ├── services/   # 会话/直答/路由/工作流编排
│   │   ├── storage/    # StorageService 抽象 + 本地磁盘实现
│   │   └── tools/      # Agent 工具注册框架 + 内置工具
│   ├── alembic/        # 数据库迁移
│   └── tests/
├── frontend/           # Vue 3 + Element Plus + Vite
└── docker-compose.yml  # 本地基础设施（PostgreSQL 等）
```

## 本地启动

```bash
# 1. 基础设施（PostgreSQL）
docker compose up -d postgres

# 2. 后端
cd backend
cp .env.example .env          # 填 GLM_API_KEY
uv sync
uv run alembic upgrade head   # 建表
uv run uvicorn app.main:app --reload --port 8001

# 3. 前端
cd frontend
npm install
npm run dev                   # http://localhost:5173
```

## 关键约定

- 所有业务表带 `user_id`，文件路径按 `/artifacts/{user_id}/{task_id}/v{n}/` 分域
- 产物文件一律经 `StorageService` 接口读写（本地磁盘实现，后期可换 OSS/S3）
- 模型经 OpenAI 兼容协议接入 GLM，型号/端点均为配置项
