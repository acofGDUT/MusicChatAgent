# 路线图

本文档记录未来工作和开放风险。它不会把新设计写成已经实现的能力。

## 当前主线：上下文、记忆、工作流、前端

上游文档：

- [设计规格](../superpowers/specs/2026-06-11-context-memory-workflow-design.md)
- [实施计划](../superpowers/plans/2026-06-11-context-memory-workflow-plan.md)
- [Artifact 规格](../SDD/spec/deterministic-action-and-artifact-spec.md)

## 优先级队列

| 优先级 | 工作项 | 状态 | 移入进展文档所需证据 |
| --- | --- | --- | --- |
| P0 | 为“最新指令优先”、reducer 行为和 graph 生命周期建立基线测试与评测 | Partially done | 既有测试曾覆盖；本轮 delta/ToolMessage 源码更新后仍需重新运行 |
| P0 | 引入带 token 预算的 `CurrentRequest` 和 `ContextEnvelope` | Proposed | 冲突评测通过，并生成上下文 token 报告 |
| P0 | 让所有 graph 分支汇合到结构化 outcome、memory policy、response 和 finalizer | Proposed | 分支生命周期和 message delta 测试通过 |
| P0 | 停止运行时 soul 变更，让 profile 更新具备作用域、证据和可回滚能力 | Proposed | 记忆治理测试通过 |
| P1 | 在保留 `reply` 兼容的同时，为聊天响应增加一等 `message/artifacts/run` 字段 | Source updated, pending verification | `/chat/local` 已返回 `run` 和 `artifacts`；需重新跑 API/浏览器验收 |
| P1 | 围绕结构化 Artifact、公开运行事件、取消和恢复重做前端聊天 session | Source updated, pending verification | `artifacts.ts`、`selectRenderableArtifacts()` 和 renderer 已接入；需重新跑前端验证 |
| P1 | 在可注入接口背后增加持久化 checkpointer/runtime event store | Proposed | 重启恢复和取消测试通过 |
| P2 | 在行为契约被测试保护后，模块化大型后端和前端文件 | Proposed | 全量回归和文档收口通过 |

## 相关既有计划

- "确定性动作与结构化 Artifact" SDD 仍然有效，应与 Task 02 和 Task 04 合并实施，而不是作为竞争协议单独推进。
- `music_team_v3_1_refactor_design.md` 包含有价值的模块拆分思路，但当前实现工作应遵循更新的 Spec-first task；只有在继续维护该文档时才同步更新。

## 延后决策

- 持久化存储选择：SQLite、Redis，或其他 checkpointer 实现。
- 保留三个领域 agent，还是收敛为一个可调用工具的 assistant agent。
- profile facts 第一阶段是否需要用户可见编辑器，还是只提供开发工具。
- 公开事件 schema 稳定后，流式 transport 使用直接 SSE 还是 LangGraph SDK。
- 一等 `artifacts` 落地后，旧文本 JSON Artifact 解析保留多久。

## 当前不做

- 重写 QQ 音乐 service/auth 内部实现。
- 把确定性 UI 动作迁移到聊天/LLM 路径。
- 构建通用 slot-filling 引擎。
- 在前端工作流面板暴露内部 prompt 或推理内容。
