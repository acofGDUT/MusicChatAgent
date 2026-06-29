# Task 00: 建立行为基线与评测集

**Risk layer:** P0

## Goal

把“最新要求被旧上下文覆盖、消息重复、分支行为不一致、上下文成本不可见”等问题变成可重复运行的测试和指标，
为后续重构建立不依赖主观感受的基线。

## Suggested Files

- Add: `tests/agents/test_context_priority.py`
- Add: `tests/agents/test_graph_lifecycle.py`
- Add: `tests/agents/test_message_reducer.py`
- Add: `tests/evals/context_priority_cases.json`
- Add: `tests/evals/run_context_eval.py`
- Add: `tests/api/test_local_chat_contract.py`
- Modify: `requirements.txt` or test-only dependency file if required

## Constraints

- 测试不得调用真实 QQ 音乐写接口。
- LLM 和工具通过注入的 fake/stub 替换，结果必须确定。
- 评测数据不得包含真实凭证、私密 profile 或生产对话。
- 基线失败要准确指向当前行为，不为通过而弱化断言。

## Steps

- [ ] 记录当前 Graph 节点、边、state 字段和三条分支的快照测试。
- [ ] 写多轮消息测试，证明 reducer 更新后每条消息只出现一次。
- [ ] 建立至少 20 条最新纠正冲突样例，覆盖否定、改目标、临时约束和长期偏好。
- [ ] 建立 summary/profile 冲突样例，断言当前请求优先。
- [ ] 记录每次 Agent 输入的分段 token、总 token、模型调用次数和节点耗时。
- [ ] 为 playback、music_ops、smalltalk、needs_user、failed 建立生命周期断言。
- [ ] 固化聊天 API 当前兼容字段和目标新增字段的契约测试骨架。
- [ ] 运行基线并在本 task 的 Closeout 中记录真实结果。

## Acceptance

```powershell
python -m pytest tests/agents tests/api -q
```

Expected:

- 测试可在无真实 LLM/QQ 网络时运行。
- 至少一个测试能在旧实现上复现消息重复或分支不一致风险。
- 20 条冲突样例有稳定的期望结果和机器可读报告。
- 指标报告能区分 current request、recent messages、summary、profile 和 policy token。

## Documentation

- 更新 `docs/current/PROGRESS.md`：只记录实际建立的测试和结果。
- 更新 `docs/current/DEVNOTES.md`：记录 fake 工具边界和无法自动化的真实服务验收。

