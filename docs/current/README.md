# 当前项目文档

本目录是 MusicChatAgent 的当前状态入口。它只描述已经从代码或真实检查中确认的事实，不把未来设计写成已实现能力。

## 当前状态提示

2026-06-11 本轮源码已更新结构化 Artifact 播放链路：

- 后端保留 agent 本轮 delta messages，并从 `ToolMessage`/AI message 中收集 `play_music`、`playlist_browser` artifacts。
- `/api/v1/chat/local` 返回 `data.run` 和 `data.artifacts`。
- 前端本地聊天优先渲染结构化 artifacts，旧文本 JSON 仅作为兼容 fallback。
- 本轮没有由 Codex 执行后端测试、前端构建或浏览器验收；验证状态见 [PROGRESS.md](PROGRESS.md)。

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
