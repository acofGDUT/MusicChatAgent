# 上下文、记忆与工作流优化实施计划

> Parent spec: [上下文优先级、记忆治理与工作流体验优化设计](../specs/2026-06-11-context-memory-workflow-design.md)
>
> Status: Partially implemented; remaining work tracked in docs/current/ROADMAP.md
>
> Date: 2026-06-11

## Goal

按可独立评审的纵向切片，交付“最新要求可靠生效、上下文受预算控制、记忆不会污染、Graph 生命周期一致、
前端获得结构化运行状态”的主链路。每个 task 先建立可失败证据，再修改实现；未运行的验证不得写成已通过。

## Constraints

- 保持现有 QQ 音乐认证、服务层和确定性播放/歌单 API 可用。
- 不覆盖工作区现有未提交修改，实施前逐文件检查 diff。
- `messages` 使用 `add_messages` 时只返回 delta，不返回完整旧列表。
- 不在前端或公开 trace 暴露 system prompt、profile 原文、secret 或思维链。
- 不让 profile/soul 更新失败改变已完成工具操作的真实结果。
- 副作用工具在超时和结果未知时不得自动重试。
- 复用 [确定性动作与结构化 Artifact 实施计划](../../SDD/plan/deterministic-action-and-artifact-plan.md) 的 Artifact 模型与兼容策略。
- 持久化后端通过接口注入；第一轮优化不强制引入外部基础设施。

## Delivery Phases

| Phase | Outcome | Tasks | Exit gate |
| --- | --- | --- | --- |
| 0. Baseline | 可复现当前问题和量化基线 | 00 | 基线测试能稳定失败/通过，指标可采集 |
| 1. Correctness | 最新请求和 Graph 状态正确 | 01-02 | 冲突指令、消息去重、全部分支收口通过 |
| 2. Memory | profile/summary/soul 边界稳定 | 03 | 作用域、证据、预算、失败降级通过 |
| 3. Contract/UI | API 和前端不再猜文本 | 04 | 结构化消息、Artifact、运行状态端到端通过 |
| 4. Durability | 会话可恢复且可观测 | 05 | 重启恢复、取消、指标和安全日志通过 |
| 5. Closeout | 模块与文档一致 | 06 | 全量验证、人工验收、current docs 收口 |

## Task Order

1. [Task 00: 建立行为基线与评测集](2026-06-11-context-memory-workflow/task-00-baseline-and-evals.md)
2. [Task 01: 引入 CurrentRequest 与 ContextEnvelope](2026-06-11-context-memory-workflow/task-01-context-envelope.md)
3. [Task 02: 统一 Graph 生命周期与结构化执行结果](2026-06-11-context-memory-workflow/task-02-graph-outcome.md)
4. [Task 03: 重构 profile、summary 与 soul 治理](2026-06-11-context-memory-workflow/task-03-memory-governance.md)
5. [Task 04: 升级聊天 API 与前端工作流体验](2026-06-11-context-memory-workflow/task-04-api-and-frontend.md)
6. [Task 05: 持久化、取消与可观测闭环](2026-06-11-context-memory-workflow/task-05-durability-observability.md)
7. [Task 06: 模块化、迁移与项目收口](2026-06-11-context-memory-workflow/task-06-closeout.md)

## Dependency Notes

- Task 00 是所有后续任务的证据基础。
- Task 01 和 Task 02 都修改 Graph state，建议按顺序完成，避免维护两套临时字段。
- Task 03 依赖 `ContextEnvelope` 的检索输入和预算统计。
- Task 04 依赖 Task 02 的 `ExecutionOutcome`，并与现有 Artifact SDD 的 Task 1-4 合并实施。
- Task 05 在 API 事件 schema 稳定后进行，避免持久化临时结构。
- Task 06 只做行为保持的模块拆分、旧字段移除和文档 closeout，不夹带新功能。

## Risk Layers

| Layer | Meaning | Required evidence |
| --- | --- | --- |
| P0 | 状态正确性、用户副作用、记忆污染、安全边界 | 自动化回归 + 集成测试 + 人工关键场景 |
| P1 | API 合约、前端恢复、性能与兼容 | 聚焦测试 + build/lint + E2E |
| P2 | 内部模块化和文档导航 | 静态检查 + 聚焦 smoke + diff review |

## Cross-task Validation

以下命令是目标验证集合，只有实际运行后才能记录结果：

```powershell
pytest
```

```powershell
python -m pytest tests/agents tests/api -q
```

```powershell
pnpm lint
pnpm format:check
pnpm build
pnpm test
```

前端命令在 `music-agent-chat-ui/` 执行。若项目尚无 `test` 脚本，Task 04 先建立最小组件测试基础设施，
不得把“无测试脚本”记录为通过。

## Required E2E Scenarios

1. 旧偏好与当前纠正冲突，当前纠正生效。
2. 长对话超过预算后，“第二首/刚才那个歌单”仍可解析或明确澄清。
3. 自然语言单曲播放返回结构化 `play_music` Artifact。
4. 创建/加歌/删歌的副作用结果真实、不可重复提交。
5. 请求取消或网络中断后 run 有明确终态，页面可继续发送。
6. 服务重启后已提交会话可恢复，profile 不跨用户污染。

## Review Checkpoints

### A. State contract

- 当前请求是否独立、不可被摘要覆盖。
- reducer 是否只收 delta。
- 旧字段迁移是否有兼容窗口。

### B. Memory safety

- profile 写入是否有证据、作用域和版本。
- soul 是否彻底退出运行时写路径。
- 记忆维护失败是否只降级而不篡改业务结果。

### C. API and UI

- Artifact 是否来自校验后的结构化字段。
- 公开事件是否无敏感内容和思维链。
- 取消、重试和刷新恢复是否有真实行为测试。

### D. Release closeout

- Spec、plan、实现和 `docs/current/` 是否一致。
- `PROGRESS.md` 是否只记录真实验证。
- `ROADMAP.md` 是否移除已完成项并保留剩余风险。
- Git diff 是否无凭证、history、构建产物或无关格式化。

## Rollout and Rollback

- 新上下文编译器、API 字段和持久化实现都使用配置开关分阶段启用。
- 保留旧 `/chat/local` 响应字段和旧文本 Artifact parser 一个迁移周期。
- profile 迁移前创建只读备份和版本号；新 store 异常时回退为“不注入长期画像”，不回退为共享可写文件。
- 新 checkpointer 异常时本地开发可回退 `InMemorySaver`；生产环境不得静默丢失会话后宣称恢复成功。
- 每个 phase 独立提交和验收，出现指令遵循率或工具成功率回归时停止进入下一 phase。

## Completion Definition

### 2026-07-16 integration checkpoint

The architecture branch now includes the completed ToolResult contract, result verifier with one safe retry, structured artifact state, SQLite checkpoint persistence, authenticated identity isolation, user preferences, and local chat history. Backend and frontend verification evidence is recorded in `docs/current/PROGRESS.md`.

This broader plan is intentionally not marked complete: CurrentRequest/ContextEnvelope compilation, cancellation semantics, explicit preference management UI, production auth/storage hardening, and live external-service E2E remain open in `docs/current/ROADMAP.md`.

- 七个 task 的 Acceptance 均有实际证据。
- 设计规格的验收标准逐项有测试、指标或人工验收记录。
- 当前架构文档只描述已上线机制，未完成候选仍留在 ROADMAP。
- 旧共享可写 soul 路径已停用，profile 已有用户作用域和可回滚更新。
- 最新要求冲突评测全部通过，且平均输入 token 达到目标或有经评审的偏差说明。
