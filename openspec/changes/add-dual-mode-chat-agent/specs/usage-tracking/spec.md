# usage-tracking 规格

## ADDED Requirements

### Requirement: LLM 调用用量记录
系统 SHALL 记录每次 LLM 调用的用量流水：用户、模型、输入/输出 tokens、耗时、所属会话与任务（若在工作模式下）。

#### Scenario: 直答调用被记录
- **WHEN** 用户在普通对话模式发起一次直答
- **THEN** 系统记录一条包含用户、模型、tokens、耗时的用量流水

#### Scenario: Agent 循环内调用被记录
- **WHEN** Agent 工具循环中发生一次 LLM 调用
- **THEN** 用量流水关联到对应任务，可按任务聚合

### Requirement: 任务执行记录
系统 SHALL 记录每个任务的执行信息：总时长、工具调用次数、沙箱执行次数，用于成本分析与异常监控。

#### Scenario: 任务完成生成执行记录
- **WHEN** 一个工作模式任务进入预览就绪状态
- **THEN** 系统记录该任务的时长与工具调用统计

### Requirement: 用量数据可查询
系统 SHALL 提供按用户与时间范围查询用量汇总的内部接口（v1 只记不扣费，为将来配额/计费提供数据基础）。

#### Scenario: 查询用户用量汇总
- **WHEN** 以用户 ID 与时间范围查询用量
- **THEN** 返回该时间范围内的 tokens 与任务数汇总
