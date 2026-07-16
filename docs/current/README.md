# 当前项目文档

本目录是 MusicChatAgent 的当前状态入口。它只描述已经从代码或真实检查中确认的事实，不把未来设计写成已实现能力。

## 当前状态提示

2026-07-16 已把三个实现 Spec 集成到 architecture 本地聊天主线：

- 只维护 `/chat/local`；`/chat/online` 重定向到本地聊天。
- ToolResult、Verifier/安全重试、结构化 Artifact 已合并。
- SQLite checkpoint、QQ 身份隔离、结构化偏好和权威历史恢复已启用。
- 完整后端测试、前端 service 测试、类型检查、lint 和 production build 已执行；真实外部服务 E2E 尚未执行。

详细证据见 [PROGRESS.md](PROGRESS.md)。

## 阅读顺序

1. [ARCHITECTURE.md](ARCHITECTURE.md) - 当前后端、LangGraph、记忆和前端链路如何工作。
2. [PROGRESS.md](PROGRESS.md) - 已完成事项、检查证据和未执行的验证。
3. [ROADMAP.md](ROADMAP.md) - 仍需完成的优化工作和优先级。
4. [DEVNOTES.md](DEVNOTES.md) - 开发时仍需注意的限制、风险和取舍。

## 当前设计工作

- [上下文优先级、记忆治理与工作流体验优化设计](../superpowers/specs/2026-06-11-context-memory-workflow-design.md)
- [上下文、记忆与工作流优化实施计划](../superpowers/plans/2026-06-11-context-memory-workflow-plan.md)
- [确定性动作与结构化 Artifact 优化规格](../SDD/spec/deterministic-action-and-artifact-spec.md)
- [确定性动作与结构化 Artifact 实施计划](../SDD/plan/deterministic-action-and-artifact-plan.md)

## 历史参考文档

根目录中的 `music_team_v3_1_framework.md`、`项目文档.md`、`项目跟进文档.md`、`project_review.md` 和
`music_team_v3_1_refactor_design.md` 仍有参考价值，但不是当前状态的权威来源。若这些文档与代码或本目录冲突，
以当前代码检查和本目录为准。
