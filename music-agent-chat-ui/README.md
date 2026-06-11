# Music Agent Chat UI

MusicChatAgent 的 Next.js 前端，通过 FastAPI REST API 连接本地音乐 Agent。

前端不再依赖 LangGraph 开发服务器。运行聊天功能只需要启动：

1. FastAPI 后端，默认端口 `8000`
2. Next.js 前端，默认端口 `3000`

## Setup

```bash
pnpm install
```

复制 `.env.example` 为 `.env`，并确认后端地址：

```bash
NEXT_PUBLIC_API_BASE_URL=http://127.0.0.1:8000
```

启动前端：

```bash
pnpm dev
```

访问 `http://localhost:3000`，完成 QQ 音乐登录后进入聊天页面。

## Routes

- `/login`：QQ 音乐二维码登录
- `/home`：用户首页
- `/chat/local`：音乐助手聊天
- `/chat`：重定向到本地聊天
- `/chat/online`：旧地址兼容，重定向到本地聊天

## Commands

```bash
pnpm dev
pnpm build
pnpm lint
pnpm format:check
```
