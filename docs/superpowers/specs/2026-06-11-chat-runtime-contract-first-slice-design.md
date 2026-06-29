# 本地聊天运行时合同第一执行切片设计

> Status: Source updated, pending verification
>
> Date: 2026-06-11
>
> Parent direction: [上下文优先级、记忆治理与工作流体验优化设计](2026-06-11-context-memory-workflow-design.md)
>
> Related: [确定性动作与结构化 Artifact 优化规格](../../SDD/spec/deterministic-action-and-artifact-spec.md)

## Background

`docs/superpowers/specs/2026-06-11-context-memory-workflow-design.md` 是主链路治理总纲，覆盖上下文优先级、
记忆治理、Graph 生命周期、API 合同、前端工作流、持久化和可观测性。该总纲方向正确，但一次性实现范围过大。

当前更适合先交付一个可验证的第一切片：让本地聊天请求稳定返回、错误可诊断、Artifact 不再靠纯文本猜测、
Graph 消息累积风险被测试锁住，并为后续 `ContextEnvelope` 和记忆治理打底。

近期运行时复现也暴露了一个具体问题：前端显示 `Failed to fetch`，但根因是后端 Agent 调用失败，例如次级模型名
被写死为目标服务不支持的 `gpt-4o-mini`，FastAPI 返回未被前端稳定消费的异常响应。这个问题说明第一切片必须先
收紧“运行时配置 + API 错误响应 + 前端错误展示”合同，否则更大的 Graph/记忆改造会缺少可靠反馈。

## Goals

1. 本地聊天接口在 Agent、模型或上游服务失败时返回稳定 JSON 错误，不让前端只看到模糊的 `Failed to fetch`。
2. LLM 模型名从环境变量读取，避免把某个供应商模型硬编码进代码路径。
3. `/api/v1/chat/local` 在保持旧 `reply` 和 `trace` 兼容的同时，新增一等 `artifacts` 和最小 `run` 字段。
4. 播放器和歌单 Artifact 由后端校验后返回，前端优先消费 `data.artifacts`，旧文本 JSON 解析只作为历史兼容。
5. 修复并测试 `add_messages` reducer 使用方式：节点只返回新增消息 delta，不返回旧消息加新消息的完整列表。
6. 保留当前 UI 确定性 API：歌单翻页、点击播放、音频控制继续绕开 LLM。
7. 不在本切片恢复或扩展通用 slots；工具 schema 继续承担工具参数合同。
8. 为后续 `ExecutionOutcome`、`ContextEnvelope` 和记忆治理提供最小状态与测试基线。

## Non-goals

- 不实现完整 `ContextEnvelope` token 预算和 profile 相关性检索。
- 不迁移 `user_profile.md` 到结构化 facts store。
- 不替换 `InMemorySaver`，不引入 SQLite、Redis 或新的持久化基础设施。
- 不实现流式 SSE、取消、幂等副作用恢复或服务重启后的权威会话恢复。
- 不一次性合并 `MusicExecutor`、`PlayAgent` 和 `ChatReplier`。
- 不重写 QQ 音乐认证、服务层或工具内部实现。
- 不把点击播放、暂停、拖动进度、歌单翻页改成聊天请求。
- 不把 trace 设计成稳定业务协议；trace 仍是调试信息。

## Current Constraints

- 活跃 Graph 仍是 `app.agents.music_team_v3_1:graph`。
- 当前聊天 API 是 `POST /api/v1/chat/local`，内部使用 `graph.astream(..., stream_mode="updates")`。
- 前端活跃页面是 `/chat/local`，`/chat/online` 已重定向到 `/chat/local`。
- 当前前端 `features/chat-local` 只消费 `reply` 和 `trace`，Artifact 主要从助手文本中解析。
- `messages` 字段使用 LangGraph `add_messages` reducer，但部分节点返回完整消息列表。
- 工具型 Agent 和 LLM 在模块导入时创建，测试注入替身需要先引入小型适配点或 monkeypatch。
- `.env` 不应提交；可提交的是 `.env.example` 和代码对环境变量的读取。

## User-visible Behavior

### 普通聊天成功

用户发送普通消息后，前端展示助手回复；接口返回：

```json
{
  "status": "success",
  "data": {
    "thread_id": "local-web-thread",
    "reply": "你好，有什么可以帮你的吗？",
    "artifacts": [],
    "run": {
      "status": "succeeded",
      "error": null
    },
    "trace": []
  }
}
```

### Agent 或模型失败

如果模型、网络或 Graph 节点失败，接口返回稳定错误。前端应显示可读错误，而不是只显示 `Failed to fetch`。

```json
{
  "status": "error",
  "message": "Agent 服务调用失败，请检查模型配置或后端日志。",
  "data": {
    "thread_id": "local-web-thread",
    "artifacts": [],
    "run": {
      "status": "failed",
      "error": {
        "code": "agent_upstream_error",
        "message": "Agent 服务调用失败，请检查模型配置或后端日志。"
      }
    }
  }
}
```

HTTP 状态可以是 `502`，但响应体必须可被前端解析。后端日志记录异常类型和 `thread_id`，不得返回 API key、
完整 system prompt、原始 profile 或堆栈给前端。

### 自然语言产生 Artifact

用户输入“播放周杰伦的晴天”时，后端可以继续让 Agent 调用工具；成功后：

- `reply` 是自然语言说明。
- `artifacts` 包含经过校验的 `play_music` payload。
- 前端即使 `reply` 中没有 JSON，也能渲染播放器。

### UI 确定性播放不变

用户在歌单卡片中点击播放仍调用：

```text
GET /api/v1/song/play-url?song_mid=...&title=...&artist=...
```

该路径不经过 `/chat/local`、LangGraph 或 LLM。

## Design

### 1. Runtime configuration

`app/agents/music_team_v3_1/config.py` 读取两个模型名：

```python
MODEL_NAME = os.getenv("MUSIC_AGENT_MODEL", "glm-4.5-air")
SECONDARY_MODEL_NAME = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
```

`llm0` 使用 `SECONDARY_MODEL_NAME`，`llm1` 使用 `MODEL_NAME`。默认值仅作为本地 fallback；
实际部署必须通过 `.env` 或环境变量选择供应商支持的模型。

`.env.example` 应说明：

- `OPENAI_MODEL`：次级模型，用于 intent parser、summary、profile、chat replier 等当前 `llm0` 路径。
- `MUSIC_AGENT_MODEL`：主音乐工具 Agent 模型。

### 2. Chat API response contract

新增响应字段，但保留旧字段：

```python
class RunError(BaseModel):
    code: str
    message: str

class RunInfo(BaseModel):
    status: Literal["succeeded", "failed"]
    error: RunError | None = None

class LocalChatData(BaseModel):
    thread_id: str
    reply: str = ""
    artifacts: list[dict[str, Any]] = []
    run: RunInfo
    trace: list[LocalTraceEvent] = []
```

迁移期内前端仍可读取 `reply` 和 `trace`。新逻辑必须优先使用 `artifacts`。

### 3. Artifact validation

后端定义最小 Artifact 模型，复用现有 SDD 字段：

```python
class PlayMusicArtifact(BaseModel):
    type: Literal["play_music"]
    song_mid: str | None = None
    title: str | None = None
    artist: str | None = None
    url: str
    cover: str | None = None
    description: str | None = None

class PlaylistBrowserArtifact(BaseModel):
    type: Literal["playlist_browser"]
    playlist_name: str
    dirid: int | None = None
    tracks: list[PlaylistTrack]
    page: int
    page_size: int
    total_song_num: int
    has_more: bool
    description: str | None = None
```

解析规则：

1. 只接受白名单 `type`。
2. 只使用 JSON parser 和 Pydantic 校验。
3. 校验失败的 payload 不进入 `artifacts`。
4. 不从 trace 读取业务 Artifact。
5. 第一切片允许从工具结果和最终 AI 文本中做迁移兼容提取，但提取结果必须进入后端校验模型后才返回。

### 4. Graph state and reducer discipline

第一切片不重写完整 Graph，但必须修复消息 delta 纪律：

```python
return {**state, "messages": [ai_msg], "task": task, "control": control}
```

禁止在 `messages` reducer 字段返回：

```python
return {**state, "messages": [*messages, ai_msg]}
```

如果节点需要读取历史消息，应通过 `extract_messages(state)` 读取，但返回值只包含新增 delta。

第一切片可以增加轻量字段：

```python
class MusicGraphStateV31(TypedDict, total=False):
    artifacts: list[dict[str, Any]]
    outcome: dict[str, Any]
```

`outcome` 只用于统一 API 状态和错误，不承担完整长期工作流语义。

### 5. Frontend rendering contract

前端 `ChatMsg` 增加：

```ts
type ChatArtifact = PlayMusicPayload | PlaylistBrowserPayload;

type ChatMsg = {
  role: "user" | "assistant";
  content: string;
  ts: number;
  artifacts?: ChatArtifact[];
  trace?: TraceItem[];
};
```

渲染优先级：

1. 如果 `message.artifacts` 非空，渲染这些结构化 Artifact。
2. 如果 `message.artifacts` 为空，才对历史消息执行旧文本 JSON 兼容解析。
3. 新响应不得依赖 trace 触发播放器。
4. 未知 Artifact 类型忽略或显示普通附件占位，不导致页面崩溃。

### 6. Error mapping

第一切片只定义少量稳定错误码：

| Code | Trigger | HTTP |
| --- | --- | --- |
| `invalid_request` | 空消息或参数不合法 | 400 |
| `agent_upstream_error` | LLM、Graph、外部模型服务异常 | 502 |
| `agent_timeout` | 后端执行超时 | 504 |
| `internal_error` | 未分类内部错误 | 500 |

错误响应体必须包含 `status="error"`、用户可读 `message` 和 `run.status="failed"`。

## Security and Reliability

- 不把 API key、QQ 凭证、LangSmith key、system prompt、profile 原文或完整堆栈返回给前端。
- 后端日志可以记录异常类型、`thread_id`、节点名和错误码，但不记录完整用户私密历史。
- Artifact URL 必须来自 QQ 音乐服务层或受信任工具结果；前端传入 URL 不可作为可信 Artifact。
- `trace` 继续作为开发调试信息；后续生产环境可关闭或降采样。
- 模型配置错误必须表现为稳定错误响应，不得导致浏览器 CORS 层面的 `Failed to fetch`。
- 第一切片不自动重试有副作用工具。

## Compatibility and Migration

- `/api/v1/chat/local` 保留旧 `reply` 和 `trace` 字段。
- 前端保留旧文本 JSON parser 作为历史消息兼容路径。
- `GET /api/v1/song/play-url` 和 `GET /api/v1/playlist/{dirid}/tracks` 响应不变。
- `/chat/online` 继续重定向到 `/chat/local`。
- `.env` 不提交；`.env.example` 增加模型变量说明。
- 本切片完成后，`docs/current/ARCHITECTURE.md` 才能更新当前机制；计划阶段不提前改当前事实。

## Alternatives

### 直接实现完整 ContextEnvelope

暂不采用。当前运行时错误、Artifact 合同和 reducer 风险尚未稳定；先做第一切片能减少后续大改的噪声。

### 只修模型名，不改 API 错误合同

拒绝。模型名只是这次触发因素，任何 Agent 异常都可能让前端收到不可读失败。必须让错误响应成为稳定合同。

### 继续让前端解析 AI 文本 JSON

拒绝作为目标方案。文本解析只适合历史兼容；新响应应由后端校验后返回 `artifacts`。

### 第一切片就删除 intent_parser

暂不作为必做项。第一切片先稳定运行时合同；删除或弱化 `intent_parser` 放入后续任务，避免同时改变路由行为、
Artifact 合同和错误处理。

## Acceptance Criteria

### Runtime and API

- `llm0` 模型名可通过 `OPENAI_MODEL` 配置。
- `llm1` 模型名可通过 `MUSIC_AGENT_MODEL` 配置。
- 模型配置错误或上游失败时，`/chat/local` 返回可解析 JSON 错误，而不是让前端只显示 `Failed to fetch`。
- 空消息返回稳定 `400` 或等价错误响应。
- 成功响应始终包含 `data.artifacts` 和 `data.run`。

### Artifact

- 后端能校验合法 `play_music` 和 `playlist_browser` payload。
- 缺少必填字段、未知 `type` 或非法 JSON 不进入 `artifacts`。
- 前端优先渲染 `data.artifacts`。
- `reply` 不包含 JSON 时，结构化播放器仍可显示。
- 旧文本 JSON 消息仍可兼容渲染。

### Graph

- 使用 `add_messages` reducer 的节点只返回新增消息 delta。
- 多轮调用不会因节点返回完整旧消息导致重复累积。
- `music_ops`、`playback` 和 `smalltalk` 至少都有稳定 `run.status` 映射。

### Frontend and Verification

- 普通聊天请求在浏览器中成功显示回复。
- 人为模拟 Agent 异常时，前端显示可读错误文本。
- 点击歌单播放不调用 `/chat/local`。
- `pnpm lint` 和 `pnpm build` 通过。
- 后端聚焦测试不访问真实 LLM 或 QQ 音乐公网。

## Open Questions

1. 第一切片的 Artifact collector 是否只读取工具消息，还是同时兼容最终 AI 文本中的 JSON？建议迁移期两者都支持，但只返回校验后的结果。
2. 是否立即新增前端测试依赖，还是先把 artifact 选择逻辑抽成纯函数并用现有 lint/build + 浏览器验收保护？
3. `trace` 在开发环境是否默认保留？如果生产部署，应另行增加配置开关。
4. `intent_parser` 是在第一切片末尾弱化，还是等 Artifact 合同稳定后再单独切片删除？
