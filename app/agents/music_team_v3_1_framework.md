# Music Team v3.1 框架构思书

## 1. 目标

在 `v3` 的 Node + Edge 基础上，升级为更标准、可扩展、可维护的多代理图架构，重点解决：

1. 标准化任务状态流转：`pending/running/waiting_user/done/failed`
2. 增加 `intent_parser_node` 做一级意图分流
3. 预接 `playback` 子图（单曲播放/歌单浏览后点播）
4. 增加长期记忆文件：
   - `user_profile.md`（用户画像）
   - `soul.md`（多代理角色宪法）

---

## 2. 设计原则

- **单一共享状态**：所有节点读写同一个 state，避免 supervisor/worker 状态割裂
- **图内显式记忆更新**：summary/profile/soul 由节点更新并写回 state
- **可插拔子图**：音乐操作、播放控制、未来扩展都走统一路由协议
- **可审计**：每轮都可追踪 `task_status`、路由、失败原因
- **受控自我更新**：`soul.md` 可小幅进化，但有不可突破边界

---

## 3. 状态模型（v3.1）

建议 State 分层：

- 会话层：`thread_id`, `messages`
- 任务层：`task`
- 记忆层：`memory`
- 控制层：`control`
- 扩展层：`extensions`

关键字段：

- `task.intent`: `smalltalk/music_ops/playback/unknown`
- `task.status`: `pending/running/waiting_user/done/failed`
- `task.required_slots/missing_slots`: 槽位机制（如歌单名、dirid）
- `memory.summary`: 短期摘要
- `memory.user_profile`: 用户画像内容
- `memory.soul`: 角色宪法内容
- `control.route`: `chat_replier/music_ops_subgraph/playback_subgraph`

---

## 4. 图流程

主图建议：

`START -> intent_parser -> supervisor_router -> domain_node -> memory_sync -> chat_replier -> finalizer -> END`

### 4.1 intent_parser_node
- 识别用户意图：闲聊 / 音乐操作 / 播放控制
- 初始化任务：`task.status = pending`

### 4.2 supervisor_router_node
- 根据 `intent + missing_slots + retry` 路由
- 缺槽位时进入 `waiting_user` 并转 `chat_replier`

### 4.3 domain_node（统一入口）
- `music_ops_subgraph`：歌单与歌曲相关操作
- `playback_subgraph`：播放控制（预接，可先返回能力边界）

### 4.4 memory_sync_node
- 对话长度超阈值时更新 `summary`
- 识别到偏好变化时更新 `user_profile.md`
- 低频受控更新 `soul.md`

### 4.5 chat_replier_node
- 对用户输出自然语言
- 严格依据 `task.status` 组织话术

### 4.6 finalizer_node
- 收尾状态（例如清理临时路由、重置计数器）

---

## 5. task_status 标准流转

- `pending -> running -> done`
- `pending -> running -> waiting_user`
- `pending -> running -> failed`
- `waiting_user -> pending`（用户补充信息后）
- `failed -> pending`（仅当条件变化且用户明确重试）

判定原则：

- `waiting_user`：缺必要信息但可继续
- `failed`：当前无法继续（权限/接口/能力边界）
- `done`：已完成且可结构化转述结果

---

## 6. user_profile.md 方案

建议路径：`app/agents/memory/user_profile.md`

建议结构：

- 基础偏好（歌手/风格/语言/场景）
- 操作习惯（命名偏好、加歌策略）
- 约束禁忌（不想要的内容）
- 长期实体（常用歌单、dirid、关键词）
- 更新时间与原因

更新规则：

- 只做增量更新
- 明确偏好优先写入
- 弱信号不写

---

## 7. soul.md 方案

建议路径：`app/agents/memory/soul.md`

建议结构：

- Identity（身份与边界）
- Non-Negotiables（不可突破）
- Style（语气与表达）
- Decision Policy（决策优先级）
- Evolution Log（版本与变更记录）

更新规则：

- 可更新：`Style`、`Decision Policy` 小参数、`Evolution Log`
- 不可更新：`Identity` 核心边界、`Non-Negotiables`
- 建议配置冷却窗口，避免高频漂移

---

## 8. playback 子图预接协议

统一动作结构：

- `type`: `play_music` / `playlist_browser`
- `song_mid`
- `playlist_dirid`
- `page` / `page_size`

先做协议与路由，后续接真实工具时不影响主图框架。

---

## 9. 迁移建议（v3 -> v3.1）

1. 先引入 v3.1 新 State 与 `intent_parser_node`
2. 再加标准 `task_status` 流转
3. 接入 `memory_sync_node` 托管 summary/profile/soul
4. 最后插入 playback 子图

---

## 10. 分阶段落地

- **Phase 1**：状态模型 + 意图分流 + 标准状态流转
- **Phase 2**：`user_profile.md` 读写节点
- **Phase 3**：`soul.md` 受控更新
- **Phase 4**：播放子图接入真实播放能力
