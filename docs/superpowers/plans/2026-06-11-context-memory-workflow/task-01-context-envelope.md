# Task 01: 引入 CurrentRequest 与 ContextEnvelope

**Risk layer:** P0

## Goal

让当前用户请求成为独立、最高优先的运行时输入，并用分段 token 预算装配相关上下文，消除整篇 profile 截断和
完整历史无界注入。

## Suggested Files

- Modify: `app/agents/music_team_v3_1/state.py`
- Add: `app/agents/music_team_v3_1/context/models.py`
- Add: `app/agents/music_team_v3_1/context/compiler.py`
- Add: `app/agents/music_team_v3_1/context/budget.py`
- Modify: `app/agents/music_team_v3_1/utils.py`
- Modify: `app/agents/music_team_v3_1/nodes.py`
- Modify: `app/agents/music_team_v3_1/config.py`
- Test: `tests/agents/test_context_priority.py`
- Test: `tests/agents/test_context_budget.py`

## Constraints

- 当前用户消息保持为 Agent 输入最后一条 `HumanMessage`。
- 不用新的通用 slots 重复工具 schema。
- token 预算必须按目标模型计数，不使用字符长度冒充 token。
- 超限时先裁剪低相关长期信息，不丢弃当前请求和待确认约束。
- 迁移期允许保留旧 `memory/control/task`，但新执行节点只读取明确合同字段。

## Steps

- [ ] 先写失败测试：profile 与当前请求冲突时旧实现选择错误或输入无边界。
- [ ] 定义 `CurrentRequest`、`ContextEnvelope` 和分段 token usage 模型。
- [ ] 从最新 `HumanMessage` 生成 request，分配稳定 `turn_id`。
- [ ] 实现 recent-message 完整轮次窗口和结构化最近实体输入。
- [ ] 实现 profile facts 检索接口占位；旧 Markdown 仅通过适配器提供候选 facts。
- [ ] 实现可配置预算和确定的降级顺序。
- [ ] 调整 Agent 输入构造顺序，删除 profile/soul 固定 `[:2200]` 截断。
- [ ] 为过长当前请求、空请求、指代不明和预算耗尽补失败路径。
- [ ] 记录 context 指标，不记录原始私密文本。

## Acceptance

```powershell
python -m pytest tests/agents/test_context_priority.py tests/agents/test_context_budget.py -q
```

Expected:

- 20 条最新纠正冲突样例全部使用当前请求。
- Agent 输入最后一条消息与 `state.request.text` 一致。
- 每个 segment 和总输入都不超过配置预算。
- profile 超长或检索失败时，当前请求仍完整可用。
- 旧摘要只作为背景，不会恢复已被用户纠正的目标。

## Documentation

- 实施完成后更新 `docs/current/ARCHITECTURE.md` 的上下文装配章节。
- 在 `docs/current/DEVNOTES.md` 记录预算默认值和 tokenizer 限制。

