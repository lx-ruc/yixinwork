# code-sandbox 规格

## ADDED Requirements

### Requirement: 模型代码沙箱隔离执行
系统 SHALL 将 Agent 现场生成的代码放入独立 Docker 容器执行，禁止在后端进程内直接运行模型生成的代码。

#### Scenario: 数据处理脚本进沙箱
- **WHEN** Agent 决定编写并运行一段 pandas 脚本清洗数据
- **THEN** 该脚本在独立 Docker 容器中执行，结果回传给 Agent

### Requirement: 沙箱资源与网络约束
系统 SHALL 对沙箱容器施加：无网络访问、CPU/内存限额、执行时长上限、非 root 用户运行、产出文件大小限额。

#### Scenario: 超时任务被终止
- **WHEN** 沙箱内代码执行超过时长上限
- **THEN** 容器被终止，Agent 收到超时错误并可决定调整方案

#### Scenario: 沙箱无法访问网络
- **WHEN** 沙箱内代码尝试发起外部 HTTP 请求
- **THEN** 请求被阻断失败

### Requirement: 沙箱生命周期管理
系统 SHALL 为每次代码执行创建独立容器并在执行结束后销毁，容器间不共享状态。

#### Scenario: 任务结束容器销毁
- **WHEN** 一次代码执行完成（成功或失败）
- **THEN** 对应容器被销毁，不留残留

### Requirement: 可信工具进程内执行
系统 SHALL 将平台自身的工具函数（文件生成、格式转换、渲染）与模型生成代码区分，前者在后端进程内直接执行。

#### Scenario: 文档转换不进沙箱
- **WHEN** Agent 调用平台工具将 Markdown 转换为 docx
- **THEN** 转换在后端进程内完成，不创建沙箱容器
