# 开发注意事项

本文档记录 2026-07-16 集成后仍然有效的风险和约束。

## 已解决的旧风险

- Agent 节点和 Verifier 已只返回 message delta；完整后端测试覆盖 reducer、ToolMessage 和多轮行为。
- `memory_sync` 不再原地删除或裁剪 checkpoint messages。
- 全局可写 `user_profile.md` 和 `history.jsonl` 已退出在线权威路径。
- soul 只作为只读策略输入，普通请求不再运行时改写。
- music、playback 和 smalltalk 都会经过 memory sync/finalizer。
- 工具成功/失败不再依赖中文关键词，核心工具使用结构化 ToolResult。
- history 从 SQLite checkpoint 恢复完整可见消息，不再从 preview 重建。
- `OPENAI_MODEL` 不再硬编码，DeepSeek/OpenAI 兼容供应商可以通过环境变量配置。

## 当前风险

### 最新请求优先级仍缺少独立状态合同

当前执行输入已经有有界近期消息、摘要和结构化偏好，但尚未实现设计中的 `CurrentRequest`/`ContextEnvelope` 与真实 tokenizer 预算。需要继续用“旧要求 vs 最新纠正”评测保护最新指令。

### 本地身份不是生产认证

身份来自当前机器上的单个 QQ Music Credential。它能隔离 checkpoint key 和偏好，但不提供 Session/JWT、多账号切换、Credential 加密或权限管理。不要把当前 API 直接暴露到不受信网络。

### SQLite 只面向单进程本地运行

数据库开启 WAL、busy timeout 和事务锁，但没有多实例分布式锁、备份恢复、字段加密或在线迁移系统。SQLite 文件和 Credential 文件都不得提交，也不应放在共享目录。

### 偏好抽取仍依赖 LLM

严格 schema、版本和事务可以防止非法状态落库，但无法保证模型语义判断永远正确。当前只在显式偏好线索出现时抽取，并采用 fail-soft；后续仍需要用户查看、纠错和失效入口。

### Artifact 仍保留旧文本兼容解析

新响应使用 `data.artifacts`，但为了旧历史兼容，后端 collector 和前端 renderer 仍可解析合法 JSON 文本。新功能不得重新依赖文本解析；待历史迁移窗口结束后再删除 fallback。

### Run 合同仍是第一阶段

当前公开 `run` 只有 succeeded/failed 与稳定错误码，还没有 run_id、公开阶段事件、取消、幂等键或流式恢复。副作用工具的未知结果已经禁止自动重试，但完整取消语义仍待设计。

### API 模块仍然过宽

`app/api/v1/endpoints.py` 同时承载聊天、认证、用户、歌曲、歌单和播放器直连接口。后续拆分必须保留路由路径、响应模型、lifespan 注入和测试 monkeypatch 边界。

### 外部服务 E2E 尚未执行

237 个后端测试和前端构建使用 fake graph/service 验证内部合同，没有证明真实 QQ Music API、账号权限、播放 URL 或当前外部模型服务始终可用。面试演示前应执行一次受控真实 E2E。

### 前端 lint 存在既有 warnings

Next lint 为 0 error，但仍有 hook dependency 和 fast-refresh warnings；`next lint` 本身也已提示弃用。当前不阻塞构建，后续应迁移 ESLint CLI 并逐项处理。

## 工作约定

- 修改 ToolResult、Verifier、身份、记忆和副作用安全前先增加失败测试。
- UI 确定性动作继续留在 LLM 路径之外。
- 记忆写入风险高于读取；无法确认时宁可不写。
- 不返回或记录 API key、Credential、完整私密历史、system prompt 或思维链。
- 只有真实运行过的测试、构建或 E2E 才能进入 `PROGRESS.md`。
