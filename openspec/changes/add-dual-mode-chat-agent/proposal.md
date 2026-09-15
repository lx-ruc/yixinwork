# Proposal: add-dual-mode-chat-agent

## Why

要做一个**双模式对话智能体模块**（嵌入宿主系统的 Web 模块）：用户既能像普通 AI 助手一样闲聊提问（直接 LLM 回复），也能把实际工作交给 Agent 完成（处理数据、做 PPT、生成海报、写文档等），工作成果可预览、可按反馈增量修改、满意后可下载。单一的"聊天"或单一的"自动化工具"都无法覆盖这两类需求，双模式是模块的核心差异化。

**范围约束**：本模块是宿主系统的一部分，注册/登录等鉴权由宿主系统负责；模块通过可信身份头（`X-User-Id`）接收用户身份并据此做数据隔离，自身不实现用户体系。

## What Changes

- **全新产品（绿地项目）**，从零建立前后端代码库
- **双模式会话**：
  - 普通对话模式：直接调用 LLM，流式回复
  - 工作模式：调用 Agent（LangGraph 工具循环）完成任务，产出通用类型产物（文档/表格/PPT/海报/数据结果）
- **智能路由**：普通对话模式下，路由器识别"任务型"消息后弹出确认卡片，用户一键切换到工作模式（消息原样带入），不自动执行
- **消息即指令**：工作模式内，用户消息始终进入 Agent 对话流——执行中插话 = 转向/追加指令；预览后反馈 = 增量修改指令，跟随**最近一个产物**
- **产物生命周期**：中间格式（md/HTML）→ web 预览（策略 C：按类型混合）→ 版本链（v1→v2→…）→ 满意后签名 URL 下载最终格式（docx/xlsx/png/pdf 等）
- **身份上下文与数据隔离**：接收宿主系统注入的 `X-User-Id` 可信头（生产缺失即 401），所有数据按 user_id 隔离；模块自身不做注册/登录
- **代码沙箱**：Agent 现场写的数据处理代码在加固 Docker 容器中执行（无网络、资源限额、非 root）；可信工具函数（文件生成/转换）在进程内执行
- **模型接入**：GLM（OpenAI 兼容协议），配置化可替换
- **用量埋点**：第一天起记录每次 LLM 调用的 user/tokens/耗时（只记不扣，为将来配额/计费留数据）
- **部署路径**：本地 docker-compose 起步，架构保证可平迁服务器（无状态后端 + PG 检查点 + StorageService 存储抽象）

## Capabilities

### New Capabilities

- `dual-mode-conversation`: 双模式会话——普通对话直答（流式）与工作模式会话的结构、消息通道（SSE）、模式显式切换
- `smart-mode-routing`: 智能路由——任务/闲聊识别、确认卡片交互、消息携带切换
- `agent-task-execution`: 工作模式 Agent 执行——LangGraph 工具循环、进程内工具层（文件生成/格式转换）、执行过程事件流、执行中消息注入（转向）
- `artifact-lifecycle`: 产物生命周期——版本链（interrupt 暂停/恢复承载增量修改）、类型混合预览（策略 C）、sandbox iframe 安全预览、签名 URL 下载
- `code-sandbox`: 代码沙箱——模型生成代码的 Docker 隔离执行（加固约束）、结果回传
- `identity-context`: 身份上下文——宿主系统注入的 X-User-Id 可信头解析、生产严格模式（缺失 401）、数据按用户隔离（含文件路径分域）
- `usage-tracking`: 用量记录——LLM 调用与任务执行的用量流水

### Modified Capabilities

（绿地项目，无既有 capability）

## Impact

- **新增代码库**：
  - `frontend/`：Vue 3 + Element Plus + Vite（对话流、模式切换、路由确认卡片、产物预览面板）
  - `backend/`：Python + FastAPI + LangGraph（会话/路由/Agent 循环/工具层/产物服务）
- **基础设施**：PostgreSQL（业务数据 + LangGraph checkpoints）、Docker（沙箱）、本地磁盘存储（经 StorageService 抽象，后期可换 OSS/S3）
- **外部依赖**：GLM API（OpenAI 兼容端点）、pandoc / playwright / python-pptx / openpyxl / python-docx 等生成与转换工具链
- **安全面**（对外必须）：沙箱加固、预览 XSS（sandbox iframe + CSP）、下载签名 URL 与路径防护、API 限流、身份头校验（生产缺失 401）
