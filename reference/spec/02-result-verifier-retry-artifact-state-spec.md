# Result Verifier、一次性 Retry、Artifact Schema 与搜索上下文 Spec

## 1. 文档信息

- 状态：Implemented
- 优先级：P0
- 目标版本：Music Team v3.2 / Phase 2
- 前置依赖：`01-tool-result-spec.md` 已实现
- 核心依赖：`ToolResult`、`extensions.last_tool_result`、LangGraph conditional edges、Pydantic v2
- 后续依赖本 Spec 的功能：SQLite 持久化、用户级记忆隔离、历史恢复

## 2. 背景

第一阶段已经解决工具返回格式不统一和自然语言误判状态的问题，但仍存在四个缺口：

1. 执行节点拿到 ToolResult 后直接结束，没有统一的结果校验节点。
2. `retryable=true` 只是数据字段，图中没有明确且有上限的 retry 流程。
3. 播放器和歌单 Artifact 依赖 LLM 手写 JSON，后端没有统一 Schema，可能产生前端无法渲染的结果。
4. 搜索结果只存在于 Agent 内部 ToolMessage 中，图状态没有保存稳定的 `last_search_results`，导致“播放第 2 首”等跨轮引用依赖模型回看长消息。

本阶段增加一个显式、确定性的 `result_verifier` 节点。该节点不调用 LLM，主要负责：

- 保存当前工具执行摘要；
- 保存或清理最后一次歌曲搜索结果；
- 校验并规范化 Artifact；
- 对直接加歌的 `WRITE_UNCERTAIN` 做一次只读后置验证；
- 判断是否允许进行一次安全 retry；
- 决定后续图路由。

## 3. 目标

### 3.1 必须完成

1. 新增 `result_verifier` 节点，并让音乐操作和播放执行节点都经过它。
2. 增加最多一次的显式 retry，仅用于无写副作用、明确标记为可重试的失败。
3. 新增 `PlayMusicArtifact`、`PlaylistBrowserArtifact` 和 `PlaylistTrack` Pydantic Schema。
4. Agent、Tool 和 FastAPI 端点统一使用 Artifact Schema。
5. 对 LLM 最终输出的 Artifact 进行校验，并转成规范 JSON 后再交给前端。
6. 将当前轮工具调用摘要保存到 `extensions.current_tool_run`。
7. 将最近一次成功的歌曲搜索保存到 `extensions.last_search_results`。
8. 在下一轮 Agent 上下文中注入精简的 `last_search_results`，支持“播放第 N 首”。
9. 对直接加歌的 `WRITE_UNCERTAIN` 做一次只读后置查询，不重复执行写操作。
10. 在现有 trace 中展示 verifier 状态和 retry 次数。
11. 添加完全离线的单元测试和图路由测试。

### 3.2 非目标

以下内容不在本 Spec 中实现：

- SQLite checkpointer。
- `user_id/thread_id` 隔离。
- 用户长期偏好和跨线程记忆。
- Human-in-the-loop 审批。
- 全局槽位系统。
- 多次 retry、指数退避、后台任务队列。
- 重试写操作或补偿事务。
- 新增 LLM verifier、judge Agent 或 planner Agent。
- 推荐算法和自动生成主题歌单。
- 前端 UI 重构或新增复杂交互。
- 自动从 Pydantic 生成 TypeScript 类型。

## 4. 设计原则

### 4.1 Verifier 必须是确定性代码

`result_verifier` 不调用模型。所有判断基于：

- `ToolResult`；
- 当前轮工具名称；
- Pydantic 校验；
- 必要时的一次只读查询；
- 明确的 retry 计数器。

不得让 LLM 判断自己的 JSON 是否正确，也不得通过提示词判断工具是否真实成功。

### 4.2 Retry 只处理安全且暂时性的失败

允许 retry 的必要条件：

1. 当前失败的 `ToolResult.retryable=true`，或本轮出现可安全修复的 `ARTIFACT_INVALID`；
2. 当前轮没有执行任何写工具；
3. `retry_count < max_retries`；
4. 原执行域是 `music_ops` 或 `playback`；
5. 不是 `INVALID_ARGUMENT`、`NOT_FOUND`、`AUTH_REQUIRED`、`PERMISSION_DENIED`、`PARTIAL_SUCCESS` 或 `WRITE_UNCERTAIN`。

本阶段 `max_retries` 固定为 1。

### 4.3 不使用 LangGraph RetryPolicy 重跑整个 Agent 节点

LangGraph 的 RetryPolicy 适合节点抛出的暂时性异常；当前项目的大多数业务失败已经被转换成 ToolResult，不会抛异常。直接给整个 executor 节点配置 RetryPolicy 还可能重复执行该节点之前已经完成的写操作。

因此本阶段使用显式状态和条件边形成一次可观测循环：

```text
executor -> result_verifier -> executor（最多一次）
```

这使 retry 原因、次数和安全判断都能出现在 state 和 trace 中。

### 4.4 写操作永不自动重试

以下工具统一视为写工具：

```python
WRITE_TOOL_NAMES = {
    "create_playlist_tool",
    "add_songs_to_playlist_tool",
    "add_by_keyword_to_playlist_tool",
    "delete_playlist_tool",
    "remove_songs_from_playlist_tool",
}
```

即使当前轮最后一个失败来自只读工具，只要该轮之前调用过上述任意工具，也禁止重新执行整个 Agent。

`music_ops` 的 retry 不得继续使用暴露写工具的完整 executor。新增只读 retry executor，工具集只包含搜索和查询类工具。Prompt 约束只是补充，真正的“不可写”边界由工具注册集合保证。

### 4.5 State 保存原始结构化数据

`last_search_results` 保存歌曲引用数据，不保存已经拼接好的 Prompt 文本。Prompt 在 `build_runtime_messages` 中按需构建。

### 4.6 Artifact 校验后统一规范化

允许 Playback Agent 返回：

- 纯 JSON；
- 只包含一个 JSON 的 Markdown 代码块。

不接受“自然语言 + 嵌入 JSON”的混合输出。校验成功后，verifier 使用 Pydantic `model_dump_json()` 生成纯 JSON，并替换最终 AIMessage 内容。

## 5. 目标图结构

当前两条执行路径调整为：

```text
START
  -> init_memory
  -> intent_parser
  -> supervisor_router
       -> music_ops_subgraph
       -> playback_subgraph

music_ops_subgraph
  -> result_verifier
       -> retry_music_ops -> music_ops_subgraph
       -> music_done -> memory_sync -> chat_replier -> finalizer -> END

playback_subgraph
  -> result_verifier
       -> retry_playback -> playback_subgraph
       -> playback_done -> finalizer -> END
```

### 5.1 Graph 修改要求

在 `graph.py` 中：

1. 新增节点 `result_verifier`。
2. 删除：
   - `music_ops_subgraph -> memory_sync`
   - `playback_subgraph -> finalizer`
3. 新增：
   - `music_ops_subgraph -> result_verifier`
   - `playback_subgraph -> result_verifier`
4. `result_verifier` 只能使用 conditional edges，不得同时增加普通出边。
5. 路由值限定为：
   - `retry_music_ops`
   - `retry_playback`
   - `music_done`
   - `playback_done`

条件边映射：

```python
{
    "retry_music_ops": "music_ops_subgraph",
    "retry_playback": "playback_subgraph",
    "music_done": "memory_sync",
    "playback_done": "finalizer",
}
```

## 6. Artifact Schema

### 6.1 文件位置

新增：

```text
app/schemas/__init__.py
app/schemas/artifacts.py
```

放在 `app/schemas` 而不是 Agent 包内，避免 FastAPI 端点导入 Schema 时触发 `music_team_v3_1.__init__` 中的 graph 初始化。

### 6.2 `PlayMusicArtifact`

目标字段：

```python
class PlayMusicArtifact(BaseModel):
    type: Literal["play_music"] = "play_music"
    song_mid: str = Field(min_length=1)
    title: str = Field(min_length=1)
    artist: str = ""
    url: str = Field(min_length=1)
    cover: str = ""
    description: str = "已获取播放链接"
```

约束：

- `url` 必须以 `http://` 或 `https://` 开头。
- `cover` 允许空字符串；非空时必须是 HTTP(S) URL。
- `song_mid` 和 `title` 去除首尾空格后不能为空。
- `extra="forbid"`，防止输出未知协议字段。

成功示例：

```json
{
  "type": "play_music",
  "song_mid": "0039MnYb0qxYhV",
  "title": "晴天",
  "artist": "周杰伦",
  "url": "https://example.com/song.mp3",
  "cover": "https://example.com/cover.jpg",
  "description": "已获取播放链接"
}
```

### 6.3 `PlaylistTrack`

```python
class PlaylistTrack(BaseModel):
    index: int = Field(ge=1)
    song_mid: str = Field(min_length=1)
    title: str = Field(min_length=1)
    artist: str = ""
    cover: str = ""
```

约束：

- `song_mid` 和 `title` 去除首尾空格后不能为空。
- `cover` 与播放器 Schema 使用相同 URL 规则。
- 同一页中 `index` 不得重复。
- 同一页中 `song_mid` 不得重复。

### 6.4 `PlaylistBrowserArtifact`

```python
class PlaylistBrowserArtifact(BaseModel):
    type: Literal["playlist_browser"] = "playlist_browser"
    playlist_name: str = Field(min_length=1)
    dirid: int | None = Field(default=None, gt=0)
    tracks: list[PlaylistTrack] = Field(default_factory=list)
    page: int = Field(ge=1)
    page_size: int = Field(ge=1, le=50)
    total_song_num: int = Field(ge=0)
    has_more: bool
    description: str = ""
```

约束：

- `playlist_name` 去除首尾空格后不能为空。
- 允许空页，因此 `tracks=[]` 合法。
- `total_song_num` 不得小于当前 `tracks` 数量。
- `has_more` 由后端数据决定，不要求 verifier 自行猜测总页数。
- `extra="forbid"`。

### 6.5 Artifact Union 和解析帮助函数

提供：

```python
Artifact = Annotated[
    PlayMusicArtifact | PlaylistBrowserArtifact,
    Field(discriminator="type"),
]

def parse_artifact_text(text: str) -> PlayMusicArtifact | PlaylistBrowserArtifact | None: ...
def artifact_to_json(artifact: PlayMusicArtifact | PlaylistBrowserArtifact) -> str: ...
```

`parse_artifact_text` 规则：

1. 接受纯 JSON object。
2. 接受完整的单一 `json` 代码块。
3. 拒绝 JSON array。
4. 拒绝自然语言前后包裹 JSON。
5. 拒绝未知 `type`。
6. 任何解析或 Pydantic 校验错误返回 `None`，不抛到 API 层。

## 7. Artifact 接入点

### 7.1 `play_music_tool`

播放链接成功后先构造 `PlayMusicArtifact`：

```python
artifact = PlayMusicArtifact(...)
return ToolResult.success(
    message="已获取歌曲播放信息",
    data=artifact.model_dump(mode="json"),
).to_json()
```

Tool 不再手写未校验的 payload dict。

### 7.2 FastAPI 端点

以下端点使用 Artifact 作为 `response_model` 或在 return 前显式校验：

- `GET /api/v1/song/play-url`
- `GET /api/v1/playlist/{dirid}/tracks`

要求：

- 成功返回保持当前 JSON 字段，不增加 ToolResult 外层。
- OpenAPI 文档能显示完整 Artifact Schema。
- 非法内部数据不得以 200 返回到前端。
- 现有前端无需修改解析流程。
- `/song/play-url` 未传 title 时使用“未知歌曲”作为展示兜底，避免非空 Schema 破坏现有只传 song_mid 的请求。
- `HTTPException` 必须从 FastAPI 导入，不得使用 `http.client.HTTPException`。

### 7.3 Playback Agent 最终输出

Playback Prompt 保留“成功时只输出 Artifact JSON”的规则，并补充：

- 不得增加 Schema 之外的字段。
- 歌曲播放必须包含 `song_mid/title/url`。
- 歌单浏览必须包含完整分页字段。
- 可以输出纯 JSON 或单一 JSON 代码块，不得附加解释。

### 7.4 Verifier 规范化

当 verifier 判定当前轮应输出 Artifact 时：

1. 读取最后一条 Playback AIMessage。
2. 调用 `parse_artifact_text`。
3. 校验成功：
   - 将 Artifact 保存到 `extensions.last_artifact`；
   - 用 `artifact_to_json()` 生成纯 JSON；
   - 使用相同 message id 更新 AIMessage，使 `add_messages` reducer 替换原消息；
   - `task.status=done`。
4. 校验失败：
   - 生成 `ARTIFACT_INVALID` ToolResult；
   - 判断是否允许一次 playback retry；
   - retry 不允许或已耗尽时，将最终回复替换为简短错误文本，避免前端展示损坏 JSON。

## 8. ToolResult 扩展

在 `ToolResultCode` 中新增：

```python
ARTIFACT_INVALID = "ARTIFACT_INVALID"
```

语义：工具执行可能成功，但最终 Artifact 缺字段、字段类型错误、URL 非法或不是纯 JSON。

规则：

- `ok=false`。
- 对只读 playback 流程可设置 `retryable=true`。
- 如果当前轮存在写工具，强制 `retryable=false`。
- retry 耗尽后保留 `ARTIFACT_INVALID`，不新增另一套错误码。

同时将 `get_playlist_detail_tool` 迁移为 ToolResult：成功时 `data` 直接符合 `PlaylistBrowserArtifact`，上游失败返回可重试的 `UPSTREAM_ERROR`。这样 verifier 能区分“查询失败”和“查询成功但最终 Artifact 损坏”。

## 9. 当前工具执行摘要

### 9.1 State 结构

在 `extensions` 中保存：

```python
extensions["current_tool_run"] = [
    {
        "tool_name": "search_music_tool",
        "tool_call_id": "call_xxx",
        "protocol_valid": True,
        "result": {
            "ok": True,
            "code": "SUCCESS",
            "message": "搜索完成",
            "data": {},
            "retryable": False,
        },
    }
]
```

规则：

- 每次进入 executor 后覆盖 `current_tool_run`，不跨执行尝试累加。
- 收集当前轮最后一个 HumanMessage 之后的全部 ToolMessage。
- 旧工具的 `result` 为 `None`、`protocol_valid=false`，但保留 `tool_name`。
- 不保存完整 ToolMessage 文本、Cookie、Credential 或异常栈。
- `last_tool_result` 继续保留，表示当前执行尝试的最后一个已迁移工具结果。

### 9.2 工具集合

新增 utils：

```python
def extract_current_tool_run(messages: list[Any]) -> list[dict[str, Any]]: ...
def current_tool_names(state: MusicGraphStateV31) -> set[str]: ...
def current_run_has_write_tool(state: MusicGraphStateV31) -> bool: ...
```

Retry 安全判断必须使用 `current_tool_run`，不能只看 `last_tool_result`。

## 10. `last_search_results`

### 10.1 保存位置

```python
extensions["last_search_results"]
```

该数据属于 thread-scoped 短期状态。Phase 2 仍使用当前 checkpointer；Phase 3 更换 SQLite 后自然获得跨重启恢复能力。

### 10.2 数据结构

只保存 `search_type=SONG` 的结果，并统一字段名：

```python
{
    "keyword": "周杰伦 夜跑",
    "search_type": "SONG",
    "count": 5,
    "items": [
        {
            "index": 1,
            "song_id": 123456,
            "song_mid": "0039MnYb0qxYhV",
            "title": "晴天",
            "artist": "周杰伦",
            "album": "叶惠美",
        }
    ],
}
```

约束：

- 最多保存 20 首。
- 必须包含有效 `index`、`song_mid` 和 `title`。
- `singer` 标准化为 `artist`，`mid` 标准化为 `song_mid`，`id` 标准化为 `song_id`。
- 不保存播放 URL。
- 不保存原始 Service 响应。

### 10.3 更新和清理规则

Verifier 在每个执行尝试中检查 `current_tool_run`：

1. 找到最后一次 `search_music_tool` 调用。
2. 如果 ToolResult 成功且 `search_type=SONG`：清洗并覆盖 `last_search_results`。
3. 如果歌曲搜索失败、协议无效或清洗后没有合法歌曲：删除旧 `last_search_results`，避免引用过期列表。
4. 如果本轮没有调用搜索工具：保留上一轮结果。
5. 如果搜索类型不是 `SONG`：删除旧 `last_search_results`，避免“第 N 首”错误引用歌手、专辑或歌单结果。

### 10.4 注入 Agent 上下文

`build_runtime_messages` 在 `executor` 和 `playback` 角色中增加一个精简 SystemMessage：

```text
LAST_SEARCH_RESULTS_JSON:
{...}

规则：
- 用户说“第N首/刚才第N首”时，只能使用该列表对应项。
- index 超出范围时向用户说明，禁止猜测。
- 已有 song_mid 时无需重新搜索。
```

不实现额外的中文序数 NLP 解析器，不增加槽位系统。

## 11. Result Verifier 行为

### 11.1 节点签名

```python
async def result_verifier_node(state: MusicGraphStateV31) -> MusicGraphStateV31:
    ...

def route_after_verifier(state: MusicGraphStateV31) -> str:
    ...
```

Verifier 不调用 LLM。

### 11.2 处理顺序

每次进入 verifier，严格按以下顺序执行：

1. 读取 `current_tool_run`、`last_tool_result`、`task.intent` 和 retry 状态。
2. 更新或清理 `last_search_results`。
3. 如果是直接加歌 `WRITE_UNCERTAIN`，执行一次只读后置验证。
4. 如果当前 playback 结果应产生 Artifact，执行 Artifact 校验和规范化。
5. 根据最终 ToolResult、Artifact 状态、写工具记录和 retry 次数决定是否 retry。
6. 写入 `extensions.verification`。
7. 设置 `control.verifier_route`。

### 11.3 Verification 记录

```python
extensions["verification"] = {
    "status": "passed | failed | inconclusive | skipped",
    "code": "SUCCESS | WRITE_UNCERTAIN | ARTIFACT_INVALID | ...",
    "message": "简短说明",
    "retry_scheduled": False,
    "retry_count": 0,
}
```

不得写入完整异常栈。

## 12. 直接加歌后置验证

### 12.1 触发条件

仅当以下条件全部满足时触发：

- 当前最后相关工具是 `add_songs_to_playlist_tool`；
- `last_tool_result.code=WRITE_UNCERTAIN`；
- `data.dirid` 有效；
- `data.song_ids` 非空。

### 12.2 Service 调整

`playlist_service.get_all_songs_in_playlist` 调整为允许：

```python
await get_all_songs_in_playlist(songlist_id=0, dirid=dirid)
```

并确保返回歌曲包含：

```python
{"id": ..., "mid": ..., "title": ...}
```

同时在普通 `get_playlist_detail` 的瘦身歌曲中补充 `id`，保持后续验证数据一致。

`qqmusic-api-python==0.6.0` 的全量分页必须先调用 `client.songlist.get_detail(...)` 得到 request，再使用 `async for detail in request.paginate()` 聚合 `detail.songs`；不得调用旧版的 `get_detail.all_pages_items`。

### 12.3 验证规则

读取目标歌单全部歌曲 ID：

- 请求的 song_ids 全部存在：
  - 将 `last_tool_result` 改为 `SUCCESS`；
  - message 为“加歌结果已通过查询确认”；
  - `task.status=done`；
  - verification 为 `passed`。
- 仅部分存在：
  - 将结果改为 `PARTIAL_SUCCESS`；
  - data 写入 `verified_song_ids` 和 `missing_song_ids`；
  - `task.status=failed`；
  - verification 为 `failed`。
- 全部不存在、查询失败或数据不足：
  - 保留 `WRITE_UNCERTAIN`；
  - verification 为 `inconclusive`；
  - 禁止重试写操作。

说明：已经存在于歌单中的歌曲也满足“目标歌曲在歌单中”这一后置条件。本阶段不区分“本轮新增”和“此前已存在”。

### 12.4 不验证的写场景

- `create_playlist_tool` 的不确定结果只有名称，没有创建前快照，可能与旧同名歌单混淆，因此不自动升级为成功。
- `add_by_keyword_to_playlist_tool` 已经在 Service 内做写后查询，不重复请求。
- 删除歌单和移除歌曲尚未迁移 ToolResult，本阶段不增加验证逻辑。

## 13. Artifact 期望判断

不要因为 `task.intent=playback` 就强制所有回复必须是 Artifact，否则自然追问会被误判。

规则：

1. 当前工具包含 `play_music_tool` 且最后结果成功：期望 `PlayMusicArtifact`。
2. 当前工具包含 `get_playlist_detail_tool`，且之后没有成功的 `play_music_tool`：期望 `PlaylistBrowserArtifact`。
3. 最终 AI 文本本身是 Artifact JSON：即使没有上述工具，也执行 Schema 校验。
4. 当前轮没有调用工具，或只查询了歌单列表/搜索结果并进行自然追问：Artifact 可选。
5. 最后 ToolResult 已失败：不要求 Artifact，保留真实失败回复。

如果期望类型和实际类型不同，按 `ARTIFACT_INVALID` 处理。

## 14. 一次性 Retry

### 14.1 State 字段

在 `RuntimeControl` 增加：

```python
retry_count: int
max_retries: int
retry_reason: str
retry_tool_name: str
retry_artifact_type: str
verifier_route: Literal[
    "retry_music_ops",
    "retry_playback",
    "music_done",
    "playback_done",
]
```

`extensions.retry_original_result` 保存进入 retry 前的 ToolResult 普通 dict。非 Artifact retry 完成后，必须看到 `retry_tool_name` 对应的新合法 ToolResult；如果 Agent 没有重新调用失败工具，恢复原始失败，禁止仅凭自然语言把失败洗成成功。`ARTIFACT_INVALID` retry 可以只修正最终 JSON，但必须继续校验原期望 Artifact 类型。

### 14.2 初始化

每次新用户请求经过 `init_memory_node` 时：

```python
control["retry_count"] = 0
control["max_retries"] = 1
control.pop("retry_reason", None)
control.pop("retry_tool_name", None)
control.pop("retry_artifact_type", None)
control.pop("verifier_route", None)
extensions.pop("current_tool_run", None)
extensions.pop("verification", None)
extensions.pop("retry_original_result", None)
```

不得删除 `last_search_results`。

### 14.3 Retry 决策

伪代码：

```python
can_retry = (
    retry_count < max_retries
    and retryable_failure
    and not current_run_has_write_tool(state)
    and task.intent in {"music_ops", "playback"}
)
```

允许 retry 时：

- 先递增 `retry_count`；
- 保存 `retry_reason`；
- `task.status=running`；
- 根据 intent 设置 `verifier_route`；
- 不新增 HumanMessage；
- 不执行 sleep；
- 不改变用户原始 goal。
- `music_ops` retry 使用只读 executor，不向模型注册任何写工具。

第二次仍失败时：

- 不再 retry；
- 保留原始失败 code；
- `task.status=failed`；
- verification 记录 `retry_scheduled=false` 和 `retry_count=1`。

### 14.4 Retry 上下文

`build_runtime_messages` 在 retry 时增加：

```text
RETRY_CONTEXT:
- 这是本轮唯一一次重试。
- 原因：{retry_reason}
- 只重试失败的读取/播放步骤。
- 不得调用任何写工具。
- 不得扩大用户原始任务。
```

这只是约束模型行为，真正的安全边界仍由 verifier 的写工具检测和最大次数保证。

`RETRY_CONTEXT` 必须放在输入消息末尾，避免上一条 executor 失败回复成为最后消息后让模型误以为任务已经结束。

### 14.5 与旧重入计数的关系

现有 `executor_reentry/max_reentry` 暂时保留，避免扩大本阶段改动；新 retry 不依赖这两个字段。后续可以统一清理，但不得让旧 supervisor guard 阻止 verifier 直接回到 executor。

## 15. Trace 接入

修改 `app/api/v1/endpoints.py`：

1. `TRACE_NODE_NAMES` 增加 `result_verifier`。
2. `NON_LLM_TRACE_FIELDS` 为 verifier 增加：
   - `verification_status`
   - `verification_code`
   - `retry_scheduled`
   - `retry_count`
   - `verifier_route`
3. `_build_non_llm_trace_summary` 从 `extensions.verification` 和 `control` 读取字段。

示例 trace：

```json
{
  "verification_status": "failed",
  "verification_code": "UPSTREAM_ERROR",
  "retry_scheduled": true,
  "retry_count": 1,
  "verifier_route": "retry_playback"
}
```

前端 trace 结构保持不变，不需要新增组件。

## 16. 失败处理矩阵

| 场景 | Verifier 行为 | 是否 retry | 最终状态 |
|---|---|---:|---|
| 搜索成功 | 保存 last_search_results | 否 | done |
| 搜索上游暂时失败，retryable=true | 回到原 executor | 最多一次 | running/failed |
| 搜索无结果 | 清理 last_search_results | 否 | failed |
| 播放 URL 上游暂时失败 | 回到 playback | 最多一次 | running/failed |
| 无版权播放 | 保留 PLAYBACK_UNAVAILABLE | 否 | failed |
| 播放 Artifact 合法 | 规范化为纯 JSON | 否 | done |
| 播放 Artifact 非法 | 安全时回到 playback | 最多一次 | running/failed |
| 直接加歌 WRITE_UNCERTAIN，歌曲全部存在 | 查询确认后改 SUCCESS | 否 | done |
| 直接加歌仅部分存在 | 改 PARTIAL_SUCCESS | 否 | failed |
| 直接加歌无法确认 | 保留 WRITE_UNCERTAIN | 否 | failed |
| 创建歌单 WRITE_UNCERTAIN | 保持不确定 | 否 | failed |
| 当前轮执行过任意写工具 | 禁止重新执行 Agent | 否 | done/failed |
| 旧工具返回文本 | 保持兼容，按最终回复处理 | 否 | done |

## 17. 实现影响范围

| 文件 | 变更 |
|---|---|
| `app/schemas/__init__.py` | 导出 Artifact Schema |
| `app/schemas/artifacts.py` | 新增两个 Artifact 和解析帮助函数 |
| `app/tools/tool_result.py` | 新增 `ARTIFACT_INVALID` |
| `app/tools/song_tools.py` | 使用 `PlayMusicArtifact` 构造成功数据 |
| `app/tools/playlist_tools.py` | 歌单详情工具迁移 ToolResult/PlaylistBrowserArtifact |
| `app/services/music/playlist_service.py` | 查询结果补 song id，支持按 dirid 获取全量歌曲 |
| `app/agents/music_team_v3_1/state.py` | 增加 retry、verifier 和上下文类型 |
| `app/agents/music_team_v3_1/agents.py` | 新增不注册写工具的 music retry executor |
| `app/agents/music_team_v3_1/utils.py` | 提取 current_tool_run、写工具判断、搜索上下文注入 |
| `app/agents/music_team_v3_1/nodes.py` | 新增 verifier 和 retry 决策 |
| `app/agents/music_team_v3_1/graph.py` | 插入 verifier 和条件循环 |
| `app/agents/music_team_v3_1/prompts.py` | 补充 Artifact 和 retry 约束 |
| `app/api/v1/endpoints.py` | API response schema 和 verifier trace |
| `requirements.txt` | 显式声明核心 LangChain/LangGraph/Pydantic 版本范围 |
| `tests/schemas/test_artifacts.py` | Artifact Schema 测试 |
| `tests/agents/test_result_verifier.py` | verifier、retry、search context 测试 |
| `tests/api/test_artifact_endpoints.py` | 端点响应协议测试 |

## 18. 推荐实现顺序

1. 新增 Artifact Schema 和独立测试。
2. 让播放 Tool 和两个 FastAPI 端点使用 Schema。
3. 扩展 state 和 utils，记录 `current_tool_run`。
4. 实现 `last_search_results` 清洗、保存和上下文注入。
5. 实现 verifier 的基础状态判断和 Artifact 校验。
6. 实现直接加歌只读后置验证。
7. 实现一次性 retry 决策、只读 retry executor 和 retry 结果证明。
8. 修改 graph 条件边。
9. 接入 trace。
10. 补齐 verifier、图路由、API 测试。
11. 运行 Phase 1 的 53 个回归测试和本阶段新增测试。

## 19. 测试要求

### 19.1 Artifact Schema

- 合法播放 Artifact 可完成 JSON round-trip。
- 播放 URL 非 HTTP(S) 时校验失败。
- 空 song_mid、空 title 校验失败。
- cover 为空合法，非法非空 URL 校验失败。
- 合法歌单 Artifact 可完成 JSON round-trip。
- 非法 page/page_size/index 校验失败。
- 重复 index 或 song_mid 校验失败。
- 未知字段校验失败。
- 纯 JSON 和单一代码块可以解析。
- 带自然语言前后缀的 JSON 被拒绝。

### 19.2 `last_search_results`

- SONG 搜索成功后保存标准化结果。
- 最多保存 20 首。
- mid 为空的项目被丢弃。
- 歌曲搜索失败后清理旧结果。
- 非 SONG 搜索后清理旧结果。
- 未调用搜索时保留旧结果。
- playback/executor Prompt 能看到精简结果。
- index 超出范围的 Prompt 规则明确禁止猜测。

### 19.3 Verifier

- 合法 ToolResult 成功时通过。
- 非法 Artifact 生成 `ARTIFACT_INVALID`。
- Artifact 校验成功后最终 AIMessage 是纯 JSON。
- 规范化时保持原 message id。
- 直接加歌不确定但歌曲全部存在时改为 SUCCESS。
- 仅部分歌曲存在时改为 PARTIAL_SUCCESS。
- 查询失败时保留 WRITE_UNCERTAIN。
- create playlist 不确定不会被错误升级为成功。

### 19.4 Retry

- retryable 搜索失败只 retry 一次。
- retryable 播放失败只 retry 一次。
- 第二次失败后正确终止。
- `ARTIFACT_INVALID` 在安全 playback 流程中只 retry 一次。
- 当前轮调用过写工具时绝不 retry。
- `WRITE_UNCERTAIN`、`PARTIAL_SUCCESS`、`NOT_FOUND` 不 retry。
- retry 不新增 HumanMessage。
- 每次新用户请求 retry_count 重置为 0。
- 图循环不会触发 recursion limit。

### 19.5 API 和回归

- 两个 Artifact API 成功响应符合 Pydantic Schema。
- API 字段与现有前端 TypeScript 类型兼容。
- trace 包含 verifier 信息。
- Phase 1 的全部 53 个测试继续通过。
- 所有测试 mock Service/Agent，不访问真实 QQ 音乐和模型 API。

## 20. 验收标准

完成本 Spec 必须同时满足：

1. 两条执行路径都经过 `result_verifier`。
2. 图中 retry 循环具有明确的 `retry_count < 1` 终止条件。
3. 任意包含写工具的执行尝试都不会自动 retry。
4. `ToolResult.retryable=true` 的安全读取失败最多重试一次。
5. 播放和歌单 Artifact 由 Pydantic 校验，前端只收到规范纯 JSON。
6. Artifact 校验失败不会以损坏 JSON 继续返回前端。
7. “播放第 N 首”能从 thread state 中获得上一次歌曲搜索引用。
8. 新搜索失败后不会继续引用过期列表。
9. 直接加歌不确定时只做只读查询，不重复写入。
10. Verifier 状态和 retry 次数可在 trace 中查看。
11. Phase 1 测试与本阶段新增测试全部通过。
12. 未引入新的 Agent、槽位系统、SQLite 或用户长期记忆。

## 21. 参考

- LangGraph Graph API：条件边用于根据 state 做动态路由；同一节点不要混用普通出边和动态路由。
  - https://docs.langchain.com/oss/python/langgraph/graph-api
- LangGraph Fault Tolerance：RetryPolicy 针对节点异常重跑；本项目的 ToolResult 业务失败使用显式 verifier 循环处理。
  - https://docs.langchain.com/oss/python/langgraph/fault-tolerance
- LangGraph `add_messages`：使用相同 message id 更新消息时会替换原消息，适合 Artifact 规范化。
  - https://docs.langchain.com/oss/python/langgraph/graph-api
