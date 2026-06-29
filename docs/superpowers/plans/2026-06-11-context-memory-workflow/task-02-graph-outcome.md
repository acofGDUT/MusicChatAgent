# Task 02: 统一 Graph 生命周期与结构化执行结果

**Risk layer:** P0

## Goal

修复消息 reducer 使用方式，使所有自然语言分支汇合到统一的 outcome、memory、response 和 finalizer，
并以结构化状态代替中文关键词失败检测。

## Suggested Files

- Modify: `app/agents/music_team_v3_1/state.py`
- Modify: `app/agents/music_team_v3_1/graph.py`
- Modify: `app/agents/music_team_v3_1/nodes.py`
- Modify: `app/agents/music_team_v3_1/agents.py`
- Modify: `app/agents/music_team_v3_1/prompts.py`
- Add: `app/agents/music_team_v3_1/outcomes.py`
- Test: `tests/agents/test_graph_lifecycle.py`
- Test: `tests/agents/test_message_reducer.py`
- Test: `tests/agents/test_execution_outcome.py`

## Constraints

- `messages` 更新只返回新增消息 delta。
- 播放成功 JSON/Artifact 不得被 ChatReplier 改写。
- 所有分支只能产生一个明确终态。
- 失败状态来自工具/模型结构化结果和异常映射，不依赖“失败、报错”等文本关键词。
- 副作用执行结果与自然语言回复分离。

## Steps

- [ ] 写失败测试复现旧消息列表回传导致的重复风险。
- [ ] 定义 `ExecutionOutcome`、稳定错误码和 side-effect 记录。
- [ ] 调整每个节点只返回自身修改字段，禁止直接修改输入 state。
- [ ] 让 smalltalk、music_ops、playback、needs_user 和 failed 全部进入统一汇合节点。
- [ ] 将执行 Agent 的结果适配为 outcome；工具异常映射为稳定错误码。
- [ ] 接入现有 Artifact SDD 的 collector 和白名单校验。
- [ ] 让 response composer 只消费 outcome，不重新推断业务结果。
- [ ] finalizer 校验 run 终态、清理临时控制字段并写公开阶段事件。
- [ ] 比较保留多 Agent 与单 assistant_agent 的评测；未达到门槛时保持分域 Agent。

## Acceptance

```powershell
python -m pytest tests/agents/test_graph_lifecycle.py tests/agents/test_message_reducer.py tests/agents/test_execution_outcome.py -q
```

Expected:

- 连续多轮运行后消息顺序正确且无重复倍增。
- 五类分支都经过统一汇合和 finalizer。
- 每个 run 只有一个 `succeeded/needs_user/failed/cancelled` 终态。
- Artifact 独立保存在 state，最终文本为空或变化时仍不会丢失。
- 工具返回包含“失败”字样但状态为成功时不会误判，反之亦然。

## Documentation

- 更新 `docs/current/ARCHITECTURE.md` 的 Graph 图和状态模型。
- 将已完成的旧 `intent_parser/slots` 清理工作从 `docs/current/ROADMAP.md` 移到 `PROGRESS.md`。
