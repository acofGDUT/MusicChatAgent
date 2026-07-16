# 项目进展

本文档记录已经完成的工作，以及支撑这些结论的证据。计划中的工作应写在 [ROADMAP.md](ROADMAP.md)。

## 2026-07-16：architecture 本地聊天主线与三个 Spec 完成集成

状态：实现与离线自动化验收完成；真实 QQ Music + 外部 LLM 浏览器 E2E 尚未执行。

集成边界：

- 以 `codex/architecture-improvements` 为基线，保留单一 `/chat/local` 模式；`/chat/online` 继续重定向，不恢复已删除的 LangGraph SDK providers 和代理 API。
- 合入 ToolResult、Result Verifier/一次安全重试/Artifact 状态，以及 SQLite checkpoint/身份隔离/结构化偏好/权威历史三个 Spec。
- Artifact 统一由 `app.schemas` 严格校验，`app.models.chat_artifacts` 保留为兼容导出层。
- Agent 和 Verifier 遵守 message delta 合同，同时保留 ToolMessage 供 Artifact 收集。
- `OPENAI_MODEL` 与 `MUSIC_AGENT_MODEL` 均从环境变量读取。

关键结果：

- FastAPI lifespan 管理 SQLite checkpointer 与偏好仓库的两个独立连接。
- QQ Credential 派生服务端身份，checkpoint key 不暴露 QQ 标识，客户端不能提交 `user_id`。
- 历史恢复改为读取 checkpoint 完整消息，并过滤内部 Agent/Tool 消息。
- ToolResult 驱动成功/失败判断；副作用结果未知不自动重试，安全查询最多重试一次。
- `/chat/local` 同时返回稳定 `run`、结构化 `artifacts`、兼容 `reply/trace` 和安全 JSON 错误。
- 前端优先消费结构化 Artifact，并显示后端非 2xx 错误详情。

实际验证：

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

结果：237 passed。

```powershell
cd music-agent-chat-ui
corepack pnpm@10.5.1 exec playwright test tests/localChatApi.spec.ts --reporter=line --workers=1
corepack pnpm@10.5.1 exec tsc --noEmit
corepack pnpm@10.5.1 exec prettier --check src/features/chat-local tests/localChatApi.spec.ts
corepack pnpm@10.5.1 run lint
corepack pnpm@10.5.1 run build
```

结果：Playwright 3 passed；TypeScript 和 Prettier 通过；lint 0 error（保留既有 warnings）；Next production build 成功并生成 11 个静态页面。

未完成证据边界：

- 没有使用真实 QQ Credential 执行创建歌单、加歌、播放等副作用 E2E。
- 没有执行真实 DeepSeek/OpenAI 兼容模型的浏览器完整聊天 E2E。
- 没有验证多进程、多实例或加密数据库部署。

## 2026-06-11：结构化 Artifact 链路源码更新（待运行时验证）

状态：源码已更新；用户要求由用户自行测试，因此本轮没有运行后端测试、前端构建或浏览器验收。

已更新的运行时链路：

- `app/agents/music_team_v3_1/utils.py`
  - 新增 agent delta 提取逻辑，用于从 LangChain agent 返回值中剥离历史输入，只保留本轮新消息。
  - delta 保留 `ToolMessage`，避免播放工具结果在后续回复节点前丢失。
- `app/agents/music_team_v3_1/nodes.py`
  - `music_ops_subgraph_node`、`playback_subgraph_node`、`chat_replier_node` 改为返回本轮 delta messages，而不是旧历史消息加新 AI 的完整列表。
- `app/agents/music_team_v3_1/artifacts.py`
  - `ArtifactCollector` 支持从 LangChain message、message-like dict、content block、fenced JSON 和嵌入式 JSON 中收集 artifact。
  - collector 仍通过 Pydantic artifact 模型校验并去重。
- `app/api/v1/endpoints.py`
  - `/chat/local` 在 graph updates 消费过程中从每个节点输出的 `messages` 收集 artifacts。
  - 成功响应包含 `data.run.status="succeeded"` 和 `data.artifacts`。
  - 空消息和 Graph 异常返回稳定 JSON：`data.run.status="failed"`、`data.artifacts=[]`，Graph 异常使用 502。
  - 修复 FastAPI `HTTPException` 导入来源。
- `app/tools/song_tools.py`
  - `play_music_tool` 使用 `PlayMusicArtifact.model_dump_json()` 输出结构化播放 artifact。
- `music-agent-chat-ui/src/features/chat-local/`
  - 新增共享 artifact 类型和类型守卫。
  - `sendLocalChatMessage()` 读取后端 `data.artifacts`。
  - `ChatMsg` 保存可选 `artifacts`。
  - `AssistantMessageRenderer` 优先渲染结构化 artifacts；旧文本 JSON 仅作为兼容 fallback。
  - `selectRenderableArtifacts()` 将 legacy `play_music` payload 规范化为统一结构，避免重复渲染。

本轮仅执行的检查：

```powershell
git diff --check -- <本轮源码文件>
```

结果：未发现 whitespace/error marker 问题；未执行运行时测试。

待用户验证：

- 浏览器普通聊天不再出现 `Failed to fetch`。
- 后端异常在浏览器 Origin 下仍返回可读 JSON 和 CORS 头。
- 自然语言触发播放时，`play_music_tool` 产物能通过 `ToolMessage` 出现在 `/chat/local` 的 `data.artifacts`。
- 前端优先渲染 `data.artifacts`，旧文本 JSON 消息仍兼容。
- UI 点击歌单内播放仍走 `/api/v1/song/play-url`，不走 `/chat/local`。

## 2026-06-11：聊天运行时合同第一执行切片

状态：已实施并通过验证。

验证命令与结果：

```powershell
cd D:\MusicChatAgent
.venv\Scripts\python.exe -m pytest tests/api tests/agents -v
```

结果：38 passed, 1 skipped（`memory_sync_node` 原地修改 messages 的风险测试被 skip，延后处理）。

```powershell
cd music-agent-chat-ui
npx next lint
npx next build
```

结果：lint 0 error（仅预先存在的 warnings），build 成功，11 页面全部生成。

已完成任务：

### Task 01: 稳定模型配置与聊天错误响应

- `OPENAI_MODEL` 环境变量已可配置 llm0 模型名，`MUSIC_AGENT_MODEL` 保留给主音乐 Agent。
- `/chat/local` 空消息返回 400 + `data.run.status="failed"` + `data.artifacts=[]`。
- Graph 异常返回 502 + 稳定错误结构，不泄露 traceback 或 secret。
- 错误日志使用 `logger.error` + 结构化字段（thread_id、error_type），不输出堆栈。
- 测试文件：`tests/api/test_local_chat_error_contract.py`（8 tests）。

### Task 02: 定义后端 Artifact 模型与收集器

- 新增 `app/models/chat_artifacts.py`：Pydantic 模型 `PlayMusicArtifact` 和 `PlaylistBrowserArtifact`，未知 type 被拒绝。
- 新增 `app/agents/music_team_v3_1/artifacts.py`：`ArtifactCollector` 支持 dedup、raw/JSON/fenced 解析。
- `app/tools/song_tools.py` 已改为使用 `PlayMusicArtifact.model_dump_json()` 序列化。
- 测试文件：`tests/agents/test_chat_artifacts.py`（18 tests）。

### Task 03: 将 Artifacts 和最小 Run 状态接入 /chat/local

- 成功响应包含 `data.run.status="succeeded"` + `data.artifacts=[...]`。
- 错误响应包含 `data.run.status="failed"` + `data.artifacts=[]`。
- 旧 `reply` 和 `trace` 字段保留。
- `ArtifactCollector.collect_from_text()` 支持扫描嵌入式 JSON（fenced block、inline object）。
- 测试文件：`tests/api/test_local_chat_artifacts_contract.py`（5 tests）。

### Task 04: 修复 Graph message delta 纪律

- `music_ops_subgraph_node`、`playback_subgraph_node`、`chat_replier_node` 改为返回 `[ai_msg]`（delta-only）。
- 移除三个节点中未使用的 `messages` 变量。
- `memory_sync_node` 仍存在 `state["messages"]` 原地修改，已记录为延后风险。
- 测试文件：`tests/agents/test_message_delta.py`（8 tests, 1 skipped）。

### Task 05: 前端优先消费结构化 Artifacts

- 新增 `music-agent-chat-ui/src/features/chat-local/artifacts.ts`：共享 `ChatArtifact` 类型 + 类型守卫。
- `ChatMsg` 增加可选 `artifacts` 字段，`LocalChatResp` 增加 `data.artifacts` 和 `data.run`。
- `sendLocalChatMessage` 返回 `artifacts`。
- `AssistantMessageRenderer` 优先从结构化 artifacts 渲染，旧文本 parser 作为 fallback。
- 前端 lint 0 error，build 成功。

## 2026-06-11：Spec-first 文档基线

状态：已完成文档整理；没有修改业务实现。

已检查证据：

- 使用 `rg --files` 检查仓库结构。
- 使用 `git status --short` 检查已有脏工作区和未跟踪文件状态。
- `app/agents/music_team_v3_1/state.py`, `graph.py`, `nodes.py`, `utils.py`, `prompts.py`, `agents.py`, and `config.py`.
- `app/api/v1/endpoints.py` 中的聊天、历史和播放器路由。
- `music-agent-chat-ui/src/features/chat-local/` 和 `music-agent-chat-ui/src/app/chat/`。
- `docs/SDD/` 下的既有文档、根目录中文文档、审查文档和重构设计文档。
- `app/agents/memory/user_profile.md` 和 `app/agents/memory/soul.md`，用于确认当前记忆文件形态。

已创建文档：

- [上下文/记忆/工作流设计规格](../superpowers/specs/2026-06-11-context-memory-workflow-design.md)
- [上下文/记忆/工作流实施计划](../superpowers/plans/2026-06-11-context-memory-workflow-plan.md)
- `docs/superpowers/plans/2026-06-11-context-memory-workflow/` 下的 task 00-06
- 本目录中的当前状态文档

验证结果：

- 文档基于代码检查创建。
- 没有运行后端测试。
- 没有运行前端 lint/build/tests。
- 本次文档整理没有修改应用代码。

剩余边界：

- 新 Spec 和 Plan 仍是 Draft/Proposed，描述的是目标工作，不是已完成实现。
- 当前应用仍存在 [ARCHITECTURE.md](ARCHITECTURE.md) 和 [DEVNOTES.md](DEVNOTES.md) 中记录的限制。

## 通过文件检查确认的既有实现能力

以下能力在 2026-06-11 文档整理前已经存在。本次通过阅读文件确认，没有通过运行时执行确认：

- `main.py` 中的 FastAPI 应用入口和 `/api/v1` router。
- `app.agents.music_team_v3_1` 包，包含 StateGraph、agents、prompts、state、nodes、config 和 utilities。
- 本地聊天 REST 路由 `/api/v1/chat/local` 和预览历史路由 `/api/v1/chat/local/history`。
- 歌曲播放 URL 和歌单分页的前端播放器直连 API。
- Next.js 本地聊天页面和自定义播放/歌单 Artifact 组件。
- 已有的“确定性动作与结构化 Artifact”方向 SDD。
