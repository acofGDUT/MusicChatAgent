# 路线图

本文档只记录仍未完成的工作。已完成结果和验证证据见 [PROGRESS.md](PROGRESS.md)。

## 当前基线

2026-07-16 已完成三个实现 Spec，并集成到 architecture 本地聊天主线：

- [ToolResult Spec](../../reference/spec/01-tool-result-spec.md)
- [Result Verifier、一次安全重试与 Artifact 状态 Spec](../../reference/spec/02-result-verifier-retry-artifact-state-spec.md)
- [SQLite、身份隔离、结构化偏好与历史恢复 Spec](../../reference/spec/03-sqlite-user-memory-history-spec.md)

项目当前只维护 `/chat/local`。`/chat/online` 是重定向入口，不把恢复 online chat 作为当前路线。

## 优先级队列

| 优先级 | 工作项 | 当前状态 | 完成证据 |
| --- | --- | --- | --- |
| P0 | 真实 QQ Music + 当前模型供应商浏览器 E2E | 待执行 | 登录、普通聊天、搜索、播放、创建/加歌/删歌和重启恢复均有真实证据 |
| P0 | 引入显式 `CurrentRequest` 和 token 预算 `ContextEnvelope` | Proposed | 最新纠正评测通过，并记录各 segment token 与总预算 |
| P0 | 将最小 `task/control/extensions` 进一步收敛为公开 `ExecutionOutcome` | Partially done | 所有终态、错误码和 Artifact 不再依赖兼容字段 |
| P1 | 长期偏好查看、纠错和失效工具 | Proposed | 用户可以查看和撤销结构化偏好，并有版本/审计测试 |
| P1 | 运行取消、run_id、幂等键和恢复状态 | Proposed | 取消与副作用未知状态 E2E 通过 |
| P1 | 生产部署存储与认证设计 | Proposed | 多账号 Credential、数据库加密、备份和多实例并发方案获批准 |
| P2 | 拆分 `app/api/v1/endpoints.py` 和大型 Agent 节点模块 | Proposed | 行为保持回归、导入兼容和文档更新通过 |
| P2 | 迁移 `next lint` 到 ESLint CLI 并清理现有 warnings | Proposed | lint 无 deprecated 提示且 warnings 有明确处置 |

## 仍然有效的设计上游

- [上下文优先级、记忆治理与工作流体验优化设计](../superpowers/specs/2026-06-11-context-memory-workflow-design.md)
- [上下文、记忆与工作流优化实施计划](../superpowers/plans/2026-06-11-context-memory-workflow-plan.md)
- [确定性动作与结构化 Artifact 规格](../SDD/spec/deterministic-action-and-artifact-spec.md)

这些文档中已经被三个 Spec 完成的 SQLite、结构化偏好、message delta 和 Artifact 第一切片，应以当前代码与 [ARCHITECTURE.md](ARCHITECTURE.md) 为准；尚未完成的 ContextEnvelope、取消、公开运行事件和生产部署部分继续有效。

## 当前不做

- 恢复两套前端聊天模式。
- 把点击播放、暂停、拖动进度或歌单翻页改成 LLM 请求。
- 静默回退到内存 checkpointer 后仍宣称会话可恢复。
- 在前端或公开 trace 展示 system prompt、偏好原文、凭证或思维链。
