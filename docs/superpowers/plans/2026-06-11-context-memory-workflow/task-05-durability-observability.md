# Task 05: 持久化、取消与可观测闭环

**Risk layer:** P1

## Goal

让线程、运行和关键记忆在服务重启后可恢复，为取消、超时、副作用未知状态和性能优化提供可查询证据。

## Suggested Files

- Add: `app/agents/music_team_v3_1/runtime/checkpointer.py`
- Add: `app/agents/music_team_v3_1/runtime/events.py`
- Add: `app/agents/music_team_v3_1/runtime/metrics.py`
- Modify: `app/agents/music_team_v3_1/graph.py`
- Modify: `app/agents/music_team_v3_1/config.py`
- Modify: `app/api/v1/chat_routes.py`
- Add: `tests/integration/test_thread_recovery.py`
- Add: `tests/integration/test_run_cancellation.py`
- Add: `tests/integration/test_idempotent_side_effects.py`

## Constraints

- checkpointer 选择通过配置和工厂注入，`InMemorySaver` 只作为开发 fallback。
- 不把完整 prompt、凭证或私密工具响应写入指标。
- 取消不能撤销已经完成的外部副作用；必须报告真实状态。
- 写操作需要幂等键或等价防重复机制，未知结果不得盲重试。
- 持久化失败要显式告警，不能返回虚假的“会话已保存”。

## Steps

- [ ] 根据部署要求对 SQLite 与 Redis 做小型决策记录，选定首个实现。
- [ ] 将 graph/agents/config 改为工厂和依赖注入，测试可提供临时 checkpointer。
- [ ] 定义 run、public event、audit event 和 metric schema。
- [ ] 持久化 thread message/state、Artifact 引用和 summary 版本。
- [ ] 实现 run cancellation token 和节点边界检查。
- [ ] 为副作用工具增加 idempotency key、目标摘要和结果状态。
- [ ] 采集 context token、模型调用、节点耗时、工具成功率、memory patch 结果和错误码。
- [ ] 接入 LangSmith 时仅发送允许字段，并提供关闭开关。
- [ ] 编写重启恢复、并发线程、取消和未知副作用状态集成测试。
- [ ] 建立开发期指标报告，比较优化前后 P50/P95 和 token。

## Acceptance

```powershell
python -m pytest tests/integration/test_thread_recovery.py tests/integration/test_run_cancellation.py tests/integration/test_idempotent_side_effects.py -q
```

Expected:

- 服务重启后同一 thread 能恢复已提交消息、Artifact 和未完成任务状态。
- 不同 thread/user 不互相读取状态。
- 取消在安全节点边界生效，并产生唯一终态。
- 重复提交同一写操作不会产生重复副作用。
- 指标可输出 token、延迟、工具和记忆成功率，且无 secret/完整私密文本。

## Documentation

- 更新 `docs/current/ARCHITECTURE.md` 的持久化和可观测边界。
- 更新 `docs/current/DEVNOTES.md` 的部署要求、数据保留和故障恢复。
- 在 `docs/current/PROGRESS.md` 记录实际重启恢复与并发测试结果。

