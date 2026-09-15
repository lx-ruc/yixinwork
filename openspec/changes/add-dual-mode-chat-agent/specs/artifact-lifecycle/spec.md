# artifact-lifecycle 规格

## ADDED Requirements

### Requirement: 产物版本链
系统 SHALL 为每个任务维护产物版本链（v1 → v2 → …），每次增量修改生成新版本，历史版本保留且可查看。

#### Scenario: 反馈触发新版本
- **WHEN** 任务处于预览就绪状态且用户发送修改指令"第二段改短一点"
- **THEN** 系统恢复 Agent 上下文并注入反馈，生成新版本 v2，v1 保留可查看

#### Scenario: 下载历史版本
- **WHEN** 用户在版本链中选择 v1 并请求下载
- **THEN** 系统提供 v1 的下载链接

### Requirement: 修改指令跟随最近产物
系统 SHALL 将预览就绪后的修改指令应用于该会话中最近产出的产物。

#### Scenario: 多产物会话中修改最近产物
- **WHEN** 会话中先后产出了 PPT 和数据表格，用户发送"标题字号调大"
- **THEN** 该指令应用于最近产物（数据表格），不影响 PPT

### Requirement: 类型混合预览
系统 SHALL 按产物类型提供预览：Markdown 文档直接 web 渲染；HTML 海报/幻灯片按设计原样渲染；数据结果以 HTML 表格预览。

#### Scenario: 文档产物预览
- **WHEN** 用户打开一个 Markdown 报告产物
- **THEN** 前端渲染为排版后的文档视图

#### Scenario: 海报产物预览
- **WHEN** 用户打开一个 HTML 海报产物
- **THEN** 前端按 HTML 设计原样渲染图像

### Requirement: 预览安全隔离
系统 SHALL 将 Agent 生成的 HTML 预览内容置于 sandbox iframe 中渲染，施加 CSP，禁止其访问主站凭证与存储。

#### Scenario: 恶意脚本不执行
- **WHEN** 预览内容包含 `<script>alert(1)</script>`
- **THEN** 该脚本在 sandbox iframe 中不执行，主站会话与数据不受影响

### Requirement: 满意确认与下载
系统 SHALL 在用户确认满意后，将中间格式转换为目标格式（md→docx、数据→xlsx、HTML→png、幻灯片→pptx/pdf），并通过带过期时间的签名 URL 提供下载。

#### Scenario: 满意后下载最终格式
- **WHEN** 用户对 v2 点击"满意，下载"并选择 docx
- **THEN** 系统转换生成 docx 文件并返回签名下载 URL，任务进入已交付状态

#### Scenario: 签名 URL 过期
- **WHEN** 用户使用已过期的下载 URL
- **THEN** 系统拒绝该请求并提示重新获取链接
