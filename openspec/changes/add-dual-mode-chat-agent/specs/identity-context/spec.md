# identity-context 规格

> 鉴权（注册/登录/会话凭证）由宿主系统负责，本模块不实现用户体系。

## ADDED Requirements

### Requirement: 宿主注入的信任身份
系统 SHALL 从可信的 `X-User-Id` 请求头解析当前用户身份并用于所有数据操作；生产模式（`REQUIRE_USER_HEADER=true`）下缺失该头 MUST 返回 401，开发模式可回退到配置的默认用户。

#### Scenario: 身份头正常解析
- **WHEN** 请求携带 `X-User-Id: user-42`
- **THEN** 本次请求内的所有数据操作均以 user-42 为归属

#### Scenario: 生产模式缺失身份头
- **WHEN** 生产模式下请求未携带 X-User-Id
- **THEN** 系统返回 401，且不执行任何业务逻辑

#### Scenario: 开发模式回退默认用户
- **WHEN** 开发模式下请求未携带 X-User-Id
- **THEN** 系统使用配置的开发默认用户继续处理

### Requirement: 数据按用户隔离
系统 SHALL 将会话、消息、任务、产物、版本、用量等全部业务数据以 user_id 隔离；产物文件路径 MUST 按用户分域（`/artifacts/{user_id}/{task_id}/...`）。

#### Scenario: 用户无法访问他人数据
- **WHEN** 用户 A 尝试通过猜测 ID 访问用户 B 的会话或产物
- **THEN** 系统按不存在处理（404），不泄露他人数据

#### Scenario: 文件存储按用户分域
- **WHEN** 用户 A 的任务产生产物文件
- **THEN** 文件存储在 user_id 为 A 的路径分域下

### Requirement: 预览与下载仅限所有者
系统 SHALL 确保产物预览与签名下载 URL 仅对产物所有者有效。

#### Scenario: 签名 URL 不跨用户
- **WHEN** 用户 B 持有用户 A 产物的签名 URL 发起下载
- **THEN** 系统拒绝该请求
