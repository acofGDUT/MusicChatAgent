# 开发注意事项

本文档记录当前改造项目时仍然重要的风险和约束。只有在实现和验证证明风险已经消除后，才能删除或标记为 resolved。

## 当前风险

### Message reducer 风险（部分已解决）

`MusicGraphStateV31.messages` 使用 LangGraph `add_messages`。
`music_ops_subgraph_node`、`playback_subgraph_node`、`chat_replier_node` 已改为只返回 agent 本轮产生的 delta messages，而不是返回完整历史消息列表。
delta 可以包含 `ToolMessage` 和最终 `AIMessage`，这样播放工具返回的 JSON 不会在进入 API 前丢失。
本轮源码更新没有执行测试；需要由后续人工或自动化验证确认 reducer 合并后不重复、不漏消息。
`memory_sync_node` 仍存在 `state["messages"]` 原地修改，测试已标记 skip，需要在后续改造中解决。

### 最新请求可能被旧上下文稀释

`intent_parser_node` 会把最新用户文本写入 `task.goal`，但 executor 收到的是完整提取消息，加上可选 summary/profile/soul。
当前还没有显式 `CurrentRequest` 合同，也没有强制优先级机制。

### Profile 注入是截断，不是检索

`build_runtime_messages()` injects `user_profile[:2200]`. If profile grows, relevant facts near the end may be lost while irrelevant facts near the top remain.
如果 profile 继续增长，靠后的相关事实可能丢失，而靠前的不相关事实仍会保留。
profile 更新是整篇文档级 LLM 重写，目前缺少字段级校验。

### Soul 应是稳定策略，不应是运行时记忆

运行时 soul autotune 默认关闭，但代码路径仍存在于 `MUSIC_AGENT_ENABLE_SOUL_AUTOTUNE` 之后。
在经过 review 的迁移移除运行时写入前，应把 soul 当作版本化产品策略。

### 已检查文件中的记忆作用域是全局的

`app/agents/memory/user_profile.md`、`soul.md` 和 `history.jsonl` 是共享路径。已检查代码中没有看到 profile 或 soul 的用户/account 命名空间。

### History 不是权威聊天存储

`/chat/local/history` 从 `history.jsonl` 的预览内容重建消息。这些预览适合展示和调试，但不能可靠恢复完整消息或结构化 Artifact。

### Graph 分支生命周期不对称

只有 `music_ops_subgraph` 会经过 `memory_sync`。Playback 直接进入 finalizer，smalltalk 会经过 `chat_replier` 但不经过 memory sync。
任何记忆或运行状态改造都必须覆盖所有分支。

### 失败检测部分依赖文本

`music_ops_subgraph_node` 会在最终文本包含中文失败关键词时标记失败。在依赖它保障副作用安全前，应替换为结构化 outcome 和工具/异常映射。

### API 模块过宽

`app/api/v1/endpoints.py` 同时包含聊天、认证、音乐、工具辅助和前端播放器直连接口。新增 schema 和响应契约时，优先在保持兼容 import 的前提下按 route group 拆分。

### `HTTPException` 导入已修复，仍需回归播放器错误路径

`app/api/v1/endpoints.py` 已改为从 FastAPI 导入 `HTTPException`。
播放器直连接口 `GET /song/play-url`、`GET /playlist/{dirid}/tracks` 的错误路径仍需要在人工验收或自动化测试中覆盖。

### 前端当前只有一个活跃聊天模式

`/chat/online` 会重定向到 `/chat/local`。在重新引入在线流式能力前，文档和 UI 标签不应声称有两个活跃模式。

### 前端 Artifact 渲染已接入结构化 artifacts

后端在 `data.artifacts` 中返回结构化 Artifact 数组，前端 `AssistantMessageRenderer` 优先从 `msg.artifacts` 渲染。
文本解析仅保留给没有 artifacts 的旧历史消息。
`artifacts.ts` 定义共享 `ChatArtifact` 类型和类型守卫。
`selectRenderableArtifacts()` 负责做结构化优先、legacy JSON 兼容和避免同一条回复重复渲染。

### 本轮 artifact 链路源码已更新但未运行验证

本轮源码已经把 `play_music_tool -> ToolMessage -> graph delta -> /chat/local data.artifacts -> frontend renderer` 串起来。
用户要求先不由 Codex 跑测试，因此当前文档只能标记为源码已更新，不能写成运行时已验证。

### 测试覆盖已改善但仍偏薄

此前已有后端测试覆盖 graph state、message delta、artifacts、API 契约、LLM init 等方向。
本轮源码更新没有执行这些测试；测试结果不应沿用为本轮改动的通过证据。
`tests/test_search_service.py` 是预存测试。
后续优化需要继续补充行为测试，尤其是 memory sync、agent 重试、工具失败路径。

## 工作约定

- 修改高风险行为前，先增加失败测试或可复现评测样例。
- UI 确定性动作继续留在 LLM 路径之外。
- 记忆写入的风险高于记忆读取。
- 不把真实凭证、原始私密历史、生成的构建产物或记忆备份写入 Git。
- 只有在验证实现后才更新 `docs/current/`；单纯计划阶段不要把内容写成当前事实。
