# ToolResult 统一工具结果协议 Spec

## 1. 文档信息

- 状态：Implemented
- 优先级：P0
- 目标版本：Music Team v3.2 / Phase 1
- 依赖：现有 LangGraph、LangChain Tool、Pydantic v2
- 后续依赖本 Spec 的功能：`result_verifier`、一次性 retry、Artifact Schema、执行 Trace

## 2. 背景

当前工具返回值同时存在自然语言、业务 JSON 和异常文本三种形式，Agent 需要从文本中猜测执行结果。`music_ops_subgraph_node` 还会通过“失败、报错、异常”等关键词判断任务状态，存在以下问题：

1. 工具结果无法被程序稳定消费。
2. 自然语言中出现错误关键词时可能误判任务状态。
3. 写操作返回 `False` 或抛出异常时，`add_songs_to_playlist_tool` 会将其包装成成功，可能向用户报告不存在的执行结果。
4. 后续的验证、重试、监控无法基于明确的错误类型做路由。
5. 不同工具的成功数据结构不一致，前端和其他节点只能做特殊处理。

本阶段先建立统一工具边界，并改造最常用的搜索、播放、创建歌单和加歌链路。

## 3. 目标

### 3.1 必须完成

1. 新增统一的 `ToolResult` Pydantic 模型。
2. 所有纳入本阶段的工具均返回可被 `ToolResult` 校验的 JSON 字符串。
3. 改造以下核心工具：
   - `search_music_tool`
   - `play_music_tool`
   - `create_playlist_tool`
   - `add_songs_to_playlist_tool`
   - `add_by_keyword_to_playlist_tool`
4. 删除任何“异常或 False 等同于成功”的逻辑。
5. `music_ops_subgraph_node` 和 `playback_subgraph_node` 根据最后一个有效 `ToolResult` 设置任务状态，不再扫描自然语言关键词。
6. 将最后一个工具结果写入图状态，供下一阶段的 verifier 使用。
7. 添加不依赖 QQ 音乐网络和真实模型的单元测试。

### 3.2 非目标

以下内容不在本 Spec 中实现：

- Human-in-the-loop 审批。
- 全局槽位系统或 `missing_slots` 工作流。
- 自动重试与 `result_verifier` 节点。
- 播放器和歌单 Artifact 的独立 Pydantic 模型。
- SQLite checkpointer、用户隔离和长期记忆。
- 一次性改造所有低频工具。
- 修改前端展示协议。

## 4. 核心设计决策

### 4.1 Python 模型与传输格式分离

代码内部使用 Pydantic `ToolResult` 表达结果；LangChain Tool 边界继续返回 `str`，内容必须是 `ToolResult.model_dump_json()` 产生的 JSON。

原因：

- 当前 Agent 和 `ToolMessage` 链路已经稳定处理字符串。
- 避免依赖不同 LangChain 版本对 dict/Pydantic 返回值的隐式序列化行为。
- 后续节点可以显式解析、校验并拒绝不符合协议的结果。

不得直接使用 `str(tool_result)`，因为它不是稳定 JSON。

### 4.2 `ok` 表示业务目标是否完成

- `ok=true`：本次工具请求的目标已经明确完成。
- `ok=false`：目标未完成、只完成了一部分，或写入结果无法确认。

“API 请求成功发出”不等于 `ok=true`。

### 4.3 写操作不自动把不确定结果重试

创建歌单、加歌等写操作在网络异常时可能已经产生副作用，因此：

- 结果不确定时返回 `WRITE_UNCERTAIN`。
- `retryable` 必须为 `false`。
- 本阶段不再次执行写操作。
- 下一阶段由 `result_verifier` 通过查询状态确认是否成功。

### 4.4 不通过自然语言推断错误类型

节点不得通过搜索“失败”“异常”等词语判断工具结果。

服务层仍为旧格式时，工具适配层只读取明确字段，例如 `status`、布尔返回值和数据字段；不得解析 `message` 文本来决定错误码。

## 5. 数据模型

### 5.1 文件位置

新增：

```text
app/tools/tool_result.py
```

### 5.2 模型定义

目标接口：

```python
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class ToolResultCode(str, Enum):
    SUCCESS = "SUCCESS"
    INVALID_ARGUMENT = "INVALID_ARGUMENT"
    NOT_FOUND = "NOT_FOUND"
    AUTH_REQUIRED = "AUTH_REQUIRED"
    PERMISSION_DENIED = "PERMISSION_DENIED"
    PLAYBACK_UNAVAILABLE = "PLAYBACK_UNAVAILABLE"
    PARTIAL_SUCCESS = "PARTIAL_SUCCESS"
    WRITE_UNCERTAIN = "WRITE_UNCERTAIN"
    UPSTREAM_ERROR = "UPSTREAM_ERROR"
    INVALID_TOOL_RESULT = "INVALID_TOOL_RESULT"
    INTERNAL_ERROR = "INTERNAL_ERROR"


class ToolResult(BaseModel):
    ok: bool
    code: ToolResultCode
    message: str = Field(min_length=1)
    data: dict[str, Any] = Field(default_factory=dict)
    retryable: bool = False
```

允许增加以下便利方法，但不得引入额外抽象层：

```python
ToolResult.success(message: str, data: dict | None = None)
ToolResult.failure(
    code: ToolResultCode,
    message: str,
    data: dict | None = None,
    retryable: bool = False,
)
ToolResult.to_json() -> str
parse_tool_result(value: object) -> ToolResult | None
```

### 5.3 模型约束

实现时必须保证：

1. `code=SUCCESS` 时 `ok` 必须为 `true`。
2. `ok=true` 时 `code` 必须为 `SUCCESS`。
3. `WRITE_UNCERTAIN` 的 `retryable` 必须为 `false`。
4. `data` 必须可以被 JSON 序列化。
5. `message` 是给模型和用户阅读的简短事实描述，不得包含“必须视为成功”“禁止报告失败”等控制 Agent 的指令。
6. 不得在 `message` 或 `data` 中返回 API Key、Cookie、Credential、完整异常栈。

如果 Pydantic 校验器会显著增加实现时间，约束 1～3 可以先由构造方法和单元测试保证；字段结构校验必须由 Pydantic 完成。

## 6. 通用返回示例

### 6.1 成功

```json
{
  "ok": true,
  "code": "SUCCESS",
  "message": "搜索完成，共返回 5 条结果",
  "data": {
    "count": 5,
    "items": []
  },
  "retryable": false
}
```

### 6.2 参数错误

```json
{
  "ok": false,
  "code": "INVALID_ARGUMENT",
  "message": "歌单名称不能为空",
  "data": {
    "field": "name"
  },
  "retryable": false
}
```

### 6.3 写入结果不确定

```json
{
  "ok": false,
  "code": "WRITE_UNCERTAIN",
  "message": "加歌接口未返回可确认的写入结果",
  "data": {
    "dirid": 201,
    "song_ids": [436514, 123456]
  },
  "retryable": false
}
```

## 7. 核心工具行为规范

### 7.1 `search_music_tool`

成功时：

```json
{
  "ok": true,
  "code": "SUCCESS",
  "message": "搜索完成，共返回 5 条结果",
  "data": {
    "keyword": "周杰伦",
    "search_type": "SONG",
    "count": 5,
    "items": [
      {"index": 1, "id": 1, "mid": "xxx", "title": "晴天"}
    ]
  },
  "retryable": false
}
```

映射规则：

| 场景 | code | ok | retryable |
|---|---|---:|---:|
| 正常返回至少一条数据 | `SUCCESS` | true | false |
| `keyword` 为空 | `INVALID_ARGUMENT` | false | false |
| `search_type` 不在支持列表 | `INVALID_ARGUMENT` | false | false |
| 请求成功但没有结果 | `NOT_FOUND` | false | false |
| Service 返回 `status=error` | `UPSTREAM_ERROR` | false | true |
| 未预期的本地代码异常 | `INTERNAL_ERROR` | false | false |

要求：

- 保留现有 `index` 字段，供后续“播放第 N 首”使用。
- 不再把非法 `search_type` 静默降级为 `SONG`。
- `data.items` 保存结构化列表，不再将搜索结果再次编码为 JSON 字符串嵌套在 `data` 中。

### 7.2 `play_music_tool`

成功时，播放器数据暂时直接放在 `data` 中：

```json
{
  "ok": true,
  "code": "SUCCESS",
  "message": "已获取歌曲播放信息",
  "data": {
    "type": "play_music",
    "song_mid": "xxx",
    "title": "晴天",
    "artist": "周杰伦",
    "url": "https://example.com/song.mp3",
    "cover": "https://example.com/cover.jpg",
    "description": "已获取播放链接"
  },
  "retryable": false
}
```

映射规则：

| 场景 | code | ok | retryable |
|---|---|---:|---:|
| 获取到合法播放 URL | `SUCCESS` | true | false |
| `song_mid` 或 `song_name` 为空 | `INVALID_ARGUMENT` | false | false |
| 没有可播放 URL | `PLAYBACK_UNAVAILABLE` | false | false |
| 获取封面失败但播放 URL 可用 | `SUCCESS` | true | false |
| 未预期异常 | `UPSTREAM_ERROR` | false | true |

要求：

- 封面属于非关键字段，失败时使用空字符串，不能让整个播放任务失败。
- URL 不存在时不得生成假的 Artifact。
- `playback_prompt` 必须调整：仅当 `ToolResult.ok=true` 时，将 `ToolResult.data` 作为最终播放器 JSON 输出；失败时输出真实的 `code/message`，不得输出播放器 JSON。
- 独立 Artifact Schema 留到下一份 Spec，本阶段不得提前扩大范围。

### 7.3 `create_playlist_tool`

成功数据：

```json
{
  "ok": true,
  "code": "SUCCESS",
  "message": "歌单创建成功",
  "data": {
    "playlist": {
      "id": 9680571790,
      "dirid": 201,
      "name": "夜跑"
    }
  },
  "retryable": false
}
```

映射规则：

| 场景 | code | ok | retryable |
|---|---|---:|---:|
| 返回有效 `dirid` | `SUCCESS` | true | false |
| 名称为空 | `INVALID_ARGUMENT` | false | false |
| Service 返回非 dict 或缺少有效 `dirid` | `WRITE_UNCERTAIN` | false | false |
| 写请求期间抛出异常 | `WRITE_UNCERTAIN` | false | false |

要求：

- 写请求一旦开始，异常不能简单映射为可安全重试的错误。
- 不得因为返回结果格式异常而宣称创建成功。
- `data.playlist` 中只放后续步骤需要的字段。

### 7.4 `add_songs_to_playlist_tool`

输入约束：

- `song_ids` 必须非空。
- `dirid` 必须大于 0。
- 移除 `dirid=1` 的默认值，写操作必须显式指定目标歌单。

映射规则：

| 场景 | code | ok | retryable |
|---|---|---:|---:|
| Service 明确返回 `True` | `SUCCESS` | true | false |
| `song_ids` 为空或 `dirid` 非法 | `INVALID_ARGUMENT` | false | false |
| Service 返回 `False` | `WRITE_UNCERTAIN` | false | false |
| 写请求期间抛出异常 | `WRITE_UNCERTAIN` | false | false |

成功数据至少包含：

```json
{
  "dirid": 201,
  "song_ids": [436514, 123456],
  "requested_count": 2
}
```

本阶段必须删除以下行为：

- 将 `False` 描述为“歌曲实际上已经成功写入”。
- 将 Exception 描述为“网络写入实际上已经成功”。
- 指示模型忽略真实返回值或强制报告成功。

注意：当前 Service 会吞掉异常并返回 `False`。为了保留错误信息，可以让该 Service 在记录日志后重新抛出异常；无论选择哪种方式，Tool 层都必须将无法确认的结果映射为 `WRITE_UNCERTAIN`，不得映射为 `SUCCESS`。

### 7.5 `add_by_keyword_to_playlist_tool`

该工具是普通“给某歌单加几首某歌手歌曲”请求的主要入口，因此必须与直接加歌工具在同一阶段完成协议改造。

映射规则：

| Service 结果 | code | ok | retryable |
|---|---|---:|---:|
| `status=success` 且 `added_count > 0` | `SUCCESS` | true | false |
| `status=success` 但无可添加候选 | `NOT_FOUND` | false | false |
| `status=partial` 且 `added_count > 0` | `PARTIAL_SUCCESS` | false | false |
| `status=partial` 且写后未发现新增 | `WRITE_UNCERTAIN` | false | false |
| `status=error` | `UPSTREAM_ERROR` | false | false |
| 未预期异常 | `WRITE_UNCERTAIN` | false | false |

要求：

- 保留 Service 现有的写后查询逻辑，不在 Tool 层重复查询。
- `data` 保留 `dirid`、`songlist_name`、`keyword`、`target_count`、`added_count`、`added_song_ids`、`already_in_playlist_count`、`searched_pages`。
- 不通过 Service 的 `message` 文本推断业务状态，只通过 `status` 和明确数据字段映射。

## 8. Agent Prompt 兼容规则

修改 `app/agents/music_team_v3_1/prompts.py`：

### 8.1 `executor_prompt`

增加以下语义规则：

1. 工具返回统一的 `ToolResult` JSON。
2. `ok=true` 才能报告操作成功。
3. `ok=false` 时忠实报告 `code/message`。
4. `PARTIAL_SUCCESS` 只能报告部分完成，并给出实际完成数量。
5. `WRITE_UNCERTAIN` 必须表述为“当前无法确认结果”，不能自行重试或宣称成功。
6. 不向用户展示无意义的协议字段，但不得改变结果含义。

### 8.2 `playback_prompt`

增加以下语义规则：

1. `play_music_tool` 返回 `ToolResult`。
2. 成功时只把 `data` 中的播放器对象作为最终 JSON 输出。
3. 失败时输出简短自然语言，不得构造 `type=play_music`。

### 8.3 `replier_prompt`

增加以下语义规则：

1. 不得把 `ok=false` 改写成成功。
2. `WRITE_UNCERTAIN` 不得使用“已经完成”“已经添加”等确定表达。
3. `PARTIAL_SUCCESS` 必须包含实际完成数量。

## 9. 任务状态判断

### 9.1 当前逻辑问题

当前节点通过 AI 最终文本是否包含错误关键词设置 `task.status`。该逻辑必须删除。

### 9.2 新逻辑

在 `app/agents/music_team_v3_1/utils.py` 增加：

```python
def extract_tool_results(messages: list[BaseMessage]) -> list[ToolResult]: ...
def extract_last_tool_result(messages: list[BaseMessage]) -> ToolResult | None: ...
```

只解析当前轮最后一条 `HumanMessage` 之后产生的 `ToolMessage`，避免旧轮工具结果影响本轮状态。

本阶段只对以下五个已迁移工具强制 ToolResult 协议：

```python
TOOL_RESULT_REQUIRED_TOOLS = {
    "search_music_tool",
    "play_music_tool",
    "create_playlist_tool",
    "add_songs_to_playlist_tool",
    "add_by_keyword_to_playlist_tool",
}
```

其他尚未迁移的旧工具继续走兼容路径：其文本 ToolMessage 不参与 ToolResult 状态判断，也不得被误判为 `INVALID_TOOL_RESULT`。如果当前轮同时调用了旧工具和已迁移工具，以最后一个已迁移工具的 ToolResult 为准。

`music_ops_subgraph_node` 和 `playback_subgraph_node` 按以下规则设置状态：

| 当前轮情况 | task.status | error_code |
|---|---|---|
| 最后一个有效 ToolResult 为 `ok=true` | `done` | 清空 |
| 最后一个有效 ToolResult 为 `ok=false` | `failed` | 使用 ToolResult.code |
| 已迁移工具产生 ToolMessage，但无法解析为 ToolResult | `failed` | `INVALID_TOOL_RESULT` |
| 只调用尚未迁移的旧工具，Agent 正常返回文本 | `done` | 清空 |
| 当前轮没有调用工具，Agent 正常返回文本 | `done` | 清空 |
| Agent 调用本身抛出异常 | `failed` | `INTERNAL_ERROR` 或明确的上游错误码 |

说明：

- 采用“最后一个有效结果”，允许 Agent 在只读工具失败后换参数并最终成功。
- `INVALID_TOOL_RESULT` 只约束本阶段五个已迁移工具，避免破坏其他旧工具。
- 本阶段不引入 `partial` TaskStatus；`PARTIAL_SUCCESS` 暂时映射为 `failed`，但回复必须保留已完成的部分。
- 无工具调用可能是简单回复或自然追问，不需要全局槽位系统，因此记为 `done`。

### 9.3 保存最后工具结果

节点将最后一个有效结果保存到：

```python
state["extensions"]["last_tool_result"]
```

值使用 `ToolResult.model_dump(mode="json")`，不得保存 Pydantic 实例。

该字段供下一阶段 `result_verifier` 使用。本阶段只负责写入，不根据它执行重试或验证。

## 10. 实现影响范围

| 文件 | 变更 |
|---|---|
| `app/tools/tool_result.py` | 新增模型、错误码、序列化和解析帮助函数 |
| `app/tools/search_tools.py` | 改造搜索结果 |
| `app/tools/song_tools.py` | 改造播放结果 |
| `app/tools/playlist_tools.py` | 改造创建和两种加歌结果，删除伪成功逻辑 |
| `app/services/music/playlist_service.py` | 必要时让直接加歌异常可区分；保留组合加歌的写后验证 |
| `app/agents/music_team_v3_1/utils.py` | 从当前轮 ToolMessage 提取 ToolResult |
| `app/agents/music_team_v3_1/nodes.py` | 基于 ToolResult 修正任务状态 |
| `app/agents/music_team_v3_1/prompts.py` | 增加 ToolResult 解释约束 |
| `.gitignore` | 移除 `tests/` 忽略规则 |
| `tests/` | 新增协议、工具和节点状态测试 |

## 11. 推荐实现顺序

1. 新增 `ToolResult`、错误码、构造和解析方法。
2. 先为模型本身编写测试。
3. 改造 `search_music_tool`。
4. 改造 `play_music_tool`，验证成功播放的最终 Artifact 仍能被前端识别。
5. 改造 `create_playlist_tool` 和 `add_songs_to_playlist_tool`，删除伪成功。
6. 改造 `add_by_keyword_to_playlist_tool`。
7. 修改 prompts。
8. 修改 utils 和两个执行节点的状态判断。
9. 补齐工具和节点测试。
10. 运行后端测试，并手工走一次搜索、播放、创建、加歌流程。

## 12. 测试要求

### 12.1 `ToolResult` 单元测试

- 成功结果可以序列化并重新解析。
- `data={}` 不会在实例间共享。
- 非 JSON、普通文本、空字符串解析为 `None`。
- 未知错误码解析失败。
- `WRITE_UNCERTAIN` 不允许 `retryable=true`。
- `ok/code` 组合不一致时校验失败。

### 12.2 工具测试

所有测试 mock Service，不访问网络。

至少覆盖：

- 搜索成功、无结果、Service 错误、非法类型。
- 播放成功、无播放 URL、封面失败。
- 创建歌单成功、空名称、缺少 dirid、异常。
- 直接加歌成功、False、空歌曲列表、异常。
- 关键词加歌成功、部分成功、没有候选、写入不确定、Service 错误。
- 每一个返回值都能通过 `ToolResult.model_validate_json()`。

### 12.3 节点状态测试

- 工具成功时 `task.status=done`。
- 工具失败时 `task.status=failed`，并写入 `error_code/error_reason`。
- AI 文本包含“失败”但 ToolResult 成功时仍为 `done`。
- AI 文本不包含错误关键词但 ToolResult 失败时仍为 `failed`。
- 当前轮先失败、后成功时按最后一个结果记为 `done`。
- 旧轮失败结果不影响新一轮无工具回复。
- 非法 ToolMessage 返回 `INVALID_TOOL_RESULT`。

## 13. 验收标准

完成本 Spec 必须同时满足：

1. 五个核心工具的每条返回路径都是合法 ToolResult JSON。
2. `add_songs_to_playlist_tool` 中不存在将 False 或 Exception 描述为成功的代码或 prompt。
3. 两个执行节点不再搜索自然语言错误关键词。
4. 写入不确定时返回 `WRITE_UNCERTAIN`，且不会在本阶段自动重试。
5. 播放成功时前端仍能收到原有 `type=play_music` Artifact。
6. ToolResult 的错误不会被 executor/replier 改写为成功。
7. 测试不访问真实 QQ 音乐、真实 LLM 或外部网络。
8. `tests/` 被 Git 跟踪，新增测试全部通过。

## 14. 后续 Spec 的接口约定

下一份 `result_verifier/retry/artifact/state` Spec 可以直接依赖：

- `extensions.last_tool_result`
- `ToolResultCode.WRITE_UNCERTAIN`
- `ToolResultCode.PARTIAL_SUCCESS`
- `ToolResult.retryable`
- 播放成功数据位于 `ToolResult.data`

下一阶段不得重新定义另一套工具错误协议。
