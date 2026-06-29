# Task 04: 升级聊天 API 与前端工作流体验

**Risk layer:** P1

## Goal

让聊天 API 返回结构化消息、Artifact 和公开运行状态，并让前端统一消费这些合同，提供取消、错误反馈、
刷新恢复和安全的工作流阶段展示。

## Suggested Files

- Modify: `app/api/v1/endpoints.py`
- Add: `app/api/v1/schemas/chat.py`
- Add: `app/api/v1/chat_routes.py`
- Modify: `music-agent-chat-ui/src/features/chat-local/types.ts`
- Modify: `music-agent-chat-ui/src/features/chat-local/services/localChatApi.ts`
- Modify: `music-agent-chat-ui/src/features/chat-local/hooks/useLocalChatSession.ts`
- Modify: `music-agent-chat-ui/src/features/chat-local/components/AssistantMessageRenderer.tsx`
- Add: `music-agent-chat-ui/src/features/chat/run-status/`
- Add: `music-agent-chat-ui/src/features/chat/artifacts/`
- Modify: `music-agent-chat-ui/src/app/chat/local/page.tsx`
- Modify: `music-agent-chat-ui/src/app/chat/online/page.tsx`
- Test: `tests/api/test_local_chat_contract.py`
- Test: frontend component and transport tests

## Constraints

- 兼容期保留 `reply` 和安全裁剪后的 `trace`。
- 新响应存在 `artifacts` 时，不再对该响应做文本 JSON 提取。
- 公开事件不得包含内部 prompt、profile、工具参数 secret 或思维链。
- localStorage 不是权威消息库；只保存 thread id、草稿和有 schema version 的缓存。
- UI 确定性动作继续直接调用播放/歌单 API。
- HTTP 错误必须使用 FastAPI `HTTPException`，并映射稳定错误结构。

## Steps

- [ ] 先写后端 API schema 和兼容字段契约测试。
- [ ] 将 chat 路由从 600+ 行 endpoints 模块中拆出，保持 URL 兼容。
- [ ] 返回 `message/artifacts/run/reply/trace`，所有字段经 Pydantic 校验。
- [ ] 定义安全公开事件 schema 和服务端错误映射。
- [ ] 建立前端 Zod schema，未知字段前向兼容、非法 Artifact 安全拒绝。
- [ ] 抽出统一 chat transport，支持 AbortController、超时和可选 SSE。
- [ ] 将 session hook 改为显式 run 状态机，避免错误静默吞掉。
- [ ] 建立 Artifact registry；旧文本 parser 限制为历史兼容模块。
- [ ] 实现工作流阶段面板、取消按钮、可恢复错误和空状态。
- [ ] 收敛 `/chat/local` 与 `/chat/online` 到同一 feature，移除虚假的双模式描述。
- [ ] 增加前端组件测试脚本、关键交互测试和可访问性检查。

## Acceptance

```powershell
python -m pytest tests/api/test_local_chat_contract.py -q
```

```powershell
pnpm test
pnpm lint
pnpm format:check
pnpm build
```

Expected:

- 新响应无需解析 AI 文本即可渲染播放器和歌单。
- 旧客户端仍可读取 `reply`，旧历史文本 Artifact 仍能只读渲染。
- 取消后输入框恢复可用，run 显示 `cancelled` 或真实已提交结果。
- 网络、鉴权、模型和 QQ 服务错误有不同稳定错误码和用户提示。
- 页面刷新后从服务器恢复已提交消息；损坏 localStorage 不阻塞启动。
- 工作流面板只显示公开阶段和耗时，不显示内部推理内容。

## Documentation

- 更新 `docs/current/ARCHITECTURE.md` 的 API 与前端数据流。
- 更新根 README 的聊天入口和环境变量名称。
- 将旧前端播放器说明标记为历史兼容或同步新 Artifact 合同。

