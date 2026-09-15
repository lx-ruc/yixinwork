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
├── docker-compose.yml  # 一键启动（postgres + backend + frontend）
└── DEPLOY.md           # 部署指南（本地一键启动 / 迁服务器差异清单）
```

## 快速开始（docker 一键启动）

```bash
cp backend/.env.example backend/.env    # 填 GLM_API_KEY、DOWNLOAD_SIGNING_SECRET
docker compose build backend frontend
docker compose --profile tools build sandbox   # 沙箱镜像（一次性）
docker compose up -d

curl http://localhost:8001/api/health   # {"status":"ok","db":"ok"}
open http://localhost:5180
```

完整说明（含国内镜像加速、常见问题、**迁服务器配置差异清单**）见
[`DEPLOY.md`](./DEPLOY.md)。

## 本地开发（裸跑后端）

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
npm run dev -- --port 5180    # http://localhost:5180（vite 代理 /api → 8001）
```

## 关键约定

- 所有业务表带 `user_id`，文件路径按 `/artifacts/{user_id}/{task_id}/v{n}/` 分域
- 产物文件一律经 `StorageService` 接口读写（本地磁盘实现，后期可换 OSS/S3）
- 模型经 OpenAI 兼容协议接入 GLM，型号/端点均为配置项
