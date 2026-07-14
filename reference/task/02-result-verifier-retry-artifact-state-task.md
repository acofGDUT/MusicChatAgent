# Result Verifier、一次性 Retry、Artifact Schema 与搜索上下文任务清单

## 1. 任务信息

- 状态：Done
- 优先级：P0
- 对应 Spec：[`reference/spec/02-result-verifier-retry-artifact-state-spec.md`](../spec/02-result-verifier-retry-artifact-state-spec.md)
- 前置条件：第一阶段 ToolResult 改造已完成，现有 53 个测试通过
- 目标：实现确定性结果校验、一次安全重试、Artifact Schema 和 `last_search_results`
- 推荐执行方式：严格按 TASK-01 至 TASK-12 顺序推进

## 2. 范围约束

本任务只实现第二份 Spec，不得顺手加入：

- SQLite checkpointer
- `user_id/thread_id` 隔离
- 用户长期偏好或跨线程记忆
- Human-in-the-loop 审批
- 全局槽位系统
- 新的 verifier/judge/planner Agent
- 多次 retry、指数退避或后台重试队列
- 写操作自动 retry 或补偿事务
- 前端 UI 重构
- 从 Pydantic 自动生成 TypeScript 类型

实现必须遵守以下安全边界：

1. `result_verifier` 是确定性代码，不调用 LLM。
2. 本阶段最多 retry 一次。
3. 当前执行尝试只要调用过写工具，就不得自动 retry。
4. `WRITE_UNCERTAIN` 不得触发写操作重放。
5. 直接加歌结果不确定时，只允许执行一次只读后置查询。
6. Artifact 校验失败时，不得把损坏 JSON 继续交给前端。

## 3. 完成顺序总览

- [x] TASK-01：建立 Artifact Schema 和解析帮助函数
- [x] TASK-02：让播放工具和 Artifact API 使用 Schema
- [x] TASK-03：扩展 ToolResult、State 和请求初始化逻辑
- [x] TASK-04：提取当前工具执行摘要并识别写工具
- [x] TASK-05：保存并注入 `last_search_results`
- [x] TASK-06：实现 Result Verifier 基础流程和 Artifact 校验
- [x] TASK-07：实现直接加歌的只读后置验证
- [x] TASK-08：实现一次性 Retry 决策和上下文
- [x] TASK-09：修改 LangGraph 路由并验证循环边界
- [x] TASK-10：更新 Prompt 和 Trace
- [x] TASK-11：补齐离线测试和回归检查
- [x] TASK-12：执行最终验收

---

## TASK-01：建立 Artifact Schema 和解析帮助函数

### 新增文件

- `app/schemas/__init__.py`
- `app/schemas/artifacts.py`
- `tests/schemas/__init__.py`
- `tests/schemas/test_artifacts.py`

### 操作

- [x] 实现 `PlayMusicArtifact`。
- [x] 实现 `PlaylistTrack`。
- [x] 实现 `PlaylistBrowserArtifact`。
- [x] 三个模型统一设置 `extra="forbid"`。
- [x] 对 `song_mid`、`title`、`playlist_name` 去除首尾空格并拒绝空值。
- [x] 播放 `url` 必须是非空 HTTP(S) URL。
- [x] `cover` 允许空字符串；非空时必须是 HTTP(S) URL。
- [x] `PlaylistTrack.index >= 1`。
- [x] `PlaylistBrowserArtifact.page >= 1`。
- [x] `1 <= page_size <= 50`。
- [x] `total_song_num >= 0`，且不得小于当前 `tracks` 数量。
- [x] 同一页中禁止重复 `index`。
- [x] 同一页中禁止重复 `song_mid`。
- [x] 使用 `type` discriminator 定义 Artifact Union。
- [x] 实现 `parse_artifact_text(text)`。
- [x] 实现 `artifact_to_json(artifact)`。
- [x] 从 `app/schemas/__init__.py` 导出需要公开使用的类型和函数。
- [x] Schema 不得导入 Agent graph，避免 API 导入时触发图初始化。

### `parse_artifact_text` 规则

- [x] 接受纯 JSON object。
- [x] 接受只包含一个 JSON object 的单一 `json` Markdown 代码块。
- [x] 拒绝 JSON array。
- [x] 拒绝自然语言前后包裹 JSON。
- [x] 拒绝未知 `type`。
- [x] 解析或校验失败时返回 `None`，不抛异常。

### 测试

- [x] 播放 Artifact 合法输入可以 JSON round-trip。
- [x] 播放 URL 不是 HTTP(S) 时校验失败。
- [x] 空 `song_mid` 和空 `title` 校验失败。
- [x] 空 `cover` 合法，非法非空 `cover` 校验失败。
- [x] 歌单 Artifact 合法输入可以 JSON round-trip。
- [x] 非法 page、page_size、index 校验失败。
- [x] 重复 index 校验失败。
- [x] 重复 song_mid 校验失败。
- [x] 未知字段校验失败。
- [x] 纯 JSON 可以解析。
- [x] 单一 JSON 代码块可以解析。
- [x] 混合自然语言的 JSON 被拒绝。

### 完成条件

- [x] `.venv/bin/python -m pytest tests/schemas/test_artifacts.py -q` 通过。
- [x] 合法 Artifact 经 `artifact_to_json` 输出的是纯 JSON，不含 Markdown 标记。

---

## TASK-02：让播放工具和 Artifact API 使用 Schema

### 修改文件

- `app/tools/song_tools.py`
- `app/tools/playlist_tools.py`
- `app/api/v1/endpoints.py`
- `tests/tools/test_song_tools.py`
- `tests/api/__init__.py`
- `tests/api/test_artifact_endpoints.py`

### A. 播放工具

- [x] `play_music_tool` 成功时先构造 `PlayMusicArtifact`。
- [x] 使用 `artifact.model_dump(mode="json")` 作为 `ToolResult.data`。
- [x] 删除成功路径中手写、未校验的播放器 payload。
- [x] 失败路径继续返回原 ToolResult，不创建虚假 Artifact。
- [x] 保持当前前端字段兼容：`type/song_mid/title/artist/url/cover/description`。

### B. FastAPI 端点

- [x] `GET /song/play-url` 的成功响应使用 `PlayMusicArtifact` 校验。
- [x] `GET /playlist/{dirid}/tracks` 的成功响应使用 `PlaylistBrowserArtifact` 校验。
- [x] 可使用 `response_model`，或在返回前显式构造 Pydantic 模型。
- [x] 成功响应保持现有裸 Artifact JSON，不增加 ToolResult 外层。
- [x] 内部数据不符合 Schema 时不得继续返回 HTTP 200 的损坏协议。
- [x] OpenAPI 能展示完整 Artifact 字段。
- [x] 不修改前端现有 Artifact 解析方式。
- [x] `HTTPException` 从 FastAPI 导入。
- [x] 播放端点未传 title 时使用“未知歌曲”兼容现有请求。

### C. 歌单详情工具

- [x] `get_playlist_detail_tool` 迁移为 ToolResult。
- [x] 成功时 `ToolResult.data` 由 `PlaylistBrowserArtifact` 构造。
- [x] 上游失败返回可重试的 `UPSTREAM_ERROR`。
- [x] 将该工具加入强制 ToolResult 协议集合。
- [x] 失败时 verifier 不得误报为 `ARTIFACT_INVALID`。

### 测试

- [x] 播放工具成功 data 能被 `PlayMusicArtifact.model_validate` 解析。
- [x] 播放工具失败时没有 `type=play_music` Artifact。
- [x] 播放端点成功响应符合 Schema。
- [x] 歌单曲目端点成功响应符合 Schema。
- [x] 两个端点字段与现有前端类型兼容。
- [x] 测试 mock Service，不访问 QQ 音乐。

### 完成条件

- [x] 原有 `tests/tools/test_song_tools.py` 全部通过。
- [x] `.venv/bin/python -m pytest tests/api/test_artifact_endpoints.py -q` 通过。

---

## TASK-03：扩展 ToolResult、State 和请求初始化逻辑

### 修改文件

- `app/tools/tool_result.py`
- `app/agents/music_team_v3_1/state.py`
- `app/agents/music_team_v3_1/nodes.py`
- `tests/tools/test_tool_result.py`
- `tests/agents/test_result_verifier.py`

### A. ToolResult

- [x] 在 `ToolResultCode` 中新增 `ARTIFACT_INVALID`。
- [x] 继续约束 `ok=false` 才能使用该错误码。
- [x] 允许只读 playback 流程将其标记为 `retryable=true`。
- [x] 不改变第一阶段已有错误码语义。

### B. RuntimeControl

- [x] 增加 `retry_count`，默认值为 0。
- [x] 增加 `max_retries`，本阶段固定为 1。
- [x] 增加 `retry_reason`。
- [x] 增加 `retry_tool_name` 和 `retry_artifact_type`。
- [x] 增加 `verifier_route`，限定四个合法路由值。
- [x] State 中只保存可序列化的 dict、list、str、int 和 bool。

### C. 新请求初始化

每次新用户请求经过 `init_memory_node` 时：

- [x] 将 `retry_count` 重置为 0。
- [x] 将 `max_retries` 设置为 1。
- [x] 清理旧 `retry_reason`。
- [x] 清理旧 `retry_tool_name/retry_artifact_type`。
- [x] 清理旧 `verifier_route`。
- [x] 清理旧 `extensions.current_tool_run`。
- [x] 清理旧 `extensions.verification`。
- [x] 清理旧 `extensions.retry_original_result`。
- [x] 保留 `extensions.last_search_results`。
- [x] 保留现有 `executor_reentry/max_reentry`，不在本任务中合并计数器。

### 测试

- [x] `ARTIFACT_INVALID` 可以完成 ToolResult JSON round-trip。
- [x] 新用户请求会重置 retry 状态。
- [x] 新用户请求不会删除 `last_search_results`。
- [x] 初始化后的 `max_retries` 恒为 1。

### 完成条件

- [x] 第一阶段 ToolResult 模型测试继续通过。
- [x] State 可以被当前 checkpointer 正常序列化。

---

## TASK-04：提取当前工具执行摘要并识别写工具

### 修改文件

- `app/agents/music_team_v3_1/utils.py`
- `app/agents/music_team_v3_1/nodes.py`
- `tests/agents/test_result_verifier.py`

### 操作

- [x] 定义 `WRITE_TOOL_NAMES`：
  - [x] `create_playlist_tool`
  - [x] `add_songs_to_playlist_tool`
  - [x] `add_by_keyword_to_playlist_tool`
  - [x] `delete_playlist_tool`
  - [x] `remove_songs_from_playlist_tool`
- [x] 实现 `extract_current_tool_run(messages)`。
- [x] 实现 `current_tool_names(state)`。
- [x] 实现 `current_run_has_write_tool(state)`。
- [x] 只收集最后一个 HumanMessage 之后的 ToolMessage。
- [x] 每次 executor 返回后覆盖 `extensions.current_tool_run`。
- [x] 每一项保存 `tool_name`、`tool_call_id`、`protocol_valid` 和解析后的 `result`。
- [x] 已迁移工具的合法 ToolResult 保存为普通 dict。
- [x] 旧工具文本保存 `protocol_valid=false`、`result=None`，但保留工具名。
- [x] 不保存完整 ToolMessage 原文。
- [x] 不保存 Cookie、Credential 或异常栈。
- [x] Retry 安全判断使用完整 `current_tool_run`，不得只检查最后一个 ToolResult。

### 测试

- [x] 同一轮多个 ToolMessage 按顺序被提取。
- [x] 上一轮 ToolMessage 不会进入当前执行摘要。
- [x] 合法 ToolResult 被解析为 dict。
- [x] 旧工具普通文本保持兼容。
- [x] 当前轮任意位置出现写工具时，`current_run_has_write_tool` 返回 true。
- [x] 当前轮只有搜索或播放工具时返回 false。
- [x] 新 executor 尝试会覆盖旧 `current_tool_run`，不会跨 retry 累加。

### 完成条件

- [x] current tool run 数据完全可序列化。
- [x] 写工具检测不依赖 LLM 文本或 ToolResult message。

---

## TASK-05：保存并注入 `last_search_results`

### 修改文件

- `app/agents/music_team_v3_1/utils.py`
- `app/agents/music_team_v3_1/nodes.py`
- `tests/agents/test_result_verifier.py`
- 必要时修改 `tests/agents/test_tool_result_state.py`

### A. 标准化和保存

- [x] 从本轮最后一次 `search_music_tool` 的 ToolResult 读取数据。
- [x] 只保存 `search_type=SONG` 的结果。
- [x] 标准化字段：`id -> song_id`、`mid -> song_mid`、`singer -> artist`。
- [x] 保存 `keyword/search_type/count/items`。
- [x] 每首只保存 `index/song_id/song_mid/title/artist/album`。
- [x] 最多保存 20 首。
- [x] 丢弃缺少有效 index、song_mid 或 title 的项目。
- [x] 不保存播放 URL 和原始 Service 响应。

### B. 更新和清理

- [x] SONG 搜索成功且有合法歌曲时覆盖旧结果。
- [x] SONG 搜索失败时删除旧结果。
- [x] 搜索协议无效时删除旧结果。
- [x] 清洗后没有合法歌曲时删除旧结果。
- [x] 非 SONG 搜索时删除旧结果。
- [x] 本轮没有调用搜索工具时保留旧结果。

### C. Runtime Prompt 注入

- [x] `build_runtime_messages` 为 `executor` 注入精简 `LAST_SEARCH_RESULTS_JSON`。
- [x] `build_runtime_messages` 为 `playback` 注入相同上下文。
- [x] 上下文明确“第 N 首”只能使用列表中的对应 index。
- [x] index 超出范围时要求说明，禁止猜测。
- [x] 已有 song_mid 时提示无需重新搜索。
- [x] 不实现中文序数解析器或槽位系统。

### 测试

- [x] SONG 搜索成功后保存标准化结果。
- [x] 超过 20 首时被截断。
- [x] mid 为空的项目被丢弃。
- [x] 歌曲搜索失败后清理旧结果。
- [x] 非 SONG 搜索后清理旧结果。
- [x] 未调用搜索时保留旧结果。
- [x] executor 和 playback Prompt 都包含精简 JSON。
- [x] Prompt 明确禁止越界猜测。

### 完成条件

- [x] State 中不保存预拼接的 Prompt 文本。
- [x] `last_search_results` 不含播放 URL、凭证或原始大响应。

---

## TASK-06：实现 Result Verifier 基础流程和 Artifact 校验

### 修改文件

- `app/agents/music_team_v3_1/nodes.py`
- `app/agents/music_team_v3_1/utils.py`
- `tests/agents/test_result_verifier.py`

### 操作

- [x] 实现 `async def result_verifier_node(state)`。
- [x] 实现 `def route_after_verifier(state)`。
- [x] Verifier 不调用任何 Agent 或 LLM。
- [x] 严格按 Spec 顺序处理搜索上下文、写后验证、Artifact 和 retry 决策。
- [x] 写入 `extensions.verification`。
- [x] 写入 `control.verifier_route`。

### Artifact 期望判断

- [x] `play_music_tool` 成功时要求 `PlayMusicArtifact`。
- [x] `get_playlist_detail_tool` 后未成功播放歌曲时要求 `PlaylistBrowserArtifact`。
- [x] 最终 AIMessage 本身是 Artifact JSON 时主动校验。
- [x] 没有工具或仅自然追问时不强制 Artifact。
- [x] 最后 ToolResult 失败时不强制 Artifact。
- [x] 期望类型和实际类型不同视为 `ARTIFACT_INVALID`。

### Artifact 规范化

- [x] 读取最后一条 Playback AIMessage。
- [x] 使用 `parse_artifact_text` 校验。
- [x] 成功时保存 `extensions.last_artifact` 普通 dict。
- [x] 使用 `artifact_to_json` 生成纯 JSON。
- [x] 使用相同 message id 更新 AIMessage，让 `add_messages` 替换原消息。
- [x] 成功后设置 `task.status=done`。
- [x] 校验失败时生成 `ARTIFACT_INVALID` ToolResult。
- [x] retry 不允许或已耗尽时，用简短错误文本替换损坏 Artifact。

### Verification 记录

- [x] 保存 `status`：`passed/failed/inconclusive/skipped`。
- [x] 保存最终 `code`。
- [x] 保存简短 `message`。
- [x] 保存 `retry_scheduled`。
- [x] 保存 `retry_count`。
- [x] 不保存异常栈。

### 测试

- [x] 合法 ToolResult 成功时 verifier 通过。
- [x] 合法 Artifact 被规范化为纯 JSON。
- [x] 规范化后 AIMessage 保持原 id。
- [x] Artifact 被保存为普通 dict。
- [x] 非法 Artifact 生成 `ARTIFACT_INVALID`。
- [x] 类型不匹配生成 `ARTIFACT_INVALID`。
- [x] 自然追问不会被错误要求返回 Artifact。
- [x] 最后工具失败时保留真实失败回复。

### 完成条件

- [x] Verifier 单元测试完全离线通过。
- [x] 前端不会收到损坏或混合自然语言的 Artifact JSON。

---

## TASK-07：实现直接加歌的只读后置验证

### 修改文件

- `app/services/music/playlist_service.py`
- `app/agents/music_team_v3_1/nodes.py`
- 必要时修改 `app/agents/music_team_v3_1/utils.py`
- `tests/agents/test_result_verifier.py`
- 必要时修改 `tests/tools/test_playlist_tools.py`

### A. Playlist Service

- [x] `get_all_songs_in_playlist` 支持 `songlist_id=0, dirid=<有效值>`。
- [x] 全量歌曲查询结果包含 `id/mid/title`。
- [x] 普通 `get_playlist_detail` 的瘦身歌曲数据补充 `id`。
- [x] 按 qqmusic-api 0.6.0 的 `request.paginate()` 聚合所有页面。
- [x] 测试 Fake 模拟真实 request/paginate 形状，不使用旧 `all_pages_items`。
- [x] 不改变现有写操作语义。

### B. 触发条件

仅在以下条件全部满足时查询：

- [x] 当前最后相关工具是 `add_songs_to_playlist_tool`。
- [x] `last_tool_result.code=WRITE_UNCERTAIN`。
- [x] `data.dirid` 是有效正整数。
- [x] `data.song_ids` 非空。

### C. 验证结果映射

- [x] 请求歌曲全部存在：改为 `SUCCESS`。
- [x] 全部存在时 message 为“加歌结果已通过查询确认”。
- [x] 全部存在时 `task.status=done`、verification 为 `passed`。
- [x] 仅部分存在：改为 `PARTIAL_SUCCESS`。
- [x] 部分存在时 data 添加 `verified_song_ids/missing_song_ids`。
- [x] 部分存在时 `task.status=failed`、verification 为 `failed`。
- [x] 全部不存在、查询失败或数据不足：保留 `WRITE_UNCERTAIN`。
- [x] 无法确认时 verification 为 `inconclusive`。
- [x] 任意结果都不得重新调用加歌工具。

### D. 明确不处理

- [x] `create_playlist_tool` 的不确定结果不得通过同名歌单猜测成功。
- [x] `add_by_keyword_to_playlist_tool` 不重复执行写后查询。
- [x] 删除歌单和移除歌曲不增加本阶段后置验证。

### 测试

- [x] 全部歌曲存在时升级为 SUCCESS。
- [x] 部分歌曲存在时转换为 PARTIAL_SUCCESS。
- [x] 全部不存在时保持 WRITE_UNCERTAIN。
- [x] 查询异常时保持 WRITE_UNCERTAIN。
- [x] 缺少 dirid 或 song_ids 时不查询。
- [x] 创建歌单不确定不会被误判成功。
- [x] 关键词加歌不会重复查询。
- [x] 测试断言没有第二次写调用。

### 完成条件

- [x] 后置验证只执行读取操作。
- [x] `WRITE_UNCERTAIN.retryable` 仍为 false。

---

## TASK-08：实现一次性 Retry 决策和上下文

### 修改文件

- `app/agents/music_team_v3_1/agents.py`
- `app/agents/music_team_v3_1/nodes.py`
- `app/agents/music_team_v3_1/utils.py`
- `app/agents/music_team_v3_1/prompts.py`
- `tests/agents/test_result_verifier.py`

### Retry 必要条件

- [x] `retry_count < max_retries`。
- [x] 最终失败明确 `retryable=true`，或为可安全修复的 `ARTIFACT_INVALID`。
- [x] 当前 `current_tool_run` 不包含任何写工具。
- [x] 当前 intent 是 `music_ops` 或 `playback`。
- [x] 失败不是 `INVALID_ARGUMENT`。
- [x] 失败不是 `NOT_FOUND`。
- [x] 失败不是 `AUTH_REQUIRED`。
- [x] 失败不是 `PERMISSION_DENIED`。
- [x] 失败不是 `PARTIAL_SUCCESS`。
- [x] 失败不是 `WRITE_UNCERTAIN`。

### 允许 Retry 时

- [x] 先把 `retry_count` 增加 1。
- [x] 保存精简 `retry_reason`。
- [x] 设置 `task.status=running`。
- [x] music ops 设置 `verifier_route=retry_music_ops`。
- [x] playback 设置 `verifier_route=retry_playback`。
- [x] 不新增 HumanMessage。
- [x] 不 sleep。
- [x] 不修改用户原始 goal。
- [x] music ops 使用只注册读取工具的 retry executor。
- [x] 保存原始失败 ToolResult 和对应 `retry_tool_name`。

### Retry 耗尽或禁止时

- [x] 保留原始失败 code。
- [x] 设置 `task.status=failed`。
- [x] `retry_scheduled=false`。
- [x] 第二次失败时 `retry_count` 保持为 1。
- [x] 写工具检测优先于 ToolResult 的 `retryable` 字段。
- [x] 非 Artifact retry 未产生目标工具的新 ToolResult 时恢复原失败。
- [x] `ARTIFACT_INVALID` retry 继续校验首次记录的 Artifact 类型。

### Retry Prompt 上下文

- [x] executor/playback retry 时注入 `RETRY_CONTEXT`。
- [x] 声明这是唯一一次 retry。
- [x] 包含简短 retry 原因。
- [x] 要求只重试失败的读取或播放步骤。
- [x] 明确禁止调用写工具。
- [x] 明确禁止扩大用户原始任务。
- [x] `RETRY_CONTEXT` 位于输入消息末尾。

### 测试

- [x] retryable 搜索失败只安排一次 retry。
- [x] retryable 播放失败只安排一次 retry。
- [x] 第二次失败后停止。
- [x] 安全 playback 的 `ARTIFACT_INVALID` 只 retry 一次。
- [x] 当前轮调用过写工具时绝不 retry。
- [x] `WRITE_UNCERTAIN/PARTIAL_SUCCESS/NOT_FOUND` 不 retry。
- [x] retry 不新增 HumanMessage。
- [x] retry 上下文只在 retry 执行时注入。
- [x] retry executor 注册的工具与 `WRITE_TOOL_NAMES` 没有交集。
- [x] retry 后跳过原失败工具不能被判为成功。

### 完成条件

- [x] 代码中不存在无上限 retry 路径。
- [x] 不使用 LangGraph `RetryPolicy` 重跑整个 executor。

---

## TASK-09：修改 LangGraph 路由并验证循环边界

### 修改文件

- `app/agents/music_team_v3_1/graph.py`
- `app/agents/music_team_v3_1/nodes.py`
- `tests/agents/test_result_verifier.py`
- 可新增 `tests/agents/test_verifier_graph.py`

### Graph 修改

- [x] 注册 `result_verifier` 节点。
- [x] 删除 `music_ops_subgraph -> memory_sync` 普通边。
- [x] 删除 `playback_subgraph -> finalizer` 普通边。
- [x] 新增 `music_ops_subgraph -> result_verifier`。
- [x] 新增 `playback_subgraph -> result_verifier`。
- [x] 给 `result_verifier` 添加 conditional edges。
- [x] 不给 `result_verifier` 再添加普通出边。

### 条件路由映射

- [x] `retry_music_ops -> music_ops_subgraph`。
- [x] `retry_playback -> playback_subgraph`。
- [x] `music_done -> memory_sync`。
- [x] `playback_done -> finalizer`。
- [x] `route_after_verifier` 对未知或缺失路由安全失败，不静默进入 retry。

### 图行为测试

- [x] music ops 成功经过 verifier 后进入 memory sync。
- [x] playback 成功经过 verifier 后进入 finalizer。
- [x] 第一次安全失败回到对应 executor。
- [x] 第二次失败不再形成循环。
- [x] 写操作失败直接走完成路径，不回 executor。
- [x] 图运行不触发 recursion limit。
- [x] 旧 `executor_reentry` guard 不会阻止 verifier 的直接 retry。

### 完成条件

- [x] `MusicTeamGraphV31` 可以正常 import 和 compile。
- [x] 四个 verifier 路由都有自动化测试覆盖。

---

## TASK-10：更新 Prompt 和 Trace

### 修改文件

- `app/agents/music_team_v3_1/prompts.py`
- `app/api/v1/endpoints.py`
- `tests/agents/test_result_verifier.py`
- `tests/api/test_artifact_endpoints.py`

### A. Playback Prompt

- [x] 成功时只允许输出纯 JSON 或单一 JSON 代码块。
- [x] 禁止增加 Schema 外字段。
- [x] 播放 Artifact 必须包含 `song_mid/title/url`。
- [x] 歌单 Artifact 必须包含完整分页字段。
- [x] 禁止在 Artifact 前后附加解释。
- [x] 失败时继续输出真实失败说明，不伪造 Artifact。

### B. Trace

- [x] `TRACE_NODE_NAMES` 增加 `result_verifier`。
- [x] `NON_LLM_TRACE_FIELDS` 为 verifier 增加：
  - [x] `verification_status`
  - [x] `verification_code`
  - [x] `retry_scheduled`
  - [x] `retry_count`
  - [x] `verifier_route`
- [x] `_build_non_llm_trace_summary` 从 `extensions.verification` 和 `control` 读取字段。
- [x] 不改变前端已有 trace 事件外层结构。
- [x] Trace 不输出完整 ToolMessage、异常栈、Cookie 或 Credential。

### 测试

- [x] verifier trace 包含状态和错误码。
- [x] 安排 retry 时 trace 包含 `retry_scheduled=true` 和次数 1。
- [x] 不 retry 时 trace 正确展示最终路由。
- [x] Prompt 包含完整 Artifact 约束。

### 完成条件

- [x] 现有前端无需新增 trace 组件即可展示节点信息。
- [x] Prompt 不承担真正的 retry 安全判断，安全边界仍在 verifier 代码中。

---

## TASK-11：补齐离线测试和回归检查

### 测试文件

- `tests/schemas/test_artifacts.py`
- `tests/agents/test_result_verifier.py`
- `tests/agents/test_verifier_graph.py`（如新增）
- `tests/api/test_artifact_endpoints.py`
- 第一阶段已有全部测试

### 操作

- [x] 运行 Artifact Schema 测试。
- [x] 运行播放工具测试。
- [x] 运行 verifier 单元测试。
- [x] 运行 graph 路由测试。
- [x] 运行 API Artifact 测试。
- [x] 运行完整 pytest。
- [x] 确认测试不读取真实 `.env` 凭证。
- [x] 确认测试不读取 `data/credential.json` 或 `data/cookie.txt`。
- [x] 确认测试不请求 QQ 音乐或其他外部网络。
- [x] 确认测试不调用真实模型。
- [x] 确认所有 Service/Agent 使用 mock、stub 或 fake。
- [x] 确认测试可以重复运行且结果稳定。

### 推荐命令

```bash
.venv/bin/python -m pytest tests/schemas/test_artifacts.py -q
.venv/bin/python -m pytest tests/tools/test_song_tools.py -q
.venv/bin/python -m pytest tests/agents/test_result_verifier.py -q
.venv/bin/python -m pytest tests/agents/test_verifier_graph.py -q
.venv/bin/python -m pytest tests/api/test_artifact_endpoints.py -q
.venv/bin/python -m pytest -q
```

如果没有单独创建 `test_verifier_graph.py`，删除对应命令，不需要为了文件数量强行拆分测试。

### 完成条件

- [x] 第一阶段 53 个测试全部继续通过。
- [x] 第二阶段核心成功、失败、retry 和写操作禁重试场景无 skip。

---

## TASK-12：执行最终验收

### 静态检查

- [x] `result_verifier` 不调用 LLM。
- [x] `result_verifier` 只有 conditional edges，没有普通出边。
- [x] `max_retries` 固定为 1。
- [x] 所有 retry 路径都受 `retry_count < max_retries` 控制。
- [x] 任意包含写工具的执行尝试都不会 retry。
- [x] music ops retry executor 不注册任何写工具。
- [x] retry 必须产生目标工具的新 ToolResult，否则保留原失败。
- [x] `WRITE_UNCERTAIN` 不触发写操作重放。
- [x] 没有使用 LangGraph RetryPolicy 重跑整个 Agent 节点。
- [x] State 中没有保存 Pydantic 对象。
- [x] State 和 trace 中没有保存完整异常栈或凭证。
- [x] Artifact Schema 位于 `app/schemas`，API 导入不会触发 graph 初始化。
- [x] 歌单全量查询使用 qqmusic-api 0.6.0 的 `request.paginate()`。

### 手工或 Mock 流程

- [x] 搜索歌曲成功后，state 保存 `last_search_results`。
- [x] 下一轮“播放第 2 首”能引用对应 song_mid。
- [x] 新歌曲搜索失败后不会引用旧结果。
- [x] 搜索接口暂时失败时自动重试一次。
- [x] 第二次仍失败时向用户返回真实失败。
- [x] 播放成功时前端收到合法纯 JSON Artifact。
- [x] 播放 Agent 输出损坏 JSON 时不会直接交给前端。
- [x] 直接加歌结果不确定时只执行只读查询。
- [x] 直接加歌查询确认全部存在时状态为成功。
- [x] 当前轮执行过创建歌单或加歌时绝不 retry。

### 最终命令

```bash
.venv/bin/python -m pytest -q
git diff --check
git status --short
```

### Definition of Done

- [x] Spec 第 20 节的 12 项验收标准全部满足。
- [x] 所有 Task 已勾选，或记录明确的未完成原因。
- [x] 全部离线测试通过。
- [x] `MusicTeamGraphV31` 可正常 import 和 compile。
- [x] 播放器与歌单 Artifact 的现有前端链路没有回归。
- [x] `reference/spec/02-result-verifier-retry-artifact-state-spec.md` 与实现不存在已知偏差。

## 4. 建议提交边界

如果后续需要分提交，推荐：

1. `feat: add validated music artifact schemas`
2. `feat: persist search context and verify agent results`
3. `feat: add one-shot safe retry routing`
4. `test: cover verifier artifacts and retry boundaries`

提交不是完成任务的必要条件，不要在未经明确要求时自动 commit 或 push。

## 5. 完成记录

- 完成日期：2026-07-13
- 测试结果：`146 passed`
- 测试命令：`PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -q`
- 依赖检查：`.venv/bin/python -m pip check`，无损坏依赖
- 应用检查：`MusicTeamGraphV31` 可正常 import/compile，verifier 四条条件路由均存在
- 安全修正：music ops retry 使用独立只读工具集；非 Artifact retry 必须返回原失败工具的新 ToolResult
- SDK 兼容：歌单全量查询使用 qqmusic-api 0.6.0 的 `request.paginate()`
- API 兼容：保留现有 Artifact 字段；空 title 使用“未知歌曲”兜底
- 测试说明：图路由测试合并在 `tests/agents/test_result_verifier.py`，未单独创建 `test_verifier_graph.py`
- Git 操作：未 commit、未 push，修改保留在当前 `0.6musicApp` 分支
