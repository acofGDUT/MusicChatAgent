# 确定性动作与结构化 Artifact 实施计划

## 1. 计划目标

按照规格 `docs/SDD/spec/deterministic-action-and-artifact-spec.md`，分阶段完成：

1. 建立结构化 artifact 契约和聚焦测试。
2. 让聊天 API 显式返回 artifacts。
3. 让前端优先使用结构化 artifacts。
4. 移除主链路对 LLM intent parser 和通用 slots 的依赖。
5. 保留直接播放 API 与旧消息兼容能力。

本计划不建设登录、搜索、歌单、播放各模块的完整测试套件，只增加保护本次改造所必需的测试。

## 2. 风险等级定义

| 等级 | 含义 |
| --- | --- |
| P0 | 可能导致错误播放、协议失效、主聊天链路不可用，必须先测试后修改 |
| P1 | 可能造成行为回归、重复渲染或兼容性问题，需要聚焦回归测试 |
| P2 | 可维护性、文档或诊断改进，不阻塞主功能上线 |

## 3. 推荐执行顺序

```text
任务 0：确认基线
  -> 任务 1：定义 artifact 模型与解析器
  -> 任务 2：Graph 收集 artifacts
  -> 任务 3：聊天 API 返回 artifacts
  -> 任务 4：前端消费 artifacts
  -> 任务 5：移除 intent/slots 强依赖
  -> 任务 6：兼容回归与清理
  -> 任务 7：文档同步
```

任务 1 到任务 4 应先完成协议迁移，再修改 Graph 路由。这样能够把“数据返回问题”和“Agent 行为问题”分开定位。

## 4. 任务 0：确认当前基线

### 风险

P1

### 目标

记录改造前的实际行为，避免把现有问题误判为本次回归。

### 涉及文件

- `app/api/v1/endpoints.py`
- `app/agents/music_team_v3_1/graph.py`
- `app/agents/music_team_v3_1/nodes.py`
- `app/agents/music_team_v3_1/state.py`
- `app/tools/song_tools.py`
- `music-agent-chat-ui/src/features/chat-local/services/localChatApi.ts`
- `music-agent-chat-ui/src/components/local-chat/messages/music_player_artifact.tsx`
- `music-agent-chat-ui/src/components/local-chat/messages/playlist_browser_artifact.tsx`

### 执行内容

- 确认 UI 点击播放只调用 `/api/v1/song/play-url`。
- 确认聊天响应当前只有 `reply` 和 `trace`，没有 `artifacts`。
- 确认播放工具当前返回 JSON 字符串。
- 确认前端当前从 `reply` 文本提取 artifact。
- 记录当前 Graph 每次请求会先调用 `intent_parser`。

### 验收

- 基线事实与规格文档一致。
- 不修改业务代码。

## 5. 任务 1：定义 Artifact 模型和解析器

### 风险

P0

### 建议新增文件

- `app/models/chat_artifacts.py`
- `app/agents/music_team_v3_1/artifacts.py`
- `tests/agents/test_artifact_collector.py`

### 建议修改文件

- `app/tools/song_tools.py`
- 产生 `playlist_browser` 数据的对应工具文件

### 先写失败测试

1. 合法 `play_music` JSON 能转换为 `PlayMusicArtifact`。
2. 合法 `playlist_browser` JSON 能转换为 `PlaylistBrowserArtifact`。
3. 缺少 `url` 的 `play_music` JSON 被拒绝。
4. 未知 `type` 被忽略或返回明确解析错误。
5. 普通自然语言和包含无关 JSON 的文本不会生成 artifact。
6. 同一工具结果被重复观察时不会重复添加 artifact。

### 推荐实现路径

1. 使用 Pydantic 定义 artifact 联合类型。
2. 编写只接受白名单类型的 `parse_chat_artifact(value)`。
3. 编写从 `ToolMessage` 或工具执行结果中收集 artifacts 的纯函数。
4. 让 `play_music_tool` 使用模型序列化返回 JSON，而不是手写字典协议。
5. 保持工具返回字符串，以兼容当前 LangChain 工具消息格式。

### 验收

- 解析器不调用 LLM、不访问网络。
- 所有输入都有确定性结果。
- 不合法数据不会进入 Graph State。

## 6. 任务 2：在 Graph State 中收集 Artifacts

### 风险

P0

### 建议修改文件

- `app/agents/music_team_v3_1/state.py`
- `app/agents/music_team_v3_1/nodes.py`
- `app/agents/music_team_v3_1/graph.py`
- `app/agents/music_team_v3_1/utils.py`
- `tests/agents/test_graph_artifacts.py`

### 先写失败测试

1. Agent 工具消息包含合法播放 JSON 时，最终 State 中存在一个 `play_music` artifact。
2. 最终 AI 回复不包含 JSON 时，artifact 仍然保留。
3. 工具失败时 `artifacts` 为空，并保留可读错误回复。
4. 普通聊天最终 State 中 `artifacts=[]`。
5. 多次执行节点不会重复追加相同 artifact。

### 推荐实现路径

1. 在 State 增加 `artifacts`，默认初始化为空数组。
2. 新增 `artifact_collector_node`，只读取本轮新增的工具结果。
3. 在执行 Agent 后、最终回复确定前调用 collector。
4. collector 使用任务 1 的纯解析器，不自行解析任意 AI 回复。
5. 为 artifact 设计稳定去重键，例如：
   - 播放：`type + song_mid + url`
   - 歌单：`type + dirid + page`
6. 保证 finalizer 不清空 artifacts。

### 验收

- artifact 生命周期独立于最终回复文本。
- collector 不从 trace 获取业务数据。
- 单轮请求只返回本轮产生的 artifacts。

## 7. 任务 3：聊天 API 返回 Artifacts

### 风险

P0

### 建议修改文件

- `app/api/v1/endpoints.py`
- 可选新增：`app/api/v1/schemas/chat.py`
- `tests/api/test_local_chat_artifacts.py`

### 先写失败测试

使用 FastAPI dependency/mock 或替代 graph stream，禁止调用真实 LLM 和 QQ 音乐：

1. 普通聊天响应包含 `data.artifacts=[]`。
2. Graph 产生播放 artifact 时，API 原样返回经过 schema 校验的数据。
3. Graph 输出无效 artifact 时，API 不返回该项。
4. `reply` 为空但 artifact 有效时，请求仍成功并返回 artifact。
5. 响应继续包含 `thread_id` 和兼容的 `trace`。

### 推荐实现路径

1. 为本地聊天响应增加 Pydantic response model。
2. 在消费 `graph.astream` 时保存最新 State 的 artifacts。
3. 返回固定数组字段，禁止 `null`。
4. API 层只做响应组装，不重新从 AI 文本中提取 JSON。
5. 暂时保留 trace，但明确其仅用于调试。

### 验收

```json
{
  "status": "success",
  "data": {
    "thread_id": "test-thread",
    "reply": "已经为你找到歌曲。",
    "artifacts": [],
    "trace": []
  }
}
```

- `artifacts` 始终存在。
- API 测试无需外部网络即可运行。

## 8. 任务 4：前端优先消费结构化 Artifacts

### 风险

P0

### 建议修改文件

- `music-agent-chat-ui/src/features/chat-local/types.ts`
- `music-agent-chat-ui/src/features/chat-local/services/localChatApi.ts`
- `music-agent-chat-ui/src/features/chat-local/hooks/useLocalChatSession.ts`
- `music-agent-chat-ui/src/features/chat-local/components/AssistantMessageRenderer.tsx`
- `music-agent-chat-ui/src/features/chat-local/utils.ts`
- `music-agent-chat-ui/src/components/local-chat/messages/music_player_artifact.tsx`
- `music-agent-chat-ui/src/components/local-chat/messages/playlist_browser_artifact.tsx`
- 建议新增：`music-agent-chat-ui/src/features/chat-local/artifacts.ts`

### 测试基础设施

当前前端没有测试脚本。为本次改造建议最小引入 Vitest、Testing Library 和 jsdom：

- `music-agent-chat-ui/vitest.config.ts`
- `music-agent-chat-ui/src/test/setup.ts`
- `music-agent-chat-ui/src/features/chat-local/components/AssistantMessageRenderer.test.tsx`

如果团队暂不接受增加前端测试依赖，至少将 artifact 选择逻辑提取为纯函数，并通过 TypeScript 类型检查、lint、build 和浏览器手工验收保护；但 P0 协议迁移更推荐自动化组件测试。

### 先写失败测试

1. 响应包含 `play_music` artifact 时渲染播放器组件。
2. `reply` 不包含 JSON 时仍能渲染播放器。
3. 响应包含结构化 artifact 时，不再从同一条 `reply` 重复提取并渲染。
4. `artifacts=[]` 且旧消息包含合法 JSON 时，兼容 parser 仍可渲染。
5. 未知 artifact 类型不会导致聊天页崩溃。

### 推荐实现路径

1. 建立共享 TypeScript artifact 联合类型，避免两个组件重复定义 `PlayMusicPayload`。
2. `sendLocalChatMessage` 返回 `artifacts`。
3. `ChatMsg` 增加可选 `artifacts` 字段。
4. `AssistantMessageRenderer` 优先遍历 `msg.artifacts`。
5. 只有历史消息没有 artifacts 时才调用旧文本 parser。
6. 保留直接播放组件中的 `/song/play-url` 调用，不将其改成聊天请求。

### 验收

- 新协议能够驱动播放器和歌单组件。
- 同一 artifact 不会出现两次。
- 旧历史消息仍然可展示。
- 未知 artifact 安静降级为文本，不导致白屏。

## 9. 任务 5：移除 Intent Parser 和通用 Slots 强依赖

### 风险

P1

### 建议修改文件

- `app/agents/music_team_v3_1/state.py`
- `app/agents/music_team_v3_1/graph.py`
- `app/agents/music_team_v3_1/nodes.py`
- `app/agents/music_team_v3_1/agents.py`
- `app/agents/music_team_v3_1/prompts.py`
- `app/agents/music_team_v3_1/utils.py`
- `app/api/v1/endpoints.py`
- `tests/agents/test_graph_routing.py`

### 先写失败测试

1. 普通聊天只经过工具型 Agent，不调用独立 intent parser。
2. 自然语言播放请求允许 Agent 调用搜索和播放工具。
3. Agent 不调用工具时可以直接返回普通文本。
4. Agent 无法确定“第二首”所指对象时返回澄清文本，而不是进入 slot filling 状态。
5. Graph 最终结果不要求存在 `task.intent`、`extracted_slots` 或 `missing_slots`。

测试应使用 fake model 或 mock agent，断言节点顺序和状态变化，不断言真实 LLM 对中文句子的分类结果。

### 推荐实现路径

#### 路径 A：直接收敛为单一工具型 Agent（推荐）

1. 将普通聊天能力和音乐工具能力合并到 `assistant_agent`。
2. Graph 改为：

```text
init_memory -> assistant_agent -> artifact_collector -> memory_sync -> finalizer
```

3. 删除 `intent_parser_node`、`supervisor_router_node` 和相关 prompt/schema。
4. 评估 `playback_subgraph` 与 `music_ops_subgraph` 的工具集合；若无权限边界差异，合并。
5. 保留工具调用循环的最大步数限制，防止重复执行。

#### 路径 B：分两步迁移（回滚成本较低）

1. 第一阶段保留两个执行 Agent，但使用确定性兼容规则选择节点；无法确定时进入通用工具 Agent。
2. 第二阶段观察工具调用日志后合并 Agent。

路径 B 只用于降低一次性改造风险，不应重新发展成关键词意图系统。

### 删除或降级字段

- `IntentParserDecision`
- `IntentType`
- `TaskMeta.required_slots`
- `TaskMeta.extracted_slots`
- `TaskMeta.missing_slots`
- `RuntimeControl.is_ready_to_execute`
- intent parser 和 supervisor 的 trace 摘要

若 `TaskMeta.status` 和 `error_reason` 仍用于记忆或错误处理，可保留为轻量运行状态。

### 验收

- 每条聊天消息不再先付出一次 intent 分类 LLM 调用。
- Graph 不根据 slots 决定是否执行工具。
- UI 直接播放接口没有变化。
- artifact 测试和前端渲染测试继续通过。

## 10. 任务 6：兼容性回归与清理

### 风险

P1

### 建议修改文件

- `music-agent-chat-ui/src/features/chat-local/utils.ts`
- `music-agent-chat-ui/src/components/local-chat/messages/music_player_artifact.tsx`
- `music-agent-chat-ui/src/components/local-chat/messages/playlist_browser_artifact.tsx`
- `app/api/v1/endpoints.py`
- `app/agents/music_team_v3_1/prompts.py`

### 检查项

- 新响应不再要求模型“只输出 JSON”。
- 旧文本 JSON parser 只用于历史兼容。
- trace 中即使包含 JSON，也不会触发播放器。
- UI 播放地址缓存和歌单翻页行为不变。
- 404 播放地址错误能显示给用户且不生成 artifact。
- 删除未使用的 intent/slot prompt、类型和 trace 字段。

### 验收

- `rg` 不再发现主链路读取 `missing_slots` 或 `extracted_slots`。
- `intent_parser` 只允许出现在迁移文档或历史记录中，不出现在目标 Graph。
- 兼容 parser 有明确注释和后续删除条件。

## 11. 任务 7：文档同步

### 风险

P2

### 建议修改文件

- `README.md`
- `music-agent-chat-ui/README.md`
- `AGENTS.md`
- 项目现有架构说明文档
- 本 SDD 的状态和决策记录

### 同步内容

- Graph 最新流程图。
- UI 直接 API 与自然语言 Agent 的边界。
- `/chat/local` 的 `artifacts` 响应结构。
- artifact 新类型的扩展方式。
- 旧文本 JSON parser 的兼容期限。
- 删除“两种聊天模式”和旧前端环境变量等过时说明。

### 验收

- 文档与实际 Graph 节点、API 字段和环境变量一致。
- 新开发者不需要阅读旧 intent/slots 设计才能理解主链路。

## 12. 测试命令与预期结果

### 后端聚焦测试

```powershell
pytest tests/agents/test_artifact_collector.py tests/agents/test_graph_artifacts.py tests/api/test_local_chat_artifacts.py
```

预期：全部通过，不访问真实 LLM、QQ 音乐或公网。

### 后端完整测试

```powershell
pytest
```

预期：现有测试和新增测试全部通过。若现有测试存在基线故障，应单独记录，不允许通过跳过新增测试掩盖。

### 前端组件测试

```powershell
pnpm test
```

预期：结构化 artifact、旧消息兼容、未知类型降级测试全部通过。

### 前端静态检查

```powershell
pnpm lint
pnpm format:check
pnpm build
```

预期：无 lint 错误、格式检查通过、Next.js production build 成功。

### 搜索式清理检查

```powershell
rg -n "missing_slots|extracted_slots|required_slots|intent_parser" app/agents/music_team_v3_1 app/api/v1
```

预期：目标实现完成后无运行时依赖；仅允许迁移注释或明确保留的兼容代码。

## 13. 浏览器验收场景

前后端启动后，在本地聊天页面完成：

1. 发送普通问候，确认只显示文本，不出现空播放器。
2. 发送自然语言播放请求，确认回复文本与播放器均出现。
3. 确认回复文本中没有 JSON 时播放器仍出现。
4. 打开歌单并点击歌曲，确认直接请求 `/song/play-url`。
5. 点击暂停、继续、拖动进度，确认不产生聊天请求。
6. 模拟播放 URL 404，确认显示错误且页面不崩溃。
7. 加载包含旧 JSON 文本的历史消息，确认仍能显示旧组件。

浏览器 Network 面板检查：

- UI 点击播放不得调用 `/chat/local`。
- 自然语言请求调用 `/chat/local`，响应包含 `artifacts`。
- 同一次响应不得造成组件重复渲染。

## 14. Review 检查点

### Checkpoint A：协议评审

在实现任务 1 前确认：

- artifact 字段名称是否稳定。
- `play_music` 和 `playlist_browser` 是否覆盖当前组件需求。
- URL、封面和歌曲标识的必填边界。
- 未知 artifact 的降级行为。

### Checkpoint B：后端评审

任务 1 到任务 3 完成后确认：

- 工具结果经过模型校验。
- collector 不依赖 AI 最终文本或 trace。
- API 始终返回数组。
- 测试没有真实外部依赖。

### Checkpoint C：前端评审

任务 4 完成后确认：

- 类型定义没有在多个组件重复维护。
- 新旧解析路径不会同时触发。
- 未知类型和无效数据不会导致页面崩溃。
- 直接播放链路保持独立。

### Checkpoint D：Graph 简化评审

任务 5 完成后确认：

- intent parser 确实从运行图移除。
- 没有用大规模关键词规则替代原分类器。
- Agent 的工具权限和最大循环次数合理。
- 普通聊天、音乐查询、自然语言播放均有回归覆盖。

### Checkpoint E：发布前评审

- 后端聚焦测试通过。
- 前端测试、lint、format、build 通过。
- 浏览器验收场景通过。
- 文档同步完成。
- 无凭证、播放 URL 或内部错误堆栈进入日志和 trace。

## 15. 提交拆分建议

建议按可独立回滚的提交拆分：

1. `test: define chat artifact contract`
2. `feat: collect structured artifacts from tool results`
3. `feat: return artifacts from local chat API`
4. `feat: render structured chat artifacts in local UI`
5. `refactor: remove intent parser and generic slots`
6. `docs: update agent and chat architecture`

不要把协议、Graph 重构和前端迁移压进同一个提交，以便在行为变化时快速定位和回滚。

## 16. 完成定义

满足以下条件后，本次优化视为完成：

- UI 明确动作继续走确定性 API。
- 自然语言请求不再强制经过独立 intent parser。
- Graph State 不再依赖通用 slots。
- 聊天 API 正式返回经过校验的 `artifacts`。
- 前端优先使用结构化 artifacts，旧文本 parser 仅用于兼容。
- 聚焦自动化测试和浏览器验收通过。
- 架构及 API 文档已同步。
