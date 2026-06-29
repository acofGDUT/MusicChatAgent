# Task 03: 重构 Profile、Summary 与 Soul 治理

**Risk layer:** P0

## Goal

把共享 Markdown 记忆改造成有作用域、有证据、可检索、可回滚的长期事实；让摘要可靠压缩线程历史，
并彻底停止普通对话对 soul 的运行时改写。

## Suggested Files

- Add: `app/agents/music_team_v3_1/memory/models.py`
- Add: `app/agents/music_team_v3_1/memory/store.py`
- Add: `app/agents/music_team_v3_1/memory/profile.py`
- Add: `app/agents/music_team_v3_1/memory/summary.py`
- Add: `app/agents/music_team_v3_1/memory/policy.py`
- Add: `app/agents/music_team_v3_1/memory/migrate.py`
- Modify: `app/agents/music_team_v3_1/nodes.py`
- Modify: `app/agents/music_team_v3_1/config.py`
- Modify: `app/agents/memory/user_profile.md`
- Modify: `app/agents/memory/soul.md`
- Test: `tests/agents/memory/`

## Constraints

- 迁移前保留旧 profile/soul 的只读备份或版本标识。
- profile key 不包含明文 credential；至少按用户/account 作用域隔离。
- LLM 只能提出 profile patch，不能直接覆盖存储文件。
- 临时请求默认不进入长期 profile。
- soul/policy 运行时只读，策略变更必须经人工评审。
- 记忆更新失败不得让成功工具操作变成失败。

## Steps

- [ ] 写 profile 跨线程/跨用户污染、临时偏好误写和纠错失效测试。
- [ ] 定义 `ProfileFact`、`ProfilePatch`、`SummaryRecord` 和 `MemoryEvent`。
- [ ] 实现基于 user/thread key 的 store 接口、原子写入和版本检查。
- [ ] 将旧 Markdown profile 解析为带低/高置信度的迁移候选，人工不可确认项不自动提升。
- [ ] 实现显式长期偏好、稳定实体和纠正事件的字段级 patch 校验。
- [ ] 实现与当前请求相关的 Top-K facts 检索和 token 限额。
- [ ] 将 summary 改为增量更新，保留未完成任务、待确认项和最近 Artifact 引用。
- [ ] 移除运行时 soul 写路径和自动调优开关，加载版本化短 policy。
- [ ] 为 memory LLM 增加超时和失败降级，记录安全审计事件。
- [ ] 提供开发期 profile 查看、失效和重建命令，不直接手改生产 store。

## Acceptance

```powershell
python -m pytest tests/agents/memory -q
```

Expected:

- 不同 user key 的 profile 事实完全隔离。
- “今天不要某歌手”不写长期事实，“以后不要推荐”形成有证据的事实。
- 用户纠正后旧 fact 失效，不与新 fact 同时注入。
- profile store 冲突或 LLM 超时只产生 memory failure event。
- soul 文件/策略版本在任意聊天运行后保持不变。
- 超长 profile 只检索相关 Top-K，注入 token 不超过预算。

## Documentation

- 更新 `docs/current/ARCHITECTURE.md` 的记忆分层和作用域。
- 更新 `docs/current/DEVNOTES.md` 的迁移、回滚和并发限制。
- 在 `docs/current/PROGRESS.md` 记录真实迁移数量和未确认事实数量。

