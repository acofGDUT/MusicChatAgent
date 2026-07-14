# ToolResult 实现任务清单

## 1. 任务信息

- 状态：Done
- 优先级：P0
- 对应 Spec：[`reference/spec/01-tool-result-spec.md`](../spec/01-tool-result-spec.md)
- 目标：完成 ToolResult 协议、五个核心工具改造、任务状态判断和离线测试
- 推荐执行方式：严格按 TASK-01 至 TASK-10 顺序推进

## 2. 范围约束

本任务只实现第一份 Spec，不得顺手加入：

- `result_verifier` 节点
- 自动 retry
- Artifact Pydantic Schema
- `last_search_results`
- SQLite checkpointer
- `user_id/thread_id` 隔离
- 用户长期记忆
- 前端改版
- 全局槽位系统

如果实现过程中发现后续功能所需信息，只允许保存到 `extensions.last_tool_result`，不要提前扩展流程。

## 3. 完成顺序总览

- [x] TASK-01：恢复测试目录并建立测试骨架
- [x] TASK-02：实现 ToolResult 数据模型
- [x] TASK-03：改造搜索工具
- [x] TASK-04：改造播放工具
- [x] TASK-05：改造创建歌单和直接加歌工具
- [x] TASK-06：改造关键词加歌工具
- [x] TASK-07：更新 Agent Prompt
- [x] TASK-08：实现 ToolResult 提取和任务状态判断
- [x] TASK-09：补齐离线测试和回归检查
- [x] TASK-10：执行最终验收

---

## TASK-01：恢复测试目录并建立测试骨架

### 修改文件

- `.gitignore`
- `tests/__init__.py`
- `tests/tools/__init__.py`
- `tests/agents/__init__.py`

### 操作

- [x] 从 `.gitignore` 删除 `tests/` 忽略规则。
- [x] 创建 `tests/tools` 和 `tests/agents`。
- [x] 确认 `pytest` 可用；如果当前依赖中没有，加入 `requirements.txt` 或单独的开发依赖文件。
- [x] 测试不得读取真实 `.env` 凭证。
- [x] 测试不得请求 QQ 音乐、模型 API 或其他外部网络。

### 完成条件

- [x] `git status --short` 能显示 `tests/` 下新增文件。
- [x] 执行 `pytest --collect-only` 不因目录结构报错。

---

## TASK-02：实现 ToolResult 数据模型

### 新增文件

- `app/tools/tool_result.py`
- `tests/tools/test_tool_result.py`

### 操作

- [x] 实现 `ToolResultCode(str, Enum)`。
- [x] 至少包含以下错误码：
  - [x] `SUCCESS`
  - [x] `INVALID_ARGUMENT`
  - [x] `NOT_FOUND`
  - [x] `AUTH_REQUIRED`
  - [x] `PERMISSION_DENIED`
  - [x] `PLAYBACK_UNAVAILABLE`
  - [x] `PARTIAL_SUCCESS`
  - [x] `WRITE_UNCERTAIN`
  - [x] `UPSTREAM_ERROR`
  - [x] `INVALID_TOOL_RESULT`
  - [x] `INTERNAL_ERROR`
- [x] 实现 `ToolResult` 字段：`ok`、`code`、`message`、`data`、`retryable`。
- [x] `data` 使用 `Field(default_factory=dict)`。
- [x] 实现 `success(...)` 构造方法。
- [x] 实现 `failure(...)` 构造方法。
- [x] 实现 `to_json()`，内部使用 `model_dump_json()`。
- [x] 实现 `parse_tool_result(value)`，非法输入返回 `None`，不向上抛解析异常。
- [x] 约束 `ok=true` 只能和 `SUCCESS` 组合。
- [x] 约束 `WRITE_UNCERTAIN` 不允许 `retryable=true`。
- [x] 确保 `data` 不可序列化时能够在模型构造或序列化阶段暴露错误。

### 测试

- [x] success 可以完成 JSON round-trip。
- [x] failure 可以完成 JSON round-trip。
- [x] 两个实例不会共享默认 `data`。
- [x] 普通文本、空字符串、非法 JSON 返回 `None`。
- [x] 未知错误码返回 `None`。
- [x] `ok=true + 非 SUCCESS` 校验失败。
- [x] `ok=false + SUCCESS` 校验失败。
- [x] `WRITE_UNCERTAIN + retryable=true` 校验失败。

### 完成条件

- [x] `pytest tests/tools/test_tool_result.py` 通过。
- [x] 所有成功结果都能通过 `ToolResult.model_validate_json()` 重新加载。

---

## TASK-03：改造搜索工具

### 修改文件

- `app/tools/search_tools.py`
- `tests/tools/test_search_tools.py`

### 操作

- [x] `search_music_tool` 所有返回路径改成 ToolResult JSON 字符串。
- [x] 对 `keyword` 执行 `strip()`，为空时返回 `INVALID_ARGUMENT`。
- [x] 显式校验 `search_type` 支持值。
- [x] 删除非法 `search_type` 自动回退到 `SONG` 的行为。
- [x] 成功结果继续为每个 item 添加从 1 开始的 `index`。
- [x] 成功数据放入：
  - [x] `data.keyword`
  - [x] `data.search_type`
  - [x] `data.count`
  - [x] `data.items`
- [x] 空结果返回 `NOT_FOUND`。
- [x] Service 的 `status=error` 返回 `UPSTREAM_ERROR`，`retryable=true`。
- [x] 未预期本地异常返回 `INTERNAL_ERROR`。
- [x] 删除 `traceback.print_exc()` 和面向终端的异常打印；保留正常 logger 即可。

### 测试

使用 monkeypatch 或 AsyncMock mock `search_service.search_by_type`：

- [x] 搜索成功。
- [x] 空关键词。
- [x] 非法 search_type。
- [x] 空结果。
- [x] Service error。
- [x] Service 抛出异常。
- [x] 每条返回路径都能解析为 ToolResult。

### 完成条件

- [x] `pytest tests/tools/test_search_tools.py` 通过。
- [x] 搜索结果不再是 ToolResult 内嵌的二次 JSON 字符串。

---

## TASK-04：改造播放工具

### 修改文件

- `app/tools/song_tools.py`
- `tests/tools/test_song_tools.py`

### 操作

- [x] `play_music_tool` 所有返回路径改成 ToolResult JSON 字符串。
- [x] `song_mid` 为空返回 `INVALID_ARGUMENT`。
- [x] `song_name` 为空返回 `INVALID_ARGUMENT`。
- [x] 无播放 URL 返回 `PLAYBACK_UNAVAILABLE`。
- [x] 播放 URL 成功但封面失败时仍返回 `SUCCESS`，`cover=""`。
- [x] 成功数据直接放在 `ToolResult.data`，保留：
  - [x] `type="play_music"`
  - [x] `song_mid`
  - [x] `title`
  - [x] `artist`
  - [x] `url`
  - [x] `cover`
  - [x] `description`
- [x] 未预期的服务异常返回 `UPSTREAM_ERROR`。
- [x] 不生成虚假的播放 URL 或播放器数据。

### 测试

mock `song_service.get_playable_url` 和 `song_service.get_song_cover`：

- [x] 播放成功且有封面。
- [x] 播放成功但无封面。
- [x] 无播放 URL。
- [x] song_mid 为空。
- [x] song_name 为空。
- [x] Service 抛出异常。
- [x] 每条返回路径都能解析为 ToolResult。

### 完成条件

- [x] `pytest tests/tools/test_song_tools.py` 通过。
- [x] 成功时 `ToolResult.data` 仍符合当前前端播放器字段约定。

---

## TASK-05：改造创建歌单和直接加歌工具

### 修改文件

- `app/tools/playlist_tools.py`
- 必要时修改 `app/services/music/playlist_service.py`
- `tests/tools/test_playlist_tools.py`

### A. `create_playlist_tool`

- [x] 所有返回路径改成 ToolResult JSON 字符串。
- [x] 空名称返回 `INVALID_ARGUMENT`。
- [x] 返回有效 `dirid` 时才允许 `SUCCESS`。
- [x] 成功数据放在 `data.playlist`：`id`、`dirid`、`name`。
- [x] Service 返回非 dict、`error` 或缺少有效 `dirid` 时返回 `WRITE_UNCERTAIN`。
- [x] 写请求期间抛出异常时返回 `WRITE_UNCERTAIN`。
- [x] `WRITE_UNCERTAIN.retryable` 必须为 false。

### B. `add_songs_to_playlist_tool`

- [x] 将 `AddSongsInput.dirid` 改为必填，并限制大于 0。
- [x] `song_ids` 不能为空。
- [x] 移除工具函数中的 `dirid=1` 默认值。
- [x] Service 明确返回 `True` 时返回 `SUCCESS`。
- [x] Service 返回 `False` 时返回 `WRITE_UNCERTAIN`。
- [x] 写请求期间抛出异常时返回 `WRITE_UNCERTAIN`。
- [x] 成功和失败的 `data` 都保留 `dirid`、`song_ids`、`requested_count`。
- [x] 删除旧的整段注释实现，避免保留相互冲突的行为说明。
- [x] 删除以下伪成功文案及同义表达：
  - [x] “API 状态码 False 但操作已落实”
  - [x] “异常意味着已经成功”
  - [x] “必须视为完全成功”
  - [x] “歌曲已经稳稳地在歌单里”

### C. Service 最小调整

- [x] 检查 `playlist_service.add_songs_to_playlist` 是否仍吞掉异常并返回 False。
- [x] 如果需要区分异常，让 Service 记录日志后重新抛出；不要在本任务中引入新的 ServiceResult 体系。
- [x] 无论 Service 是否重抛，Tool 层都必须把无法确认的写入映射为 `WRITE_UNCERTAIN`。
- [x] 不修改关键词加歌已有的写后查询逻辑。

### 测试

- [x] 创建成功。
- [x] 创建空名称。
- [x] 创建返回非 dict。
- [x] 创建缺少 dirid。
- [x] 创建抛异常。
- [x] 加歌成功。
- [x] 加歌返回 False。
- [x] 加歌 song_ids 为空。
- [x] 加歌 dirid 非法。
- [x] 加歌抛异常。
- [x] 所有 False/Exception 场景断言 `ok=false`。
- [x] 所有写入不确定场景断言 `code=WRITE_UNCERTAIN` 且 `retryable=false`。

### 完成条件

- [x] 相关 playlist tool 测试通过。
- [x] `rg "100%|稳稳地|异常意味着|必须视为|操作已落实" app/tools app/agents` 没有命中旧伪成功规则。

---

## TASK-06：改造关键词加歌工具

### 修改文件

- `app/tools/playlist_tools.py`
- `tests/tools/test_playlist_tools.py`

### 操作

- [x] `add_by_keyword_to_playlist_tool` 所有返回路径改成 ToolResult JSON 字符串。
- [x] 不在 Tool 层再次执行写后查询。
- [x] `status=success` 且 `added_count > 0` 映射为 `SUCCESS`。
- [x] `status=success` 且 `added_count == 0` 映射为 `NOT_FOUND`。
- [x] `status=partial` 且 `added_count > 0` 映射为 `PARTIAL_SUCCESS`。
- [x] `status=partial` 且未发现新增映射为 `WRITE_UNCERTAIN`。
- [x] `status=error` 映射为 `UPSTREAM_ERROR`。
- [x] 未预期异常映射为 `WRITE_UNCERTAIN`，不得自动重试。
- [x] `data` 保留以下已知字段：
  - [x] `dirid`
  - [x] `songlist_name`
  - [x] `keyword`
  - [x] `target_count`
  - [x] `added_count`
  - [x] `added_song_ids`
  - [x] `already_in_playlist_count`
  - [x] `searched_pages`
- [x] 不解析 Service `message` 的自然语言来决定状态。

### 测试

- [x] 完全成功。
- [x] 没有可添加候选。
- [x] 部分成功且有新增。
- [x] 部分完成但没有确认新增。
- [x] Service error。
- [x] 未预期异常。

### 完成条件

- [x] 关键词加歌的所有返回路径都能被 `ToolResult.model_validate_json()` 解析。
- [x] 现有 Service 写后验证逻辑没有被删除或重复实现。

---

## TASK-07：更新 Agent Prompt

### 修改文件

- `app/agents/music_team_v3_1/prompts.py`

### `executor_prompt`

- [x] 声明所有工具返回 ToolResult JSON。
- [x] 只有 `ok=true` 才能报告成功。
- [x] `ok=false` 忠实报告 `code/message`。
- [x] `PARTIAL_SUCCESS` 必须报告实际完成数量。
- [x] `WRITE_UNCERTAIN` 表述为“无法确认结果”，禁止自动重试和宣称成功。

### `playback_prompt`

- [x] 成功时只输出 `ToolResult.data` 中的播放器对象。
- [x] 失败时不得生成 `type=play_music`。
- [x] 失败时基于 `code/message` 给出简短说明。

### `replier_prompt`

- [x] 禁止把 `ok=false` 改写为成功。
- [x] `WRITE_UNCERTAIN` 不使用确定完成表达。
- [x] `PARTIAL_SUCCESS` 保留实际完成数量。

### 完成条件

- [x] Prompt 中不存在要求忽略工具真实结果的内容。
- [x] Prompt 没有引入审批、槽位系统或 verifier 逻辑。

---

## TASK-08：实现 ToolResult 提取和任务状态判断

### 修改文件

- `app/agents/music_team_v3_1/utils.py`
- `app/agents/music_team_v3_1/nodes.py`
- 必要时修改 `app/agents/music_team_v3_1/state.py`
- `tests/agents/test_tool_result_state.py`

### A. Utils

- [x] 实现 `extract_tool_results(messages)`。
- [x] 实现 `extract_last_tool_result(messages)`。
- [x] 只解析最后一条 `HumanMessage` 之后的 `ToolMessage`。
- [x] 定义五个已迁移工具的强制协议名称集合。
- [x] 已迁移工具的普通文本或非法 JSON 不得被当作成功。
- [x] 尚未迁移的旧工具继续兼容文本结果，不参与 ToolResult 状态判断。
- [x] 解析函数不修改原消息列表。

### B. `music_ops_subgraph_node`

- [x] 删除基于“失败、报错、异常、无权限、超时、不支持”等关键词的判断。
- [x] 最后一个 ToolResult `ok=true` 时设置 `task.status=done`。
- [x] 最后一个 ToolResult `ok=false` 时设置 `task.status=failed`。
- [x] 失败时设置 `task.error_code` 和 `task.error_reason`。
- [x] 成功时清理上一轮残留的 `error_code/error_reason`。
- [x] 当前轮由已迁移工具产生 ToolMessage但无法解析协议时设置 `INVALID_TOOL_RESULT`。
- [x] 当前轮只调用旧工具且 Agent 正常返回文本时设置 `done`。
- [x] 当前轮没有 ToolMessage、Agent 正常返回文本时设置 `done`。
- [x] Agent 调用抛异常时返回明确 failed 状态，不让请求直接产生无说明的 500。

### C. `playback_subgraph_node`

- [x] 使用和 music ops 相同的 ToolResult 状态规则。
- [x] 删除仅通过“未接入/不支持”判断失败的逻辑。
- [x] 播放成功仍保留 Playback Agent 输出的最终 Artifact AIMessage。

### D. State

- [x] 将最后一个 ToolResult 的 `model_dump(mode="json")` 保存到 `extensions.last_tool_result`。
- [x] 不把 Pydantic 对象直接放入 checkpoint state。
- [x] 没有 ToolResult 时清理旧的 `extensions.last_tool_result`，避免 verifier 误用旧轮结果。
- [x] 确认 `TaskMeta.error_code` 已可保存字符串错误码；若现有类型足够则不修改 state.py。

### 测试

- [x] ToolResult 成功，AI 文本含“失败”，最终状态仍为 done。
- [x] ToolResult 失败，AI 文本没有错误关键词，最终状态仍为 failed。
- [x] 同一轮先失败后成功，以最后结果为准。
- [x] 上一轮失败不会污染下一轮。
- [x] ToolMessage 非法协议返回 `INVALID_TOOL_RESULT`。
- [x] 旧工具返回普通文本时不会被误判为 `INVALID_TOOL_RESULT`。
- [x] 无工具调用、正常文本回复为 done。
- [x] `extensions.last_tool_result` 是普通 dict。

### 完成条件

- [x] `pytest tests/agents/test_tool_result_state.py` 通过。
- [x] `rg "looks_fail|未接入.*不支持|失败.*报错.*异常" app/agents/music_team_v3_1/nodes.py` 不再命中旧状态判断。

---

## TASK-09：补齐离线测试和回归检查

### 操作

- [x] 运行 ToolResult 模型测试。
- [x] 运行 search tool 测试。
- [x] 运行 song tool 测试。
- [x] 运行 playlist tool 测试。
- [x] 运行节点状态测试。
- [x] 运行完整 pytest。
- [x] 确认测试没有读取 `data/credential.json` 或 `data/cookie.txt`。
- [x] 确认测试没有请求网络。
- [x] 确认没有真实模型调用。
- [x] 确认测试可以重复运行，结果稳定。

### 推荐命令

```bash
pytest tests/tools/test_tool_result.py
pytest tests/tools/test_search_tools.py
pytest tests/tools/test_song_tools.py
pytest tests/tools/test_playlist_tools.py
pytest tests/agents/test_tool_result_state.py
pytest
```

### 完成条件

- [x] 所有新增测试通过。
- [x] 不存在 skip 掉核心成功/失败场景的测试。

---

## TASK-10：执行最终验收

### 静态检查

- [x] 五个核心工具的函数签名仍兼容 LangChain Tool 调用。
- [x] 五个工具的所有显式 return 都返回 ToolResult JSON。
- [x] 没有将 `str(ToolResult)` 当作 JSON 返回。
- [x] 没有新增第二套错误模型。
- [x] 写操作错误不允许自动重试。
- [x] 没有把异常栈、Cookie 或 Credential 放入 ToolResult。

### 手工流程

在具备本地配置时各执行一次；没有真实凭证时可使用 mock 调用验证：

- [x] 搜索歌曲成功。
- [x] 搜索不存在的歌曲，得到 `NOT_FOUND`。
- [x] 播放成功时最终前端仍渲染播放器。
- [x] 无播放版权时不给出虚假播放器。
- [x] 创建歌单成功时能取到 `dirid`。
- [x] 加歌返回 False 时不再回复成功。
- [x] 关键词加歌部分完成时准确展示数量。

### 最终命令

```bash
pytest
git diff --check
git status --short
```

### Definition of Done

- [x] Spec 第 13 节的 8 项验收标准全部满足。
- [x] 所有任务项已勾选或记录明确的未完成原因。
- [x] 项目可以启动，核心工具可被 Agent 注册。
- [x] 播放 Artifact 的现有前端链路没有回归。
- [x] `reference/spec/01-tool-result-spec.md` 与实现不存在已知偏差。

## 4. 建议提交边界

如果需要分提交，推荐：

1. `test: add ToolResult contract tests`
2. `refactor: standardize core music tool results`
3. `fix: derive graph task status from ToolResult`
4. `test: cover tool failure and uncertain write paths`

提交不是完成任务的必要条件，不要在未经明确要求时自动 push。

## 5. 完成记录

- 完成日期：2026-07-13
- 测试结果：`53 passed`
- 测试命令：`.venv/bin/python -m pytest -q`
- 应用检查：`MusicTeamGraphV31` 和五个核心工具可正常导入
- 兼容性说明：未迁移的旧工具继续使用文本 ToolMessage，不会被误判为 `INVALID_TOOL_RESULT`
- Git 操作：未提交、未推送，修改保留在当前 `0.6musicApp` 分支
