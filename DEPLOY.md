# 部署指南

> 本地一键启动 → 服务器迁移的完整说明。架构约束（见 design.md）：无状态后端、
> 存储抽象、LangGraph 检查点在 PostgreSQL——迁移只动配置，不改代码。

## 一、本地一键启动（docker compose）

### 前置要求

- Docker / Docker Compose v2
- GLM API Key（[智谱开放平台](https://open.bigmodel.cn/)）

### 步骤

```bash
# 1. 配置密钥（backend/.env 已 gitignore，绝不提交）
cp backend/.env.example backend/.env
#    编辑 backend/.env：
#    GLM_API_KEY=你的key
#    DOWNLOAD_SIGNING_SECRET=随机长字符串   # 生产必须覆盖默认值

# 2. 构建镜像（国内网络加镜像前缀）
docker compose build backend frontend
#    国内加速：REGISTRY=docker.m.daocloud.io/ docker compose build backend frontend

# 3. 构建沙箱镜像（模型生成代码的隔离执行环境，一次性构建）
docker compose --profile tools build sandbox

# 4. 启动全部服务
docker compose up -d

# 5. 验证
curl http://localhost:8001/api/health        # {"status":"ok","db":"ok"}
open http://localhost:5180                    # 前端（nginx 同源反代 /api）
```

### 服务组成

| 服务 | 端口 | 说明 |
|------|------|------|
| postgres | 宿主 5433 | 业务库 + LangGraph 检查点 |
| backend | 宿主 8001 | FastAPI；启动时自动 `alembic upgrade head` |
| frontend | 宿主 5180 | nginx 托管 Vue 构建产物 + `/api` 反代（SSE 无缓冲） |
| sandbox | — | 仅构建打标签 `yixin-sandbox:latest`，不常驻 |

沙箱执行：backend 挂载宿主 `/var/run/docker.sock`，为每次代码执行创建一次性
容器（无网络 / CPU·内存·时长限额 / 非 root / 产出大小限额），执行完即销毁。

### 本地开发模式（不用容器跑后端）

```bash
docker compose up -d postgres          # 只起基础设施
cd backend && uv sync
uv run alembic upgrade head
uv run uvicorn app.main:app --reload --port 8001

cd frontend && npm ci && npm run dev -- --port 5180   # vite 代理 /api → 8001
```

## 二、迁服务器配置差异清单

代码不变，只改配置。逐项核对：

### 1. 环境变量（backend/.env 或编排环境）

| 变量 | 本地默认 | 服务器要求 |
|------|----------|-----------|
| `GLM_API_KEY` | 必填 | 必填（密钥管理服务或密文注入，不落明文文件） |
| `DATABASE_URL` | compose 内置 | 指向生产 PG（独立实例或托管服务），强密码 + TLS |
| `DOWNLOAD_SIGNING_SECRET` | dev 默认值 | **必须**换成 `openssl rand -hex 32` 生成的随机值 |
| `REQUIRE_USER_HEADER` | `false` | **必须** `true`——宿主网关注入 `X-User-Id`，缺失即 401 |
| `ALLOWED_ORIGINS` | localhost 列表 | 实际前端域名（逗号分隔；同源反代时可设为该域名） |
| `INTERNAL_API_TOKEN` | 空（接口关闭） | 运维需要用量查询时设置随机值，否则保持关闭 |
| `RATE_LIMIT_REQUESTS` | 120/分钟 | 按压测调整；多实例部署见下文限流说明 |
| `STORAGE_ROOT` | 容器卷 | 持久卷或接对象存储（实现 `StorageService` 接口） |
| `SANDBOX_IMAGE` | yixin-sandbox:latest | 服务器上重新构建一次沙箱镜像 |

### 2. 网关与身份

- 本模块**无注册/登录**：身份由宿主系统鉴权后经可信头 `X-User-Id` 注入。
  网关必须**剥离客户端伪造的同名头**再注入真实值，否则数据隔离失效。
- 所有业务表含 `user_id`，查询强制过滤；越权访问统一 404（不泄露存在性）。

### 3. HTTPS

- nginx/网关统一终结 TLS；容器间内网明文即可。
- SSE 经反代需关闭缓冲（本仓库 frontend/nginx.conf 已配置，可作网关参考）。

### 4. 数据与持久化

- `pgdata` / `artifacts` 两个卷纳入备份策略（产物文件不在库里）。
- 产物保留策略 v1 未清理（design.md Open Question），上线前按合规要求补。

### 5. 多实例横向扩展注意事项

- **限流**：当前为进程内滑动窗口（单实例语义）。多实例需换集中式实现
  （Redis），接口 `SlidingWindowLimiter.check/reset` 不变即可平滑替换。
- **沙箱执行**：每个后端实例都需挂载 docker.sock 并能拉到沙箱镜像。
- 检查点与会话状态全部在 PG，后端无状态，可直接扩。

### 6. 监控与运维

- `GET /api/health`：存活 + DB 连通（k8s probe / uptime 监控直接用）。
- 用量：`usage_events` 表（每次 LLM 调用：用户/模型/tokens/耗时；任务终态
  统计）。汇总查询：`GET /api/internal/usage/summary?user_id=..&since=..&until=..`
  + 请求头 `X-Internal-Token`（值 = `INTERNAL_API_TOKEN`）。
- 日志：`docker compose logs -f backend`；任务失败会落 `tasks.error` 与会话消息。

## 三、常见问题

- **端口冲突**：`FRONTEND_PORT=80 docker compose up -d` 可改前端端口；
  PG 宿主端口在 compose 中改 `5433:5432` 左侧。
- **沙箱镜像缺失**：任务报「run_python_code 执行失败」时先
  `docker compose --profile tools build sandbox`。
- **海报下载为空**：backend 镜像构建期已装 Chromium；自建镜像时确保
  `playwright install --with-deps chromium` 执行过。
