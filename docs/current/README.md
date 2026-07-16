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

## 已实现规格

- [Phase 1：ToolResult 统一工具结果协议](../../reference/spec/01-tool-result-spec.md)
- [Phase 2：Result Verifier、安全重试与 Artifact](../../reference/spec/02-result-verifier-retry-artifact-state-spec.md)
- [Phase 3：SQLite、用户隔离、偏好与历史恢复](../../reference/spec/03-sqlite-user-memory-history-spec.md)

仓库已移除旧 Agent 版本、失效启动入口和历史框架文档。当前实现以
`app/agents/music_team_v3_1/`、本目录以及上述三个 Spec 为准。
