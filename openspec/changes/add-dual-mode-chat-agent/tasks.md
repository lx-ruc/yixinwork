# Tasks: add-dual-mode-chat-agent

## 1. 项目脚手架

- [x] 1.1 建立 monorepo 结构（`frontend/` + `backend/` + `docker-compose.yml` + README）
- [x] 1.2 后端骨架：FastAPI 应用、配置加载（env：GLM key/端点、DB 连接）、健康检查端点
- [x] 1.3 PostgreSQL 容器与连接：建库、alembic 迁移基线、sessions/messages/tasks/artifacts/versions/usage_events 表（全部含 user_id；users 表取消——身份归宿主系统）
- [x] 1.4 前端骨架：Vue 3 + Element Plus + Vite，路由与基础布局（左侧对话流 / 右侧产物面板占位）
- [x] 1.5 StorageService 存储抽象接口 + 本地磁盘实现（路径规则 `/artifacts/{user_id}/{task_id}/v{n}/`）

## 2. 身份上下文与数据隔离（identity-context）

> 鉴权由宿主系统负责，模块只接收可信身份头。（原注册/登录方案已取消）

- [x] 2.1 X-User-Id 身份依赖：解析可信头；生产模式（REQUIRE_USER_HEADER=true）缺失返回 401；开发态回退默认用户
- [x] 2.2 数据隔离校验：会话/任务/产物查询强制 user_id 过滤，集成测试覆盖越权场景（随 G3 端点落地）

## 3. 普通对话模式（dual-mode-conversation）

- [x] 3.1 GLM 接入：OpenAI 兼容客户端封装（base_url 可配置、流式）
- [x] 3.2 会话 CRUD 端点（创建/列表/恢复，按用户隔离）
- [x] 3.3 消息端点 + SSE 流式回复直答链路（后端）
- [x] 3.4 前端对话流 UI：消息渲染、SSE 接收、流式打字展示、会话切换
- [x] 3.5 前端模式开关（普通对话/工作模式），切换状态随会话持久化

## 4. 智能路由（smart-mode-routing）

- [x] 4.1 任务/闲聊分类器（规则优先起步，预留小模型分类接口），输出结构化判定
- [x] 4.2 路由集成：普通对话模式下分类 → 任务型返回确认卡片事件（SSE）
- [x] 4.3 确认/拒绝端点：确认则携带原消息进入工作模式，拒绝则原消息走直答
- [x] 4.4 前端确认卡片组件与两种点击流转

## 5. Agent 执行核心（agent-task-execution）

- [x] 5.1 **Spike：LangGraph 执行中消息注入**——验证工具循环间隙检查消息队列并注入的可行方案，结论回写 design.md
- [x] 5.2 LangGraph 图搭建：execute 节点（工具循环）+ interrupt 预览节点 + finalize 节点，接入 AsyncPostgresSaver
- [x] 5.3 任务状态机持久化（待命/执行中/预览就绪/已交付/失败）与重启恢复
- [x] 5.4 执行过程事件流：工具调用/步骤/中间输出经 SSE 推送
- [x] 5.5 执行中插话链路：消息入队 → 循环间隙注入 → Agent 响应转向
- [x] 5.6 前端工作模式执行视图：过程事件时间线、可插话输入框
- [x] 5.7 预览就绪反馈链路：修改指令恢复 thread + 注入反馈（增量修改入口）

## 6. 可信工具层（agent-task-execution）

- [x] 6.1 工具注册框架（Agent 可调用工具的定义/校验/调用封装）
- [x] 6.2 文档工具：Markdown 中间格式生成与预览渲染数据
- [x] 6.3 海报工具：HTML 模板生成 + playwright 渲染 png
- [x] 6.4 表格工具：HTML 表格预览数据 + openpyxl 生成 xlsx
- [x] 6.5 幻灯片工具：HTML slides 预览 + pptx/pdf 转换（含保真度降级路径）

## 7. 代码沙箱（code-sandbox）

- [x] 7.1 沙箱执行服务：按任务创建容器、运行代码、收集 stdout/文件/错误、销毁容器
- [x] 7.2 加固：无网络、CPU/内存/时长限额、非 root、产出大小限额
- [x] 7.3 沙箱工具接入 Agent（作为代码执行工具）+ 失败/超时回传处理
- [x] 7.4 沙箱安全测试：超时终止、网络阻断、残留清理验证

## 8. 产物生命周期（artifact-lifecycle）

- [x] 8.1 产物与版本模型：任务↔产物↔版本关联、文件落盘、元数据入 PG
- [x] 8.2 预览接口：按类型返回可渲染预览数据（md/html/表格/slides）
- [x] 8.3 预览安全：sandbox iframe + CSP，XSS 测试用例（含 script 注入验证）
- [x] 8.4 版本链交互：前端版本切换、历史版本查看、修改指令默认跟随最近产物
- [x] 8.5 满意确认 + 下载转换（md→docx / 数据→xlsx / HTML→png / slides→pptx·pdf）
- [x] 8.6 签名 URL 下载端点：过期时间、所有者校验、路径穿越防护

## 9. 用量记录（usage-tracking）

- [x] 9.1 LLM 调用用量埋点（用户/模型/tokens/耗时/会话/任务），直答与 Agent 循环全覆盖
- [x] 9.2 任务执行统计（时长、工具调用数、沙箱执行数）
- [x] 9.3 用量汇总查询内部接口（按用户+时间范围）

## 10. 安全加固与端到端验收

- [x] 10.1 API 限流（按用户/IP）
- [x] 10.2 端到端场景验收：闲聊直答、路由卡片切换、报告任务（数据→文档）、海报任务、执行中转向、两轮增量修改、满意下载、越权与 XSS 负向用例
- [x] 10.3 docker-compose 本地一键启动（backend + postgres + sandbox + frontend）
- [x] 10.4 部署文档：本地运行说明 + 迁服务器配置差异清单
