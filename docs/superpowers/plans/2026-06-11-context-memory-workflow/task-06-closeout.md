# Task 06: 模块化、迁移与项目收口

**Risk layer:** P2

## Goal

在行为合同稳定后完成模块拆分、旧兼容路径清理、真实环境验收和项目文档收口，使代码、Spec、Plan 与
`docs/current/` 描述一致。

## Suggested Files

- Refactor: `app/agents/music_team_v3_1/nodes.py`
- Refactor: `app/agents/music_team_v3_1/prompts.py`
- Refactor: `app/agents/music_team_v3_1/utils.py`
- Refactor: `app/api/v1/endpoints.py`
- Refactor: `music-agent-chat-ui/src/features/chat-local/`
- Modify: `README.md`
- Modify: `AGENTS.md`
- Modify: `docs/current/*.md`
- Modify: parent spec and plan status/closeout sections

## Constraints

- 模块拆分不改变已通过的用户行为和公开 API。
- 不为追求文件数量机械拆分；按上下文、执行、记忆、运行时和传输边界组织。
- 旧字段和 parser 只在兼容窗口和迁移证据完成后删除。
- 不提交凭证、`history.jsonl`、profile 备份、构建产物或真实用户评测数据。

## Steps

- [ ] 在全套回归保护下拆分 context、nodes、memory、runtime、API schema 与前端 transport。
- [ ] 删除已废弃的 runtime soul autotune、固定 profile 截断和关键词失败检测。
- [ ] 清理旧 intent/slots 字段或标记明确兼容截止版本。
- [ ] 清理在线/本地聊天的重复或虚假文档描述。
- [ ] 运行后端完整测试和前端 test/lint/format/build。
- [ ] 在真实 QQ 测试账号执行六类 E2E，写入脱敏结果。
- [ ] 比较优化前后指令遵循、token、延迟和工具成功率。
- [ ] 按证据更新 `ARCHITECTURE/PROGRESS/ROADMAP/DEVNOTES`。
- [ ] 将 spec 标记为 Implemented 或明确 Partial，并为剩余风险创建新 roadmap 项。
- [ ] 检查 Git diff、链接、文档状态和未跟踪文件。

## Acceptance

```powershell
pytest
```

```powershell
pnpm test
pnpm lint
pnpm format:check
pnpm build
```

```powershell
git diff --check
git status --short
```

Expected:

- 自动化验证全部有真实结果，失败项有明确原因和剩余风险。
- 六类 E2E 完成或逐项标记未执行，不用 smoke test 代替真实副作用验收。
- 当前文档只描述已实现机制，ROADMAP 不重复已完成事项。
- Spec、Plan 和 task closeout 状态一致。
- 变更中没有 secret、真实记忆数据、缓存或无关格式化。

## Documentation

- 必须同步全部 `docs/current/` 文件。
- 必须更新根 README 和 AGENTS 中已经变化的启动、架构和前端入口。
- 旧设计文档保留历史价值时加状态说明，不改写为“当前架构”。
