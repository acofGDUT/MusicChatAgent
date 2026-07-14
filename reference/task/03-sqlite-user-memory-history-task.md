# SQLite Checkpoint、用户隔离、结构化偏好与历史恢复任务清单

## 1. 任务信息

- 状态：Ready
- 优先级：P0
- 对应 Spec：[`reference/spec/03-sqlite-user-memory-history-spec.md`](../spec/03-sqlite-user-memory-history-spec.md)
- 前置条件：Phase 1、Phase 2 已完成，现有 146 个后端测试通过
- 目标：接入 SQLite checkpoint、实现 `user_id/thread_id` 隔离、结构化用户偏好与 checkpoint 历史恢复
- 推荐执行方式：严格按 TASK-01 至 TASK-15 顺序推进
- 里程碑：先完成 3A/P0 并验收，再开始 3B/P1；只有两个里程碑均通过才算 Phase 3 完成

## 2. 范围约束

本任务只实现第三份 Spec，不得顺手加入：

- JWT、Session、OAuth 或真正的多用户登录系统
- 多用户 Credential 数据库、Cookie 加密或密钥管理
- PostgreSQL、Redis、向量数据库或 LangGraph Store
- 多进程、多实例部署和分布式锁
- 历史 `user_profile.md`、`history.jsonl` 数据迁移
- checkpoint 时间旅行、管理后台或清理界面
- 复杂偏好置信度、权重、衰减或推荐算法
- Human-in-the-loop 审批或全局槽位系统
- 新增 planner、judge、memory Agent
- 前端 UI 重构

实现必须遵守以下安全边界：

1. `user_id` 只能由服务端当前 Credential 派生，客户端不得提交或覆盖。
2. checkpoint state、API 响应、日志和 trace 都不得保存或暴露 Credential、Cookie、内部 checkpoint hash。
3. FastAPI 持久化失败时不得静默回退到 `InMemorySaver`。
4. SQLite/checkpointer 异常必须返回安全错误，不得伪装为空历史或成功响应。
5. 偏好读取、提取或写入失败必须 fail-soft，不得改变主任务和 Artifact 的成功状态。
6. 只有用户明确表达的长期偏好才能写入；普通播放、搜索和一次性请求不得自动推断偏好。
7. `user_profile.md`、`history.jsonl` 和 `soul.md` 不得继续接收用户级运行时写入。
8. history 和 POST reply 只能使用受信任的 `user_visible` 最终消息边界。
9. summary 只能压缩 runtime 上下文，不得删除 checkpoint 中的原始 messages。
10. SQLite 文件是本地未加密数据，不得提交到 Git，也不得宣传为生产级多用户服务。

## 3. 完成顺序总览

### 3A / P0：持久化、隔离、历史恢复

- [ ] TASK-01：建立依赖、strict msgpack、SQLite 路径与文件安全基线
- [ ] TASK-02：建立偏好基础 Schema、Repository Protocol 与 Disabled 实现
- [ ] TASK-03：实现服务端身份解析、thread_id 校验与 scoped checkpoint key
- [ ] TASK-04：将 Graph 改为 Factory，并在 FastAPI lifespan 接入 AsyncSqliteSaver
- [ ] TASK-05：补齐 checkpoint 重开、生命周期与身份隔离测试
- [ ] TASK-06：停用全局记忆写入并统一 post-reply memory_sync
- [ ] TASK-07：建立最终用户可见消息和确定性时间戳边界
- [ ] TASK-08：改造 History/API 错误契约和前端错误传播
- [ ] TASK-09：执行 3A 里程碑验收

### 3B / P1：结构化用户偏好

- [ ] TASK-10：实现 Preference Patch Schema 与确定性 Merge
- [ ] TASK-11：实现 SQLitePreferenceRepository 与事务安全
- [ ] TASK-12：在 FastAPI lifespan 接入双连接最终架构
- [ ] TASK-13：接入偏好加载、显式提取、Prompt 注入与 Trace
- [ ] TASK-14：补齐 Phase 3 测试、文档和既有回归适配
- [ ] TASK-15：执行最终验收

---

# 3A / P0：持久化、隔离、历史恢复

## TASK-01：建立依赖、strict msgpack、SQLite 路径与文件安全基线

### 修改文件

- `requirements.txt`
- `.gitignore`
- `app/agents/music_team_v3_1/config.py`
- `main.py`

### 新增文件

- `.env.example`
- `tests/conftest.py`

### A. 依赖与运行时

- [ ] 在 `requirements.txt` 增加 `langgraph-checkpoint-sqlite>=3.1,<4.0`。
- [ ] 在 `requirements.txt` 增加 `aiosqlite>=0.21,<1.0`。
- [ ] 安装依赖后确认 `AsyncSqliteSaver` 可导入。
- [ ] 记录 `.venv` 实际使用的 Python 与 SQLite runtime 版本。
- [ ] 不新增 `pytest-asyncio`；异步测试继续使用 `asyncio.run()`。

### B. strict msgpack

- [ ] 在任何 LangGraph、checkpointer、graph 或 endpoint import 之前检查 `LANGGRAPH_STRICT_MSGPACK=true`。
- [ ] 环境变量缺失或值不为 `true` 时启动立即失败，并给出不含 secret 的明确配置错误。
- [ ] 不允许在 LangGraph 已导入后临时补设变量来伪装 strict 已生效。
- [ ] `tests/conftest.py` 在测试收集和 app/LangGraph import 前设置 strict 环境。
- [ ] `.env.example` 提供 `LANGGRAPH_STRICT_MSGPACK=true` 示例。

### C. SQLite 路径

- [ ] 在配置层新增 `STATE_DB_PATH`。
- [ ] 默认路径为项目根目录下的 `data/music_agent.sqlite3`。
- [ ] 支持 `MUSIC_AGENT_STATE_DB` 覆盖默认路径。
- [ ] 相对路径必须相对项目根目录解析，不得依赖进程当前工作目录。
- [ ] 支持 `~` 和绝对路径，并统一解析为绝对路径。
- [ ] 启动时按需创建父目录。
- [ ] `.env.example` 提供不含用户真实路径的 `MUSIC_AGENT_STATE_DB` 示例。

### D. Git 与数据安全

- [ ] `.gitignore` 忽略 `*.sqlite3`、`*.sqlite3-wal`、`*.sqlite3-shm`。
- [ ] 同时覆盖项目默认 `data/` 下的运行时 SQLite 文件。
- [ ] 确认不会忽略需要提交的源码或测试 fixture。
- [ ] 确认 Git 未追踪现有 SQLite、WAL 或 SHM 文件。

### 测试

- [ ] strict 配置存在时应用模块可以导入。
- [ ] 使用 subprocess 验证 strict 配置缺失时启动失败。
- [ ] 默认数据库路径与从仓库外 cwd 启动时的路径一致。
- [ ] 相对、绝对和 `~` 路径解析符合 Spec。
- [ ] 当前 state/message 类型能在 strict msgpack 下 round-trip。

### 完成条件

- [ ] 新环境按照 `.env.example` 配置后可以导入应用。
- [ ] 依赖和路径测试通过。
- [ ] `git status --short` 中没有运行时 SQLite 文件。

---

## TASK-02：建立偏好基础 Schema、Repository Protocol 与 Disabled 实现

### 新增文件

- `app/schemas/preferences.py`
- `app/services/memory/__init__.py`
- `app/services/memory/preference_repository.py`

### 修改文件

- `app/schemas/__init__.py`
- `app/agents/music_team_v3_1/nodes.py`
- `app/agents/music_team_v3_1/graph.py`
- `tests/agents/test_result_verifier.py`

### A. 基础偏好 Schema

- [ ] 实现 `PreferenceBucket`，包含 `liked` 和 `disliked`。
- [ ] 单侧最多保存 20 项。
- [ ] 每个值去除首尾空格，长度限制为 1 至 60。
- [ ] 同一 bucket 单侧使用 casefold 去重并保留首次展示文本。
- [ ] 同一值不得同时存在于同一 bucket 的 liked 和 disliked。
- [ ] 实现 `UserPreferences`，包含 `artists/genres/languages/scenes` 四个 bucket。
- [ ] `UserPreferences` 包含 `version` 和 `updated_at`。
- [ ] `updated_at` 只接受 timezone-aware datetime，从存储读取后统一为 UTC；空偏好允许为 `None`。
- [ ] 所有模型使用 `extra="forbid"`。
- [ ] 从 `app/schemas/__init__.py` 导出基础类型。

### B. Repository 抽象

- [ ] 定义 async `PreferenceRepository` Protocol。
- [ ] Protocol 至少提供 `get(user_id)` 和 `merge(user_id, patch)` 入口。
- [ ] 实现单例式 `DisabledPreferenceRepository`。
- [ ] Disabled repository 不访问数据库、不调用提取模型、不保存进程内偏好。
- [ ] Disabled `get` 返回全新空偏好，避免请求间共享可变对象。
- [ ] Disabled `merge` 返回 `unchanged`；node 单独把更新状态记录为 `skipped`，不得伪装为 SQLite 写入。

### C. Async plumbing

- [ ] 将 `init_memory_node` 改为 async。
- [ ] Graph node 注入 repository，而不是从全局变量读取。
- [ ] repository 未显式提供时使用 `DisabledPreferenceRepository`。
- [ ] 3A 阶段 disabled backend 不创建数据库表，也不调用偏好 extractor。
- [ ] 更新受 sync/async 变化影响的 verifier 和 graph 测试。

### 测试

- [ ] 空偏好可 JSON/Pydantic round-trip。
- [ ] extra 字段被拒绝。
- [ ] 空字符串、纯空白和超长值被拒绝。
- [ ] naive datetime 被拒绝，带时区 datetime 统一为 UTC；行为必须有测试固定。
- [ ] Disabled repository 连续两次读取不会共享可变数据。
- [ ] Disabled backend 不发生文件 I/O 或 LLM 调用。
- [ ] async `init_memory_node` 能被 Graph 正常调用。

### 完成条件

- [ ] 基础 Schema、Disabled repository 和既有 verifier 测试通过。
- [ ] 此时应用仍可在未启用 SQLite preference 的情况下运行，为 3A 提供安全中间状态。

---

## TASK-03：实现服务端身份解析、thread_id 校验与 scoped checkpoint key

### 修改文件

- `app/core/auth.py`
- `app/agents/music_team_v3_1/utils.py`
- `app/agents/music_team_v3_1/state.py`
- `app/api/v1/endpoints.py`

### A. 认证 user_id

- [ ] 定义可映射为 401 的 `AuthenticationRequiredError`。
- [ ] 定义可映射为安全 503 的 `AuthenticationUnavailableError`。
- [ ] 实现服务端当前用户 ID 获取函数。
- [ ] 函数先 `await ensure_credential_loaded()`，再从 `app.core.auth` 模块读取当前 `GLOBAL_CREDENTIAL`。
- [ ] 禁止使用 `from app.core.auth import GLOBAL_CREDENTIAL` 持有 stale binding。
- [ ] 优先使用有效 `musicid`。
- [ ] `musicid` 为 `0`、空或无效时回退到有效 `str_musicid`。
- [ ] 两者均无效时返回认证缺失，不生成匿名共享 ID。
- [ ] user_id 去除首尾空格后长度限制为 1 至 128。
- [ ] Credential 文件读取、解析或 I/O 错误映射为安全 503。
- [ ] 错误响应、日志和 trace 不包含 Credential 内容或真实 user_id。

### B. thread_id 契约

- [ ] 请求省略 `thread_id` 或显式传 `null` 时使用 `local-web-thread`。
- [ ] 显式空字符串或纯空白返回 400。
- [ ] 有前后空白的值返回 400，不静默 trim 成另一个线程。
- [ ] 只允许 `[A-Za-z0-9._-]`。
- [ ] 长度限制为 1 至 128。
- [ ] Unicode、路径分隔符和 129 字符值返回 400。
- [ ] 请求模型配置 `extra="forbid"`。
- [ ] 客户端提交 `user_id` 或其他未知字段返回 422。

### C. scoped checkpoint key

- [ ] 实现 `build_checkpoint_thread_id(user_id, thread_id)`。
- [ ] 对 user_id 和 thread_id 使用长度前缀编码，避免简单拼接碰撞。
- [ ] 使用 SHA-256 生成不可逆内部 key。
- [ ] 内部 key 使用固定 `music:` 前缀，便于识别应用域。
- [ ] LangGraph configurable 只接收内部 hash，不接收原始 user_id/thread_id 拼接值。
- [ ] state 保存原始 `user_id` 和 `thread_id` 供节点校验，不保存 Credential 或 checkpoint hash。

### D. 隔离语义

- [ ] 同一 user_id + thread_id 稳定生成同一 key。
- [ ] 不同 user_id + 相同 thread_id 生成不同 key。
- [ ] 相同 user_id + 不同 thread_id 生成不同 key。
- [ ] POST 和 History 共用同一套身份与 key 构造帮助函数。

### 测试

- [ ] 覆盖 Credential 已加载与延迟加载两种场景。
- [ ] 覆盖 stale binding 回归场景。
- [ ] 覆盖 `musicid=0` 回退 `str_musicid`。
- [ ] 覆盖无 Credential、超长 ID、加载异常的 401/503 行为。
- [ ] 覆盖 thread_id 省略、null、空、空白、前后空白、Unicode、非法字符和超长值。
- [ ] 覆盖 request body 自报 user_id 返回 422。
- [ ] 覆盖长度前缀 hash 的确定性和隔离性。

### 完成条件

- [ ] 身份帮助函数均为可独立离线测试的确定性代码。
- [ ] API 无法通过请求字段切换到另一 user_id。
- [ ] 任何响应和 trace 都不返回原始 user_id 或内部 checkpoint key。

---

## TASK-04：将 Graph 改为 Factory，并在 FastAPI lifespan 接入 AsyncSqliteSaver

### 修改文件

- `main.py`
- `app/agents/music_team_v3_1/__init__.py`
- `app/agents/music_team_v3_1/graph.py`
- `app/api/v1/endpoints.py`

### A. Graph Factory

- [ ] 实现 `build_graph(*, checkpointer=None, preference_repository=DISABLED_PREFERENCES)`。
- [ ] Graph 编译时显式注入 checkpointer 和 preference repository。
- [ ] 保留 `graph = build_graph()` 供 `langgraph.json`/Studio 导入。
- [ ] 静态 graph 只能使用 disabled preference backend。
- [ ] 静态 graph 不访问 `user_profile.md`、`history.jsonl` 或本地 SQLite 生命周期资源。
- [ ] 从包 `__init__.py` 同时导出 `graph` 和 `build_graph`。
- [ ] FastAPI endpoint 禁止导入并使用静态 `graph`，只能从 `request.app.state.music_graph` 获取 persistent graph。

### B. FastAPI lifespan

- [ ] 使用 `FastAPI(lifespan=lifespan)` 注册生命周期。
- [ ] lifespan 启动时创建数据库父目录。
- [ ] 使用 `aiosqlite` 打开 checkpointer connection。
- [ ] 基于该连接创建 `AsyncSqliteSaver`。
- [ ] 对 connection 设置 `PRAGMA journal_mode=WAL`。
- [ ] 设置 `PRAGMA busy_timeout=5000`。
- [ ] 设置 `PRAGMA foreign_keys=ON`。
- [ ] 使用 harmless `aget_tuple` 或等价读取触发 saver setup。
- [ ] healthcheck 不写入 `__startup_healthcheck__` 或其他 checkpoint。
- [ ] 3A 阶段使用 disabled preference repository 构建 graph。
- [ ] 将 graph 和 repository 保存到 `app.state`。
- [ ] lifespan 退出时先将 `app.state.music_graph` 和 `app.state.preference_repository` 清空，再关闭连接。
- [ ] 连接关闭后旧 graph 不得继续被 endpoint 调用。
- [ ] 启动/运行失败时不回退到 `InMemorySaver`。

### C. Endpoint 使用方式

- [ ] POST 和 History 都从当前 request 的 app state 获取 graph。
- [ ] app state graph 缺失或已关闭时返回安全 503。
- [ ] POST 使用 TASK-03 生成的 scoped config 调用 `astream`。
- [ ] 不在模块 import 时打开 SQLite connection。

### 测试

- [ ] `build_graph()` 在无 checkpointer 时可供 Studio smoke test 导入。
- [ ] `build_graph(checkpointer=...)` 确实把 saver 注入 compiled graph。
- [ ] `TestClient` 进入 lifespan 后 app state graph 可用。
- [ ] 退出 lifespan 后 app state 引用为空。
- [ ] checkpointer connection 退出后不可继续查询。
- [ ] healthcheck 不留下 checkpoint。
- [ ] WAL、busy timeout 和 foreign keys 配置可查询验证。
- [ ] SQLite 初始化错误不会创建内存 fallback。

### 完成条件

- [ ] 本地 FastAPI 请求实际使用 `AsyncSqliteSaver`。
- [ ] 生命周期创建、可用、清理三个阶段都有测试固定。
- [ ] import graph 不会隐式创建永久 SQLite connection。

---

## TASK-05：补齐 checkpoint 重开、生命周期与身份隔离测试

### 新增文件

- `tests/persistence/__init__.py`
- `tests/persistence/test_sqlite_checkpoint.py`
- `tests/api/test_local_chat_history.py`

### 测试基线

- [ ] 所有 SQLite 测试使用临时目录和临时数据库。
- [ ] saver 底层恢复测试使用最小 StateGraph，不调用真实 LLM 或 QQ 音乐。
- [ ] 另写真实 `build_graph` 依赖注入 smoke test，避免只验证测试替身。
- [ ] 异步 case 在同步 pytest 中用 `asyncio.run()`。
- [ ] 并发 case 在同一次 `asyncio.run()` 内使用 `asyncio.gather()`。
- [ ] FastAPI API/lifespan 使用 `TestClient`。

### A. 重开恢复

- [ ] 第一个 saver/graph 写入 messages、summary 和 `last_search_results`。
- [ ] 关闭第一个 saver connection。
- [ ] 用同一 SQLite 文件创建第二个 saver/graph。
- [ ] 相同 scoped key 恢复完整 state。
- [ ] 不同 scoped key 返回空 state。
- [ ] 恢复后的 LangChain messages 类型和内容正确。
- [ ] strict msgpack 下 Pydantic/连接对象没有被误放入 state。

### B. 隔离

- [ ] user A/thread X 的消息不会出现在 user B/thread X。
- [ ] user A/thread X 与 user A/thread Y 不共享 checkpoint state。
- [ ] 同一 user/thread 多次请求能继续已有 state。
- [ ] API 级 History 只能读取当前 Credential 对应用户的 scoped state。

### C. 生命周期

- [ ] lifespan 内 graph 可读写。
- [ ] lifespan 退出后 saver connection 已关闭。
- [ ] app state graph/repository 已置空。
- [ ] 保存的旧 graph 不可继续调用已关闭资源。
- [ ] healthcheck 不创建任何业务 checkpoint。
- [ ] 测试失败时不存在 InMemorySaver 回退导致的假通过。

### D. strict 与 SQLite 设置

- [ ] subprocess 覆盖 strict 配置缺失的启动失败。
- [ ] SQLite 当前处于 WAL 模式。
- [ ] checkpointer connection 的 busy timeout 为 5000ms。
- [ ] 记录实际 SQLite runtime 版本，测试结论不扩展为多进程生产并发承诺。

### 完成条件

- [ ] `.venv/bin/python -m pytest tests/persistence/test_sqlite_checkpoint.py -q` 通过。
- [ ] 身份隔离相关 API 测试通过。
- [ ] 关闭并重开连接后恢复成功，不依赖同一进程内对象。

---

## TASK-06：停用全局记忆写入并统一 post-reply memory_sync

### 修改文件

- `app/agents/music_team_v3_1/config.py`
- `app/agents/music_team_v3_1/state.py`
- `app/agents/music_team_v3_1/nodes.py`
- `app/agents/music_team_v3_1/graph.py`
- `app/agents/music_team_v3_1/prompts.py`
- `app/agents/music_team_v3_1/utils.py`

### A. 先移除跨用户副作用

- [ ] 删除或停用运行时对 `user_profile.md` 的读写。
- [ ] 删除或停用运行时对 `history.jsonl` 的追加和读取。
- [ ] 删除或停用 soul autotune 写入。
- [ ] `soul.md` 只允许作为应用级只读内容使用。
- [ ] 删除对应 profile/history/soul-autotune 配置项、Prompt、flag 和 trace 字段。
- [ ] 扩大 memory_sync 路由前先完成以上清理，避免把旧副作用扩大到所有请求。

### B. Graph 路由

- [ ] music ops 路径调整为 `chat_replier -> memory_sync -> finalizer`。
- [ ] smalltalk 路径调整为 `chat_replier -> memory_sync -> finalizer`。
- [ ] playback verifier 完成后调整为 `memory_sync -> finalizer`。
- [ ] 三类请求都先经过 async `init_memory`。
- [ ] 每次最终输出恰好经过一次 `memory_sync`。
- [ ] `memory_sync` 只有一个普通出边到 `finalizer`。
- [ ] `memory_sync` 不新增 conditional edge、回环或 retry。

### C. 增量 summary

- [ ] state 增加 `summary_message_count`。
- [ ] summary 输入只包含旧 summary 和从该 count 开始的新增 messages。
- [ ] count 越界时安全 clamp 到合法范围。
- [ ] 只有新增 delta 达到阈值时才调用 summary 模型。
- [ ] summary 成功后 count 更新为当前 `len(messages)`。
- [ ] summary 失败时保留旧 summary 和旧 count，并继续 finalizer。
- [ ] summary Prompt 不推断一次性请求为长期偏好。
- [ ] 不使用 `RemoveMessage`，不删除、替换或截断 state messages。

### D. Runtime 上下文裁剪

- [ ] 实现统一 `build_runtime_messages` 帮助函数。
- [ ] 无 summary 时返回全部 messages。
- [ ] 有 summary 时包含全部尚未总结的 delta。
- [ ] 有 summary 时至少保留最近 N 条重叠消息。
- [ ] summary 失败时也不会丢失未总结 delta。
- [ ] intent parser 使用相同 runtime 起点，但不注入 profile、soul 或 summary 文本。
- [ ] 裁剪仅影响 LLM runtime 输入，不改变 checkpoint state。

### 测试

- [ ] 三条业务路径均只经过一次 memory_sync。
- [ ] memory_sync 失败仍进入 finalizer。
- [ ] 已有 summary 后追加超过 N 条短消息时，runtime 包含全部未总结 delta。
- [ ] summary 失败后 runtime 仍包含 delta。
- [ ] summary 后旧 messages 仍可从 state/history 读取。
- [ ] 请求执行期间没有写入 profile/history/soul 文件。

### 完成条件

- [ ] Graph 无 memory_sync 回环。
- [ ] 全局用户记忆文件不再影响新请求。
- [ ] summary 只承担上下文压缩，不承担历史存储。

---

## TASK-07：建立最终用户可见消息和确定性时间戳边界

### 修改文件

- `app/agents/music_team_v3_1/nodes.py`
- `app/agents/music_team_v3_1/utils.py`
- `app/agents/music_team_v3_1/graph.py`
- `tests/agents/test_result_verifier.py`

### A. 受信任标记

- [ ] HumanMessage 进入请求时由服务端写入 `created_at_ms`。
- [ ] ChatReplier 返回的模型原始 additional kwargs 先移除 `user_visible` 和 `created_at_ms`。
- [ ] 只有 ChatReplier 节点在最终消息上写入受信任 `user_visible=true`。
- [ ] PlayAgent 原始输出同样移除模型伪造的可见标记和时间戳。
- [ ] 只有 verifier 确认当前尝试 terminal 后，才标记最终 PlayAgent 消息。
- [ ] MusicExecutor 消息永远不标记为用户可见。
- [ ] retry 第一次失败尝试保持不可见。

### B. Playback canonicalization

- [ ] verifier canonicalize 最终播放 Artifact 时保留原 message id。
- [ ] terminal failure 只生成一条最终用户可见错误消息。
- [ ] retry 遗漏原失败 tool 时，从 verifier 保存的最终 ToolResult 恢复错误语义。
- [ ] 不得把第二次无关 Agent 文本当作最终失败原因。
- [ ] retry 中间尝试可进入已脱敏 trace，但不能进入 reply/history。

### C. POST reply 选择

- [ ] POST 只从本次运行后的 `user_visible` AIMessage 中选择最终 reply。
- [ ] POST 与 History 使用同一个可见性判断帮助函数。
- [ ] 没有最终可见 AIMessage 时返回安全 500。
- [ ] 禁止回退到 MusicExecutor、未验证 PlayAgent 或任意最后一条 AIMessage。

### D. 确定性时间戳

- [ ] 显式 `created_at_ms` 只有在 `int > 0` 且不是 `bool` 时有效。
- [ ] 缺失或非法时间戳优先从 checkpoint snapshot `created_at` 生成确定性 fallback。
- [ ] snapshot 时间无效时使用稳定的 message index/count fallback。
- [ ] 每条最终时间戳使用 `max(candidate, previous + 1)`，保证严格递增。
- [ ] 先对完整过滤后消息列表计算时间戳，再应用 limit。
- [ ] 同一 snapshot 重复 GET 返回稳定时间戳。
- [ ] 不同 limit 的重叠消息时间戳一致。
- [ ] 不对旧 checkpoint 执行迁移写回。

### 测试

- [ ] music ops 只暴露 ChatReplier，不暴露 MusicExecutor。
- [ ] playback 只暴露 verifier 确认后的 PlayAgent Artifact。
- [ ] retry 第一次失败消息不出现在 reply/history。
- [ ] terminal failure 只出现最终恢复的错误。
- [ ] canonicalize 前后 message id 不变。
- [ ] 模型伪造 `user_visible` 被清除。
- [ ] bool、负数、相等、倒退和非法时间戳都按规则恢复。
- [ ] 重复内容不被误去重。
- [ ] 超过 200 字的消息不被截断。

### 完成条件

- [ ] POST reply 和 History 的用户可见消息集合一致。
- [ ] 不依赖 Agent 名称或“最后一条消息”猜测可见性。
- [ ] 时间戳在同一 snapshot 下可重复、严格递增且与 limit 无关。

---

## TASK-08：改造 History/API 错误契约和前端错误传播

### 修改文件

- `app/api/v1/endpoints.py`
- `music-agent-chat-ui/src/features/chat-local/services/localChatApi.ts`
- `music-agent-chat-ui/src/features/chat-local/hooks/useLocalChatSession.ts`

### 新增文件

- `music-agent-chat-ui/tests/localChatApi.spec.ts`

### A. History 数据源

- [ ] History 使用 `await graph.aget_state(scoped_config)` 读取 checkpoint snapshot。
- [ ] 不再打开或解析 `history.jsonl`。
- [ ] 只返回完整 HumanMessage 和已标记 `user_visible` 的 ChatReplier/PlayAgent 消息。
- [ ] 不返回 ToolMessage、SystemMessage、MusicExecutor 或 retry 中间尝试。
- [ ] 保留完整消息内容，不去重、不做 200 字 preview 截断。
- [ ] limit 在可见消息过滤和全量时间戳计算后应用。
- [ ] 不存在的当前用户/thread 返回 HTTP 200 和空 messages。

### B. Request/Response 契约

- [ ] POST message 空字符串或超过 4000 字符返回 422。
- [ ] POST message 纯空白返回 400。
- [ ] 成功 POST/History response 字段保持前端兼容。
- [ ] response 不增加 user_id 或 checkpoint hash。
- [ ] thread_id 行为与 TASK-03 完全一致。

### C. 错误分类

- [ ] 认证缺失返回 401。
- [ ] Credential 加载不可用返回安全 503。
- [ ] SQLite/checkpointer/storage 异常在 POST 和 History 返回安全 503。
- [ ] 普通 Graph/LLM 未知异常返回安全 500。
- [ ] 无最终可见 AIMessage 返回安全 500。
- [ ] 偏好 backend 异常不在 3A 触发；3B 接入后必须保持主请求 200。
- [ ] 所有错误 detail 不包含异常原文、文件路径、user_id、Cookie 或堆栈。
- [ ] History DB 异常不得返回 200 空数组。

### D. 前端最小改造

- [ ] `localChatApi.ts` 对任何 non-2xx response 抛出 Error。
- [ ] 错误解析兼容 `message`、字符串 `detail` 和 `detail.message`。
- [ ] 无可解析 detail 时使用安全通用文案。
- [ ] History non-2xx 不转换为空数组。
- [ ] `useLocalChatSession.ts` 将 History 加载错误写入现有 error state。
- [ ] 不进行组件视觉重构。

### E. 前端 service 测试

- [ ] mocked fetch 覆盖 History 503 reject。
- [ ] mocked fetch 覆盖 POST 字符串 detail。
- [ ] mocked fetch 覆盖 `detail.message`。
- [ ] mocked fetch 覆盖无 JSON/未知 body 的 fallback 文案。
- [ ] 测试不启动浏览器、不启动真实后端、不访问网络。

### 测试

- [ ] 不存在 thread 返回空 history。
- [ ] DB 故障返回 503 而不是空 history。
- [ ] POST storage error 返回 503。
- [ ] POST RuntimeError 返回 500。
- [ ] 错误响应不泄露内部信息。
- [ ] 前端 History 503 进入 error state。

### 完成条件

- [ ] `.venv/bin/python -m pytest tests/api/test_local_chat_history.py -q` 通过。
- [ ] `pnpm exec playwright test tests/localChatApi.spec.ts` 通过。
- [ ] `pnpm exec tsc --noEmit` 通过。
- [ ] 相关 TypeScript 文件通过 Prettier check。

---

## TASK-09：执行 3A 里程碑验收

### 验收项

- [ ] 本地 FastAPI 实际使用 `AsyncSqliteSaver`。
- [ ] 进程关闭并重新创建 saver 后，相同 user/thread 能恢复 state。
- [ ] 不同用户的同名 thread 互相隔离。
- [ ] 同一用户不同 thread 的 state 互相隔离。
- [ ] 客户端无法提交 user_id 切换身份。
- [ ] Credential 边界错误分别映射为 401/503。
- [ ] History 从 checkpoint 读取，不再读取 JSONL。
- [ ] summary 不删除 state messages。
- [ ] playback retry 中间消息不出现在 reply/history。
- [ ] ChatReplier、PlayAgent 最终输出使用受信任 `user_visible` 边界。
- [ ] SQLite/API 真实错误不会伪装为成功。
- [ ] 全局 profile/history/soul 不再接收用户运行时写入。
- [ ] app shutdown 清空引用并关闭 saver connection。
- [ ] static graph 与 FastAPI persistent graph 职责分离。

### 建议测试命令

- [ ] `.venv/bin/python -m pytest tests/persistence/test_sqlite_checkpoint.py -q`
- [ ] `.venv/bin/python -m pytest tests/api/test_local_chat_history.py -q`
- [ ] `.venv/bin/python -m pytest tests/agents/test_result_verifier.py -q`
- [ ] `.venv/bin/python -m pytest -q`
- [ ] `cd music-agent-chat-ui && pnpm exec playwright test tests/localChatApi.spec.ts`
- [ ] `cd music-agent-chat-ui && pnpm exec tsc --noEmit`

### 里程碑门槛

- [ ] 以上测试全部通过后才能开始 TASK-10。
- [ ] 如果 3A 尚有持久化、隔离或 history 回归，不得用 3B 偏好逻辑掩盖问题。
- [ ] 记录 3A 实际测试数量和结果。

---

# 3B / P1：结构化用户偏好

## TASK-10：实现 Preference Patch Schema 与确定性 Merge

### 修改文件

- `app/schemas/preferences.py`
- `app/schemas/__init__.py`

### 新增文件

- `tests/agents/test_user_preferences.py`

### A. Patch Schema

- [ ] 实现 `PreferenceSignal`。
- [ ] `category` 只允许 `artist/genre/language/scene`。
- [ ] `action` 只允许 `like/dislike/clear`。
- [ ] `value` 去除首尾空格，长度限制为 1 至 60。
- [ ] 实现 `PreferencePatch`，单次最多 10 个 signals。
- [ ] 实现 `PreferenceMergeResult`。
- [ ] merge result status 只允许 `updated` 或 `unchanged`。
- [ ] 所有模型继续使用 `extra="forbid"`。

### B. 确定性 Merge

- [ ] 建立 singular category 到 plural bucket 的固定映射。
- [ ] 同一侧使用 casefold 去重并保留已有展示文本。
- [ ] `like` 先从 disliked 移除同值，再加入 liked。
- [ ] `dislike` 先从 liked 移除同值，再加入 disliked。
- [ ] 跨侧移动时使用当前 signal 的展示文本。
- [ ] `clear` 从 liked/disliked 两侧移除同值。
- [ ] 每侧只保留最近 20 项。
- [ ] 按 signals 顺序应用，结果完全确定。
- [ ] 空 patch、重复添加和 clear 不存在值返回 unchanged。
- [ ] 只有内容实际变化时 version + 1。
- [ ] 只有内容实际变化时更新 `updated_at`。
- [ ] merge 函数不执行数据库 I/O，不依赖 LLM。

### 测试

- [ ] like/dislike/clear 三种 action。
- [ ] 同侧大小写去重。
- [ ] like 与 dislike 互斥移动。
- [ ] 跨侧移动展示文本规则。
- [ ] 每侧最近 20 项 cap。
- [ ] 空 patch 不增加 version。
- [ ] 重复 patch 不增加 version。
- [ ] clear 不存在项不增加 version。
- [ ] 有效多 signal patch 只增加一次 version。
- [ ] 非法 category/action、空值、超长值和 extra 字段被拒绝。

### 完成条件

- [ ] merge 逻辑是纯函数，可在无数据库、无 Agent 环境下运行。
- [ ] `.venv/bin/python -m pytest tests/agents/test_user_preferences.py -q` 通过相关 case。

---

## TASK-11：实现 SQLitePreferenceRepository 与事务安全

### 修改文件

- `app/services/memory/preference_repository.py`
- `app/services/memory/__init__.py`

### 新增文件

- `tests/services/test_preference_repository.py`

### A. 表结构与序列化

- [ ] 实现 `SQLitePreferenceRepository`。
- [ ] `setup()` 创建 `user_preferences` 表。
- [ ] 表包含 `user_id TEXT PRIMARY KEY`。
- [ ] 表包含 `preferences_json TEXT NOT NULL`。
- [ ] 表包含 `version INTEGER NOT NULL DEFAULT 0`。
- [ ] 表包含 `updated_at TEXT NOT NULL`。
- [ ] JSON 只保存四类 bucket 内容。
- [ ] version 和 updated_at 以数据库列为权威来源。
- [ ] 读取后组合并通过 `UserPreferences` 校验。

### B. Connection 与事务

- [ ] repository 接收 lifespan 创建的独立 `aiosqlite.Connection`。
- [ ] connection 使用 `isolation_level=None`。
- [ ] repository 内使用单个 `asyncio.Lock` 保护 setup/get/merge。
- [ ] 实现 `_get_unlocked()` 避免持锁后重复获取同一锁。
- [ ] merge 使用 `BEGIN IMMEDIATE`。
- [ ] 成功显式 commit。
- [ ] 任意异常显式 rollback。
- [ ] 仅当内容变化时执行 insert/update。
- [ ] unchanged merge 不写数据库、不增加 version。

### C. 错误语义

- [ ] 定义可识别的 `PreferenceDataError`。
- [ ] 损坏 JSON 抛出 `PreferenceDataError`。
- [ ] Pydantic 校验失败抛出 `PreferenceDataError`。
- [ ] 损坏数据不得被自动覆盖为空偏好。
- [ ] repository 层保留 domain error，API 层不得直接泄露异常原文。

### 测试

- [ ] 新用户读取为空偏好。
- [ ] merge 后可重新连接读取。
- [ ] 不同 user_id 偏好隔离。
- [ ] 同一 user_id 可被不同 thread 共享读取。
- [ ] unchanged merge 不更新 version/updated_at。
- [ ] 两个 `asyncio.gather()` 并发 merge 不互相覆盖。
- [ ] 并发后 version 和最终内容符合串行化结果。
- [ ] 人工写入损坏 JSON 后 get 抛出 `PreferenceDataError`。
- [ ] 损坏行保持原样，没有被 repository 自动修复。
- [ ] merge 异常时事务 rollback。

### 完成条件

- [ ] `.venv/bin/python -m pytest tests/services/test_preference_repository.py -q` 通过。
- [ ] repository 没有全局 connection 或跨 event loop 锁。
- [ ] 并发 merge 测试可重复稳定通过。

---

## TASK-12：在 FastAPI lifespan 接入双连接最终架构

### 修改文件

- `main.py`
- `app/agents/music_team_v3_1/graph.py`
- `app/api/v1/endpoints.py`
- `tests/persistence/test_sqlite_checkpoint.py`

### A. 双连接

- [ ] 保留 AsyncSqliteSaver 使用的 checkpointer connection。
- [ ] 为 SQLitePreferenceRepository 新建第二个独立 connection。
- [ ] 两个 connection 指向同一个 `STATE_DB_PATH` 文件。
- [ ] 两个 connection 都设置 WAL、busy timeout 和 foreign keys。
- [ ] preference connection 使用 `isolation_level=None`。
- [ ] 启动时先完成 repository setup，再编译最终 persistent graph。
- [ ] 最终 graph 显式注入 SQLite preference repository，不使用隐式全局。

### B. 生命周期清理

- [ ] app state 保存最终 graph 和 repository。
- [ ] 退出时先清空 graph/repository app state 引用。
- [ ] 再按明确顺序关闭 preference connection 和 saver connection。
- [ ] 部分初始化失败时已创建的 connection 也能关闭。
- [ ] shutdown 重复执行不会掩盖原始启动/运行异常。

### C. 错误策略

- [ ] saver 初始化失败导致应用启动失败或请求安全 503，不回退内存。
- [ ] repository setup 失败不创建半可用 graph。
- [ ] 运行期间 preference 读写失败由 node fail-soft；不把 repository 错误升级为任务失败。
- [ ] DB 文件路径不出现在对外错误响应。

### 测试

- [ ] lifespan 内两个 connection 均可用。
- [ ] 两个 connection 的 WAL/busy timeout 设置均正确。
- [ ] lifespan 退出后两个 connection 都关闭。
- [ ] app state 引用在关闭 connection 前被清空。
- [ ] 保存的旧 graph 在 shutdown 后不可继续访问连接。
- [ ] setup 中途异常不会泄漏第一个 connection。

### 完成条件

- [ ] FastAPI 最终架构同时具有 thread-scoped checkpoint 和 user-scoped preference。
- [ ] 两类数据共用文件但不共用 connection/职责。
- [ ] 所有资源由 lifespan 唯一拥有并释放。

---

## TASK-13：接入偏好加载、显式提取、Prompt 注入与 Trace

### 修改文件

- `app/agents/music_team_v3_1/state.py`
- `app/agents/music_team_v3_1/nodes.py`
- `app/agents/music_team_v3_1/utils.py`
- `app/agents/music_team_v3_1/prompts.py`
- `app/agents/music_team_v3_1/graph.py`
- `tests/agents/test_user_preferences.py`

### A. State 与加载

- [ ] state 只保存偏好 bucket dict、version 和更新时间等可序列化字段。
- [ ] state 不保存 Pydantic model、repository、connection、Credential 或 Cookie。
- [ ] async `init_memory_node` 使用当前 server-derived user_id 调用 repository.get。
- [ ] 读取成功后把结构化偏好写入本次 state memory。
- [ ] Disabled backend 返回空偏好并标记 backend disabled。
- [ ] 读取锁、SQLite、I/O 或损坏数据异常时使用空偏好继续主任务。
- [ ] 读取失败后本次请求跳过 cue、extractor 和 merge，避免在坏基线上覆盖数据。

### B. 显式 cue gating

- [ ] 只检查最新一条 HumanMessage 文本。
- [ ] cue 覆盖明确喜欢/不喜欢表达。
- [ ] cue 覆盖“别/不要/以后/多推荐”“不再喜欢”和清除偏好表达。
- [ ] 无 cue 时不调用 preference extractor。
- [ ] “播放周杰伦”“搜索粤语歌”等普通命令不写偏好。
- [ ] 不扫描 ToolMessage、Agent 文本或旧消息作为本次偏好来源。

### C. 结构化提取

- [ ] 使用 `llm0.with_structured_output(PreferencePatch)`。
- [ ] extractor 输入只包含最新 Human 文本和专用偏好提取 Prompt。
- [ ] Prompt 明确只支持 artist/genre/language/scene。
- [ ] 不把 song、album 或一次性操作强制映射到支持类别。
- [ ] Prompt 示例固定“不再喜欢”为 dislike。
- [ ] Prompt 示例固定“清除关于 X 的偏好”为 clear。
- [ ] extractor 返回空 patch 时不写数据库。
- [ ] extractor/校验异常时记录 failed 并继续主流程。

### D. Merge 与 fail-soft

- [ ] cue 命中且 patch 非空时调用 repository.merge。
- [ ] 更新状态严格定义为 `skipped/unchanged/updated/failed` 四种。
- [ ] 只有实际写入时 status 为 updated。
- [ ] cue 命中但空 patch/无变化时 status 为 unchanged。
- [ ] 无 cue 时 status 为 skipped。
- [ ] 任意 preference 错误不修改 `task.status`。
- [ ] preference 错误不触发 result_verifier retry。
- [ ] preference 错误不删除或替换播放/歌单 Artifact。
- [ ] 明确偏好即使后续被 intent parser 分类为 smalltalk，也已完成 merge。

### E. Prompt 注入

- [ ] 为 executor、playback 和 replier 构造精简 `USER_PREFERENCES_JSON`。
- [ ] 注入内容仅包含四类结构化 bucket，不包含 user_id/version/DB 信息。
- [ ] Prompt 把 JSON 声明为数据而不是指令。
- [ ] Prompt 明确当前用户请求优先于长期偏好。
- [ ] 空偏好不生成冗长占位文本。

### F. Trace

- [ ] init trace 记录 `preference_update_status`。
- [ ] 记录偏好 version 和 signal count。
- [ ] 记录 `storage_backend=sqlite|disabled`。
- [ ] 最多记录 `user_id_present` 布尔值，不记录实际 ID。
- [ ] memory_sync trace 记录 status、should_summarize 和 summary_version。
- [ ] 删除旧 `should_update_profile`、soul autotune 等字段。
- [ ] trace 不包含完整偏好、Cookie、DB path 或异常堆栈。

### 测试

- [ ] 无 cue 不调用模型。
- [ ] 明确喜欢、拒绝推荐、以后多推荐和 clear cue 能触发 mocked extractor。
- [ ] 测试只验证 cue + mocked `PreferencePatch` 合并，不宣称真实小模型语义准确率。
- [ ] “播放周杰伦”不写偏好。
- [ ] “我不喜欢《晴天》”因 song 类别不受支持而不写偏好。
- [ ] 只把最新 Human 文本交给 extractor。
- [ ] extractor 异常不影响 task.status。
- [ ] repository 读/写异常不影响主回复和 Artifact。
- [ ] Prompt 注入是精简 JSON，且当前请求优先。
- [ ] trace 不泄露敏感字段。

### 完成条件

- [ ] 偏好写入只由明确 cue 触发。
- [ ] 偏好失败与主工作流状态完全解耦。
- [ ] 同一用户不同 thread 能共享偏好，但 checkpoint state 继续隔离。

---

## TASK-14：补齐 Phase 3 测试、文档和既有回归适配

### 修改文件

- `README.md`
- `.env.example`
- `tests/agents/test_result_verifier.py`
- 其他受 graph factory、async init_memory 和路由变化影响的既有测试

### A. 后端测试覆盖

- [ ] `tests/persistence/test_sqlite_checkpoint.py` 覆盖重开、strict、WAL、lifecycle。
- [ ] `tests/services/test_preference_repository.py` 覆盖事务、并发、损坏数据。
- [ ] `tests/agents/test_user_preferences.py` 覆盖 schema、merge、cue、注入、fail-soft。
- [ ] `tests/api/test_local_chat_history.py` 覆盖认证、隔离、history、错误契约。
- [ ] `tests/agents/test_result_verifier.py` 适配 async init_memory 和最终可见标记。
- [ ] 覆盖 summary 后完整历史仍存在。
- [ ] 覆盖 playback Artifact canonicalize 后 id/content 不回归。
- [ ] 覆盖 preference failure 返回 200、storage failure 返回 503、普通 RuntimeError 返回 500。
- [ ] 全部 Credential、LLM、QQ 音乐网络调用使用 mock。

### B. 既有回归

- [ ] Phase 1 ToolResult 契约无回归。
- [ ] Phase 2 result verifier 一次性 retry 无回归。
- [ ] 写工具仍然不会被自动 retry。
- [ ] `last_search_results` 可持久化恢复。
- [ ] 播放和歌单 Artifact Schema 无回归。
- [ ] 既有 146 个测试继续通过。
- [ ] 新增测试不能依赖执行顺序或现有本地 Credential。

### C. 前端检查

- [ ] `localChatApi.spec.ts` service tests 通过。
- [ ] TypeScript typecheck 通过。
- [ ] 相关文件 Prettier check 通过。
- [ ] 不启动浏览器或真实后端完成 service tests。

### D. README 与安全说明

- [ ] 说明必须在 LangGraph import 前设置 `LANGGRAPH_STRICT_MSGPACK=true`。
- [ ] 说明 `MUSIC_AGENT_STATE_DB` 的默认值和相对路径语义。
- [ ] 明确 SQLite 文件未加密，只适合本地/演示环境。
- [ ] 明确当前 user_id 来自本机 Credential，不是完整多用户认证系统。
- [ ] 不宣传多实例、生产并发或跨机器部署能力。
- [ ] 说明删除 SQLite 文件会同时清除 checkpoint 和结构化偏好。
- [ ] 启动示例不包含真实 Cookie、Credential 或绝对用户路径。

### E. 静态安全检查

- [ ] 搜索确认 endpoint 不再使用静态 fallback graph。
- [ ] 搜索确认 runtime 不再写 `user_profile.md`、`history.jsonl`、`soul.md`。
- [ ] 搜索确认 state 中没有 Credential、Cookie、repository 或 connection。
- [ ] 搜索确认 response/trace 不包含 raw user_id 和 checkpoint hash。
- [ ] 搜索确认 SQLite 文件未被 Git 跟踪。

### 完成条件

- [ ] Phase 1/2/3 所有后端测试通过。
- [ ] 前端 service/type/format 检查通过。
- [ ] README 的能力边界与实际实现一致。

---

## TASK-15：执行最终验收

### A. 自动化测试

- [ ] `.venv/bin/python -m pytest -q`
- [ ] `cd music-agent-chat-ui && pnpm exec playwright test tests/localChatApi.spec.ts`
- [ ] `cd music-agent-chat-ui && pnpm exec tsc --noEmit`
- [ ] `cd music-agent-chat-ui && pnpm exec prettier --check src/features/chat-local/services/localChatApi.ts src/features/chat-local/hooks/useLocalChatSession.ts tests/localChatApi.spec.ts`

### B. 功能验收

- [ ] FastAPI 使用 AsyncSqliteSaver，不使用 InMemorySaver 保存本地聊天。
- [ ] 重启服务后相同用户/thread 能恢复 messages、summary 和 `last_search_results`。
- [ ] 不同用户同名 thread 无法互相读取或覆盖。
- [ ] 同一用户不同 thread 状态隔离、偏好共享。
- [ ] 客户端无法通过 body 切换 user_id。
- [ ] 结构化偏好按 user_id 存储并经 Pydantic 校验。
- [ ] 普通播放/搜索不写长期偏好。
- [ ] 偏好失败不影响主任务和 Artifact。
- [ ] retry 中间 PlayAgent 输出不进入 reply/history。
- [ ] History 返回 checkpoint 中完整可见消息，不截断、不去重。
- [ ] summary 后旧消息仍可恢复。
- [ ] DB/History 错误不会伪装为空成功结果。
- [ ] frontend 能展示 History/POST 错误。
- [ ] 三类最终输出恰好经过一次 fail-soft memory_sync。

### C. 生命周期与安全验收

- [ ] saver 和 preference 两个 connection 由 lifespan 创建并关闭。
- [ ] shutdown 前 app state graph/repository 引用已清空。
- [ ] strict msgpack 在 LangGraph import 前启用。
- [ ] state 不包含 Credential、Cookie、checkpoint hash 或连接对象。
- [ ] API、日志和 trace 不暴露内部 user_id、Credential、DB path 或堆栈。
- [ ] profile/history/soul 不再被用户对话写入。
- [ ] SQLite、WAL、SHM 文件未进入 Git。
- [ ] README 明确本地 SQLite 未加密和非生产多用户边界。

### D. 完成记录

- [ ] 记录最终后端测试数量。
- [ ] 记录前端三项检查结果。
- [ ] 记录人工重启恢复验证结果。
- [ ] 检查 `git diff --check`。
- [ ] 检查 `git status --short`，确认没有无关文件或运行时数据。

### 完成条件

- [ ] Spec 第 19 节全部验收标准满足。
- [ ] 未通过的检查必须保留为未完成，不得把任务状态改为 Done。
- [ ] 所有检查通过后，将本文档状态改为 Done，并填写第 5 节完成记录。

---

## 4. 建议提交边界

若需要分 commit，建议使用以下边界；当前任务不要求立即提交：

1. `feat(memory): add sqlite checkpoint lifecycle and scoped identity`
   - TASK-01 至 TASK-05
2. `refactor(memory): persist full visible chat history safely`
   - TASK-06 至 TASK-09
3. `feat(memory): add structured user preferences`
   - TASK-10 至 TASK-13
4. `test(memory): complete phase 3 regression and docs`
   - TASK-14 至 TASK-15

每个 commit 都必须保持测试可运行；不得提交 SQLite、WAL、SHM、Credential 或 Cookie 文件。

## 5. 完成记录

- 3A 完成日期：待填写
- 3A 测试结果：未执行
- 3B 完成日期：待填写
- 3B 测试结果：未执行
- 最终后端测试数量：待填写
- 前端检查结果：未执行
- 人工重启恢复：未执行
- 实际修改文件：待填写
- 遗留问题：待填写
- Git commit：未创建
