# 确定性动作与结构化 Artifact 优化规格

## 1. 文档状态

- 状态：Draft
- 适用项目：MusicChatAgent
- 目标版本：下一次 Agent 主链路优化
- 关联实施计划：`docs/SDD/plan/deterministic-action-and-artifact-plan.md`

## 2. 背景

当前系统同时存在两类交互：

1. 用户在歌单、播放器等 UI 中点击按钮。
2. 用户通过自然语言提出“播放晴天”“打开我的歌单”等请求。

第一类交互已经采用确定性 REST API。例如，歌单中的播放按钮直接请求
`GET /api/v1/song/play-url`，后端返回歌曲播放地址，前端交给 `<audio>` 播放。这条链路不经过
LangGraph，也不依赖 LLM 判断意图。

第二类交互目前会先经过 `intent_parser`，由 LLM 输出 `intent`、`extracted_slots`、
`missing_slots` 和 `is_ready_to_execute`，再由 `supervisor_router` 选择执行节点。实际代码中：

- `required_slots` 始终为空。
- `missing_slots` 被强制写为空列表。
- `extracted_slots` 没有作为工具调用的可靠输入。
- 工具型 Agent 仍会自行理解用户文本并生成工具参数。
- 播放和歌单结果以 JSON 字符串混在 AI 文本中，前端需要再次猜测和解析。

因此，通用 slots 没有形成真正的数据契约，却增加了一次 LLM 调用、路由失败点和状态复杂度。

## 3. 目标

本次优化目标如下：

1. UI 明确操作继续使用确定性 API，不进入自然语言意图识别流程。
2. 自然语言请求由工具型 Agent 直接处理，工具参数作为唯一的结构化业务参数。
3. 移除主链路对通用 `intent` 和 `slots` 的强依赖。
4. 将播放器、歌单等可交互数据作为结构化 `artifacts` 返回，不再依赖前端从 AI 文本中提取 JSON。
5. 保持现有用户能力和旧消息渲染兼容，允许分阶段迁移。
6. 减少 LLM 调用次数和提示词耦合，提高播放链路的可测试性。

## 4. 非目标

本次优化不包含：

- 不为登录、搜索、歌单、播放分别建设完整单元测试体系。
- 不重做 QQ 音乐服务层和认证机制。
- 不在本阶段引入数据库或替换 `InMemorySaver`。
- 不实现新的推荐、收藏、歌词或播放队列能力。
- 不保证自然语言识别完全确定性；模糊语言仍由 LLM 理解。
- 不将所有 REST API 合并进 LangGraph。
- 不设计跨领域通用工作流引擎或通用 slot filling 框架。

## 5. 设计原则

### 5.1 明确操作不让 LLM 决策

当 UI 已经知道动作和实体标识时，直接调用对应 API：

| 用户操作 | 输入 | 调用方式 |
| --- | --- | --- |
| 点击歌曲播放 | `song_mid`、标题、歌手 | `GET /api/v1/song/play-url` |
| 歌单翻页 | `dirid`、页码 | `GET /api/v1/playlist/{dirid}/tracks` |
| 暂停、继续、拖动进度 | 当前播放器状态 | 浏览器本地 `<audio>` 操作 |

这些操作不得转换成聊天文本后再交给 Agent 判断。

### 5.2 工具参数代替通用 slots

自然语言场景中的结构化参数由具体工具 schema 定义，例如：

```python
play_music_tool(
    song_mid="0039MnYb0qxYhV",
    song_name="晴天",
    singer_name="周杰伦",
)
```

工具 schema 负责字段名称、必填约束和类型校验，不再在 Graph State 中重复维护
`required_slots`、`extracted_slots` 和 `missing_slots`。

### 5.3 文本与可交互数据分离

回复文本负责自然语言说明，`artifacts` 负责前端组件渲染。前端不得把任意回复文本当作可靠的业务协议。

## 6. 用户可见行为

### 6.1 UI 点击播放

行为保持不变：

1. 用户点击歌单中的播放按钮。
2. 前端使用歌曲 `song_mid` 请求播放地址。
3. 后端返回 `play_music` 数据。
4. 前端立即加载并播放音频。

此流程不调用 LangGraph 或 LLM。

### 6.2 自然语言播放

用户输入“播放周杰伦的晴天”时：

1. 聊天请求进入 LangGraph。
2. 工具型 Agent 根据上下文搜索歌曲并调用播放工具。
3. 后端从工具结果中提取 `play_music` artifact。
4. API 同时返回自然语言回复和结构化 artifact。
5. 前端根据 `artifact.type` 渲染播放器。

LLM 可以影响工具选择和参数生成，但不能决定 artifact 的最终结构。artifact 必须由后端校验后返回。

### 6.3 普通聊天

普通聊天允许由同一个工具型 Agent 直接回答而不调用工具。返回值中 `artifacts` 为空数组。

### 6.4 模糊或缺失信息

对于“播放第二首”“播放刚才那首”等请求，Agent 可使用最近的工具结果和会话消息解析引用。
无法可靠解析时，应在 `reply` 中询问用户，不引入全局 `missing_slots` 状态机。

## 7. 功能范围

### 7.1 范围内

- 简化 LangGraph 主链路，去掉强制的 LLM 意图预分类。
- 删除或停用 Graph State 中未发挥实际作用的通用 slots 字段。
- 为聊天 API 增加 `artifacts` 数组。
- 在后端集中校验并规范化 `play_music` 和 `playlist_browser` artifact。
- 前端优先从 API 的 `artifacts` 字段渲染组件。
- 兼容历史消息和迁移期内的文本 JSON。
- 建立覆盖“聊天请求到前端 artifact 渲染”的聚焦测试。

### 7.2 范围外

- UI 点击行为改为走聊天接口。
- 使用规则穷举所有自然语言意图。
- 为每种工具建立一套独立 intent/slot 定义。
- 允许前端直接信任未经校验的 LLM JSON。

## 8. 目标架构

### 8.1 UI 确定性动作

```text
用户点击播放
  -> 前端读取 song_mid
  -> FastAPI /song/play-url
  -> SongService
  -> QQ Music API
  -> PlayMusicArtifact
  -> HTMLAudioElement
```

### 8.2 自然语言动作

```text
用户聊天输入
  -> FastAPI /chat/local
  -> LangGraph 初始化会话/记忆
  -> 工具型 Agent
       -> 可选：search_music_tool
       -> 可选：play_music_tool / playlist tool
  -> Artifact 收集与校验
  -> 记忆同步
  -> API { reply, artifacts, trace }
  -> 前端文本与组件分别渲染
```

### 8.3 建议 Graph 流程

```text
START
  -> init_memory
  -> assistant_agent
  -> artifact_collector
  -> memory_sync
  -> finalizer
  -> END
```

`assistant_agent` 可以不调用工具并直接完成普通聊天，也可以根据自然语言调用音乐工具。
不再为每条消息先执行独立 `intent_parser`。

若一次性合并现有 Agent 风险过高，可以先保留现有执行节点，但将意图解析器改为非 LLM 的兼容路由，
随后再合并为单一工具型 Agent。最终状态仍以上述流程为目标。

## 9. 数据设计

### 9.1 Artifact 联合类型

建议后端定义明确的数据模型：

```python
class PlayMusicArtifact(BaseModel):
    type: Literal["play_music"]
    song_mid: str
    title: str
    artist: str = ""
    url: str
    cover: str = ""
    description: str = "已获取播放链接"


class PlaylistTrack(BaseModel):
    index: int
    song_mid: str
    title: str
    artist: str = ""
    cover: str = ""


class PlaylistBrowserArtifact(BaseModel):
    type: Literal["playlist_browser"]
    playlist_name: str
    dirid: int | None = None
    tracks: list[PlaylistTrack]
    page: int
    page_size: int
    total_song_num: int
    has_more: bool
    description: str = ""
```

### 9.2 Graph State

目标 State 只保留实际参与流程的数据：

```python
class MusicGraphState(TypedDict, total=False):
    thread_id: str
    messages: Annotated[list[BaseMessage], add_messages]
    memory: MemoryMeta
    control: RuntimeControl
    artifacts: list[dict[str, Any]]
    errors: list[dict[str, str]]
```

`task.intent`、`required_slots`、`extracted_slots`、`missing_slots` 不作为目标状态的一部分。
如果历史记录仍需要任务状态，可保留轻量的 `status` 和 `error_reason`，但不得驱动 slot filling。

### 9.3 聊天 API 响应

目标响应：

```json
{
  "status": "success",
  "data": {
    "thread_id": "local-web-thread",
    "reply": "已经为你找到《晴天》。",
    "artifacts": [
      {
        "type": "play_music",
        "song_mid": "0039MnYb0qxYhV",
        "title": "晴天",
        "artist": "周杰伦",
        "url": "https://isure.stream.qqmusic.qq.com/...",
        "cover": "https://y.qq.com/music/photo_new/...",
        "description": "已获取播放链接"
      }
    ],
    "trace": []
  }
}
```

无 artifact 时必须返回空数组，不使用 `null`：

```json
{"artifacts": []}
```

### 9.4 工具结果

工具可以继续返回 JSON 字符串以兼容 LangChain `ToolMessage`，但 JSON 必须先由后端模型生成：

```python
payload = PlayMusicArtifact(...)
return payload.model_dump_json()
```

`artifact_collector` 只接收受支持的 `type`，并通过对应 Pydantic 模型校验。无法解析或校验失败的内容
不得进入 `artifacts`，应记录到 `errors` 或 trace。

## 10. 前端渲染协议

前端聊天响应类型增加：

```ts
type ChatArtifact = PlayMusicArtifact | PlaylistBrowserArtifact;

type LocalChatResp = {
  status?: string;
  data?: {
    thread_id?: string;
    reply?: string;
    artifacts?: ChatArtifact[];
    trace?: TraceItem[];
  };
};
```

渲染优先级：

1. 优先渲染响应中的 `artifacts`。
2. 迁移期内，如果 `artifacts` 为空，可对旧消息执行一次文本 JSON 兼容解析。
3. 新响应不得依赖 trace 中的 JSON 来驱动用户组件。

兼容解析应标记为待删除逻辑，并在历史消息完成结构化存储后移除。

## 11. 权限与安全边界

- 播放 URL 和歌单接口继续使用当前 QQ 音乐凭证，不把凭证内容返回给前端。
- 后端不得接受前端传入的任意音频 URL作为可信播放结果。
- artifact 中的 URL 必须来自服务层或受信任工具结果。
- artifact 解析必须使用 JSON parser 和 Pydantic，不使用 `eval` 或字符串执行。
- trace 仅用于调试，不作为业务数据源；生产环境应考虑关闭或裁剪敏感内容。
- API 错误不得暴露 QQ 音乐凭证、LLM API Key 或完整内部异常堆栈。

## 12. 兼容性边界

- `GET /api/v1/song/play-url` 和 `GET /api/v1/playlist/{dirid}/tracks` 保持响应兼容。
- `/api/v1/chat/local` 只新增 `artifacts` 字段，旧前端忽略该字段仍可工作。
- 第一阶段保留文本 JSON 提取函数，用于历史消息和旧线程。
- 不要求迁移现有 `history.jsonl`；历史记录仍可按旧文本显示。
- 新产生的结构化 artifact 是否持久化由后续记忆存储 SDD 决定，本次仅保证当前响应可用。

## 13. 方案取舍

### 13.1 不采用通用 slots

原因：

- 现有工具 schema 已经承担参数约束。
- slots 仍需 LLM 提取，不能消除模型不确定性。
- 同一参数在 parser、state 和 tool schema 中重复定义，容易漂移。
- 当前产品没有复杂的表单式多轮收集需求。

未来只有在出现“必须逐字段收集并确认后才能执行”的高风险流程时，才为该具体流程建立领域模型，
而不是恢复全局通用 slots。

### 13.2 不使用大规模关键词规则替代 LLM

关键词规则对“播放”“暂停”等少量命令有效，但会在否定句、上下文引用和推荐请求中快速复杂化。
规则只适合协议级命令或 UI 已知动作，不适合作为完整自然语言路由器。

### 13.3 采用结构化 artifacts

相比从 AI 文本中提取 JSON，结构化字段：

- 可独立校验。
- 可稳定测试。
- 不受 LLM 附加说明文字影响。
- 可以逐步扩展新组件类型。

代价是后端需要增加 artifact 收集和类型模型，但该复杂度属于明确的数据契约，收益高于隐式文本协议。

## 14. 风险与缓解

| 风险 | 等级 | 缓解措施 |
| --- | --- | --- |
| 合并 Agent 后普通聊天风格变化 | P1 | 固定 assistant system prompt，并保留回归样例 |
| ToolMessage 中混入无关 JSON | P0 | 仅接受白名单 `type`，通过 Pydantic 校验 |
| artifact 已生成但最终回复节点丢失 | P0 | artifact 单独存入 State，不依赖最后一条 AIMessage |
| 前端同时渲染新 artifact 和旧文本 JSON | P1 | 有结构化 artifact 时禁用当前响应的兼容提取 |
| 旧历史消息无法结构化恢复 | P2 | 保留只读兼容 parser，不强制迁移历史文件 |
| 去掉 intent 后工具误调用 | P1 | 收紧工具描述、危险操作增加确认；播放和查询保持低风险 |
| LLM 或 QQ 音乐服务失败 | P1 | 返回可读错误文本，`artifacts=[]`，不得返回半合法 artifact |

## 15. 验收标准

### 15.1 UI 确定性链路

- 点击歌单中的播放按钮不会请求 `/chat/local`。
- 请求包含正确 `song_mid`。
- 合法播放响应能够设置 `<audio src>` 并尝试播放。
- 重复播放同一首歌可使用现有前端缓存。

### 15.2 自然语言链路

- `/chat/local` 响应始终包含 `data.artifacts` 数组。
- 普通聊天返回 `artifacts=[]`。
- 播放工具成功时返回一个通过校验的 `play_music` artifact。
- artifact 即使没有出现在 `reply` 文本中，前端仍能渲染播放器。
- 无效工具 JSON 不会触发前端播放器。

### 15.3 Graph 简化

- 正常聊天不再强制调用独立 `intent_parser` LLM。
- 主链路不依赖 `required_slots`、`extracted_slots` 或 `missing_slots`。
- “播放第二首”等上下文请求仍可由最近消息或工具结果处理；无法确定时返回澄清文本。

### 15.4 兼容性

- 现有直接播放和歌单翻页接口保持可用。
- 历史 AI 文本中的旧 `play_music`/`playlist_browser` JSON 仍可显示。
- 前端 lint 和 production build 通过。
- 后端聚焦测试在无真实 LLM、无真实 QQ 音乐网络请求的条件下可运行。

## 16. 可观测性

建议记录以下结构化信息，但不记录凭证和完整播放 URL：

- `thread_id`
- Agent 调用的工具名称
- artifact 类型和数量
- artifact 校验失败原因
- 请求耗时
- 外部服务错误类别

`intent_parser` trace 在迁移完成后删除；trace 不能继续作为前端 artifact 来源。
