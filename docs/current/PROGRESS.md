# 项目进展

本文档只记录当前代码已经实现并验证的能力。未来工作见 [ROADMAP.md](ROADMAP.md)。

## 2026-07-16：面试项目分支基线

当前主链路是本地聊天：

- 后端通过 FastAPI 提供 `/api/v1/chat/local` 和历史接口。
- 前端 `/chat/online` 只重定向到 `/chat/local`，没有在线 LangGraph SDK runtime。
- 当前唯一 Agent 实现位于 `app/agents/music_team_v3_1/`。
- 旧 Agent、失效 CLI/LangGraph 配置、重复框架文档和历史任务过程文档已从面试分支移除。

## 已完成的三个阶段

### Phase 1：ToolResult

- 核心 Tool 统一返回可校验的 ToolResult JSON。
- 工具成功/失败由结构化 `ok/code` 判断，不扫描 LLM 自然语言关键词。
- `WRITE_UNCERTAIN` 不会被包装成成功，也不允许自动重试。
- 当前轮最后一个核心工具结果保存到 `extensions.last_tool_result`。

### Phase 2：Result Verifier 与 Artifact

- music ops 和 playback 执行结果统一经过确定性 `result_verifier`。
- 只读、明确可重试的失败最多重试一次；任何包含写工具的 attempt 都不自动重试。
- 播放器和歌单 Artifact 由 Pydantic Schema 校验并规范化。
- `last_search_results` 支持后续对“第 N 首”的结构化引用。
- API 返回稳定的 `run`、`artifacts`、`reply`、`trace` 和安全错误结构。

### Phase 3：SQLite 与用户记忆

- FastAPI lifespan 管理 AsyncSqliteSaver 和偏好仓库连接。
- QQ Credential 派生服务端用户身份，用户和线程组合生成隔离 checkpoint key。
- 用户明确表达的音乐偏好通过结构化 patch 合并并按用户存储。
- History 从 checkpoint 完整消息恢复，不依赖 JSONL preview。
- Graph state 保留完整 messages，summary 只压缩发送给模型的 runtime context。

## 验证证据

后端：

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

结果：`237 passed`。

前端：

```powershell
cd music-agent-chat-ui
corepack pnpm@10.5.1 exec playwright test tests/localChatApi.spec.ts --reporter=line --workers=1
corepack pnpm@10.5.1 exec tsc --noEmit
corepack pnpm@10.5.1 exec prettier --check src/features/chat-local tests/localChatApi.spec.ts
corepack pnpm@10.5.1 run lint
corepack pnpm@10.5.1 run build
```

结果：Playwright `3 passed`；TypeScript、Prettier、lint 和 production build 通过。lint 保留既有 warning，但没有 error。

## 尚未验证的外部边界

- 没有使用真实 QQ Credential 执行创建歌单、加歌和播放的完整浏览器 E2E。
- 没有使用真实外部 LLM 服务执行完整聊天 E2E。
- 没有验证多进程、多实例、数据库加密和生产级身份系统。
