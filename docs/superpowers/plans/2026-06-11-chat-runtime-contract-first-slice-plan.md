# 本地聊天运行时合同第一执行切片实施计划

> Parent spec: [本地聊天运行时合同第一执行切片设计](../specs/2026-06-11-chat-runtime-contract-first-slice-design.md)
>
> Status: Completed and verified on 2026-07-16
>
> Date: 2026-06-11

## Goal

交付一个可马上执行、可独立 review 的第一切片：本地聊天请求稳定、模型配置不硬编码、错误响应可读、
Artifact 一等返回、Graph 消息 reducer 风险被测试覆盖，前端优先消费结构化数据。

本计划是现有上下文/记忆/工作流总纲的第一批落地工作，不包含完整记忆治理和持久化重构。

## Constraints

- 不覆盖用户已有未提交文件；实施前逐文件检查 `git diff`。
- 不提交 `.env`、凭证、LangSmith key、QQ 音乐 credential、构建产物或历史记忆备份。
- UI 点击播放、歌单翻页和音频控制继续走确定性 REST API。
- 新 API 字段只能新增，不能破坏旧 `reply`、`trace` 消费路径。
- `messages` 使用 `add_messages` 时只返回 delta。
- 不把 trace 当成稳定业务协议。
- 不把通用 slots 作为本切片的执行前提。
- 所有 P0 行为先有失败测试或可复现证据，再修改实现。

## Task Order

### Task 01: 稳定模型配置与聊天错误响应

**Risk layer:** P0

#### Goal

修复硬编码模型导致的运行时失败，并保证 Agent 异常以稳定 JSON 返回。

#### Suggested Files

- Modify: `app/agents/music_team_v3_1/config.py`
- Modify: `app/api/v1/endpoints.py`
- Modify: `music-agent-chat-ui/.env.example`
- Test: `tests/api/test_local_chat_error_contract.py`

#### Failure tests first

- monkeypatch `endpoints.graph.astream` 抛出异常，断言 `/chat/local` 返回：
  - HTTP `502`
  - `status="error"`
  - `data.run.status="failed"`
  - `data.artifacts=[]`
  - 响应体不含 traceback 或 secret
- 带 `Origin: http://localhost:3000` 发起同一错误请求，断言错误响应仍包含可解析 JSON body 和
  `access-control-allow-origin: http://localhost:3000`，避免浏览器退化成 `Failed to fetch`。
- 空消息请求返回稳定错误。
- `OPENAI_MODEL` 被设置时，`llm0` 使用该模型名。由于 `llm0` 当前在模块导入时创建，测试必须通过配置
  helper/factory 验证，或在测试中显式 reload `app.agents.music_team_v3_1.config`；不得在模块已导入后只改
  `os.environ` 就断言生效。

#### Implementation notes

- 增加 `OPENAI_MODEL` 环境变量读取。
- 保留 `MUSIC_AGENT_MODEL` 给主音乐 Agent。
- 给 `/chat/local` 的 Graph 调用包一层错误映射。
- 错误日志记录 `thread_id` 和异常类型，不把堆栈返回给前端。
- 前端 `sendLocalChatMessage` 继续读取 `message`，但要能显示后端稳定错误文本。

#### Acceptance

```powershell
python -m pytest tests/api/test_local_chat_error_contract.py -q
```

Expected:

- 不访问真实 LLM。
- 错误响应合同通过。
- 手工浏览器发送普通消息不再显示 `Failed to fetch`。

### Task 02: 定义后端 Artifact 模型与收集器

**Risk layer:** P0

#### Goal

让后端产生并校验一等 `artifacts`，为前端摆脱文本 JSON 解析打基础。

#### Suggested Files

- Add: `app/models/chat_artifacts.py`
- Add: `app/agents/music_team_v3_1/artifacts.py`
- Modify: `app/tools/song_tools.py`
- Modify: playlist browser payload 相关工具或 API 组装处
- Test: `tests/agents/test_chat_artifacts.py`

#### Failure tests first

- 合法 `play_music` JSON 被解析为 artifact。
- 合法 `playlist_browser` JSON 被解析为 artifact。
- 缺少 `url` 的 `play_music` 被拒绝。
- 未知 `type` 被拒绝。
- 普通文本和无关 JSON 不产生 artifact。
- 重复 payload 不重复进入结果。

#### Implementation notes

- 使用 Pydantic 模型校验。
- `play_music_tool` 使用模型序列化，避免手写漂移字段。
- 收集器第一阶段可兼容工具结果和最终 AI 文本，但返回前必须校验。
- 不从前端传入任意 URL 生成可信 artifact。

#### Acceptance

```powershell
python -m pytest tests/agents/test_chat_artifacts.py -q
```

Expected:

- 全部解析测试确定性通过。
- 测试不访问真实 QQ 音乐或 LLM。

### Task 03: 修复 Graph message delta 纪律

**Risk layer:** P0

#### Goal

消除 `add_messages` reducer 与完整消息列表返回方式叠加导致的重复累积风险。该任务必须早于 API
Artifact 接入完成，避免 collector 从重复消息中返回重复或过期 Artifact。

#### Suggested Files

- Modify: `app/agents/music_team_v3_1/nodes.py`
- Test: `tests/agents/test_message_delta.py`

#### Failure tests first

- `music_ops_subgraph_node` 只返回新增 AI message。
- `playback_subgraph_node` 只返回新增 AI message。
- `chat_replier_node` 只返回新增 AI message。
- 多轮 state 合并后不会重复旧消息。
- `memory_sync_node` 不直接原地修改 reducer 字段来裁剪消息；如果需要裁剪，应通过明确策略单独处理。

#### Implementation notes

- 节点内部仍可读取 `extract_messages(state)`。
- 返回 `messages` 时只返回 `[ai_msg]`。
- 对 summary 裁剪先保守处理：本切片可以只增加测试和 TODO，或将裁剪移入明确的 future task；不要偷偷丢历史。

#### Acceptance

```powershell
python -m pytest tests/agents/test_message_delta.py -q
```

Expected:

- reducer 行为测试通过。
- 现有聊天 smoke 不回归。

### Task 04: 将 Artifacts 和最小 Run 状态接入 `/chat/local`

**Risk layer:** P0

#### Goal

成功和失败响应都包含稳定 `artifacts` 与 `run` 字段；旧 `reply` 和 `trace` 保留。

#### Suggested Files

- Modify: `app/api/v1/endpoints.py`
- Modify: `app/agents/music_team_v3_1/state.py`
- Modify: `app/agents/music_team_v3_1/nodes.py`
- Test: `tests/api/test_local_chat_artifacts_contract.py`

#### Failure tests first

- fake graph 产生播放 artifact，API 返回 `data.artifacts[0].type == "play_music"`。
- fake graph 不产生 artifact，API 返回 `data.artifacts == []`。
- fake graph 的最终 `reply` 为空但 artifact 有效时，响应仍为 success。
- Agent 异常时，错误响应也有 `artifacts=[]` 和 `run.status="failed"`。
- 使用 delta-correct 的真实节点输出或等价 fake 输出验证：collector 不会因消息 reducer 合并重复返回旧 artifact。
- 模拟 LangChain `ToolMessage` 或等价工具执行消息中包含 `play_music` JSON，经过后续回复节点后，
  `/chat/local` 仍返回该 artifact。该测试用于保护真实 `play_music_tool -> ToolMessage -> Agent -> API` 路径，
  不能只测试 fake graph 顶层塞入 `artifacts`。

#### Implementation notes

- 如果引入 `state["artifacts"]`，finalizer 不应清空它。
- API 层只组装响应，不重新信任 trace。
- `run.status` 第一阶段只需要 `succeeded` / `failed`。
- Artifact collector 应优先读取后端 state 或工具消息中的校验结果；迁移期可兼容最终 AI 文本 JSON，但不得依赖
  trace，也不得绕过 Pydantic 校验。
- 保持旧字段：

```json
{
  "reply": "...",
  "trace": []
}
```

#### Acceptance

```powershell
python -m pytest tests/api/test_local_chat_artifacts_contract.py -q
```

Expected:

- 成功、无 artifact、异常路径都返回稳定响应结构。
- ToolMessage 路径产生的播放 artifact 能穿过后续回复节点并出现在 API 响应里。

### Task 05: 前端优先消费结构化 Artifacts

**Risk layer:** P1

#### Goal

前端从后端 `data.artifacts` 渲染播放器/歌单，旧文本 parser 只作为兼容路径。

#### Suggested Files

- Modify: `music-agent-chat-ui/src/features/chat-local/types.ts`
- Modify: `music-agent-chat-ui/src/features/chat-local/services/localChatApi.ts`
- Modify: `music-agent-chat-ui/src/features/chat-local/hooks/useLocalChatSession.ts`
- Modify: `music-agent-chat-ui/src/features/chat-local/components/AssistantMessageRenderer.tsx`
- Modify: `music-agent-chat-ui/src/features/chat-local/utils.ts`
- Optional add: `music-agent-chat-ui/src/features/chat-local/artifacts.ts`

#### Failure tests first

- 至少抽出一个 artifact 选择/归一化纯函数，并为该函数建立最小自动化测试。测试必须覆盖：
  - `artifacts` 包含 `play_music` 时选择结构化 artifact。
  - `reply` 无 JSON 但 `artifacts` 有效时仍选择结构化 artifact。
  - `artifacts` 存在时不再对同一条 `reply` 执行文本 JSON 兼容解析，避免重复渲染。
  - `artifacts=[]` 时旧文本 JSON 仍可兼容。
  - 未知 artifact 类型不崩溃。
- 若暂不引入 React 组件测试，允许先用 Vitest 测纯函数；但不能只靠 `lint/build + 浏览器验收` 覆盖该核心合同。

#### Implementation notes

- 建立共享 `ChatArtifact` 类型，减少播放器和歌单组件重复定义。
- `sendLocalChatMessage` 返回 `artifacts`。
- `ChatMsg` 增加可选 `artifacts`。
- 新响应的 trace 不再驱动 artifact 渲染。

#### Acceptance

```powershell
cd music-agent-chat-ui
pnpm test
pnpm lint
pnpm build
```

Browser expected:

- 普通聊天显示文本。
- 构造或真实触发 `play_music` artifact 后显示播放器。
- 旧 JSON 文本消息仍能渲染。

### Task 06: 第一切片验收与文档收口

**Risk layer:** P2

#### Goal

只在真实验证完成后同步 `docs/current`，并标记本切片实际完成范围。

#### Suggested Files

- Modify after implementation: `docs/current/ARCHITECTURE.md`
- Modify after implementation: `docs/current/PROGRESS.md`
- Modify after implementation: `docs/current/ROADMAP.md`
- Modify after implementation: `docs/current/DEVNOTES.md`
- Modify after implementation: this plan closeout section

#### Steps

- [ ] 运行后端聚焦测试。
- [ ] 运行前端 lint/build。
- [ ] 浏览器验收普通聊天、错误展示、结构化 artifact、点击播放不走聊天。
- [ ] 记录真实命令和结果。
- [ ] 更新 current docs：只描述已经上线的机制。
- [ ] 未完成项留在 ROADMAP，不写成已完成。

#### Acceptance

```powershell
python -m pytest tests/api tests/agents -q
```

```powershell
cd music-agent-chat-ui
pnpm lint
pnpm build
```

Expected:

- 命令真实执行并记录结果。
- 浏览器验收结果写入 `PROGRESS.md`。
- `ARCHITECTURE.md` 与代码一致。

## Cross-task Validation

最终合并前运行：

```powershell
python -m pytest tests/api tests/agents -q
```

```powershell
pytest
```

```powershell
cd music-agent-chat-ui
pnpm lint
pnpm build
```

浏览器验收：

1. 打开 `http://localhost:3000/chat/local`。
2. 发送普通消息，确认不出现 `Failed to fetch`。
3. 模拟或触发 Agent 异常，确认显示后端错误文本。
4. 触发 `play_music` artifact，确认 `reply` 无 JSON 时播放器仍显示。
5. 打开歌单并点击播放，确认调用 `/api/v1/song/play-url`，不调用 `/chat/local`。

## Review Checkpoints

### A. API contract

- 所有成功响应是否包含 `artifacts` 和 `run`。
- 所有错误响应是否可解析，且不泄露 secret。
- 旧 `reply` 和 `trace` 是否仍兼容。

### B. Artifact safety

- Artifact 是否经过后端模型校验。
- 未知 `type` 是否被拒绝。
- 前端是否不再从 trace 驱动新 artifact。

### C. Graph state

- reducer 字段是否只返回 delta。
- 是否引入了未测试的消息裁剪。
- `intent/slots` 是否仍只是兼容字段，而不是新功能依赖。

### D. Frontend

- 结构化 artifact 与旧文本 parser 是否互斥，避免重复渲染。
- 未知 artifact 和错误响应是否不会导致白屏。
- 点击播放确定性 API 是否保持独立。

### E. Documentation

- 未验证内容不进入 `PROGRESS.md`。
- 未完成的大总纲任务继续留在 `ROADMAP.md`。
- `DEVNOTES.md` 标记哪些风险已解决，哪些仍存在。

## Rollout and Rollback

- API 新字段是向后兼容新增，可以灰度启用前端消费。
- 如果前端 artifact 渲染有问题，可以暂时回退到旧文本 parser，同时保留后端 `artifacts` 输出。
- 如果 Graph delta 修改引起回归，优先保留测试，回滚实现并重新定位 reducer 合并边界。
- 如果模型服务不支持配置模型，回滚不是改代码硬编码，而是修改环境变量并记录供应商支持列表。

## Completion Definition

本切片完成必须同时满足：

- Task 01-05 的聚焦验证通过。
- 浏览器普通聊天不再出现 `Failed to fetch`。
- `/chat/local` 成功和失败响应都符合新合同。
- 前端优先消费结构化 `artifacts`。
- `add_messages` reducer 风险有测试覆盖。
- `docs/current` 只在验证后同步真实状态。

## Closeout

### 2026-07-16 integration verification

This slice is complete on `codex/architecture-improvements` after integration with the three-phase workflow work. Verification evidence:

- Backend: `237 passed` with no exclusions.
- Local-chat API artifact/error contracts: covered by backend contract tests, including `ToolResult.data` artifact extraction.
- Frontend: Playwright local API contract `3 passed`; TypeScript, Prettier, lint, and production build completed successfully.
- The project remains local-chat-only; `/chat/online` redirects to `/chat/local` and the online provider/runtime was not restored.

Live LLM/QQ Music browser E2E remains an external-environment follow-up and is tracked in `docs/current/ROADMAP.md`; it is not treated as an unverified source-code item.

当前状态：源码已更新，等待运行时验证。已接入模型配置、稳定错误响应、后端 artifact 模型与收集器、graph delta message 修复、`/chat/local` 的 `run/artifacts` 响应字段，以及前端结构化 artifact 优先渲染。

本轮未由 Codex 执行后端测试、前端构建或浏览器验收；完成状态需以后续实际验证结果为准。
