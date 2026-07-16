# MusicChatAgent

一个面向 QQ 音乐场景的本地多 Agent 助手，也是用于展示 Agent 工程化能力的全栈项目：

- 后端：FastAPI + LangChain + LangGraph
- 前端：Next.js 15 本地聊天界面
- 状态：SQLite checkpoint、用户隔离、结构化偏好与历史恢复
- 可靠性：ToolResult 协议、确定性 Result Verifier、一次安全重试、Pydantic Artifact

项目只维护 `/chat/local` 主链路，不依赖在线 LangGraph 服务。

---

## 1. 核心能力

启动后可以：

- 搜索、播放和浏览 QQ 音乐歌曲与歌单
- 创建歌单、按关键词加歌并返回可验证的执行结果
- 在服务重启后恢复同一用户、同一线程的对话状态
- 保存用户明确表达的结构化音乐偏好
- 在前端渲染经过后端 Schema 校验的播放器和歌单 Artifact

三个核心工程阶段：

1. ToolResult：统一工具成功、失败、部分成功和写入不确定协议。
2. Result Verifier：确定性验证、副作用安全边界和最多一次只读重试。
3. SQLite Memory：checkpoint 持久化、用户/线程隔离、偏好与完整历史恢复。

---

## 2. 环境要求

请先确保本机具备：

- **Python**：推荐 **3.12.6**（当前项目已按该版本验证）
- **Node.js**：建议 18+
- **包管理器**：pnpm 10.5.1（由 `packageManager` 和 `pnpm-lock.yaml` 固定）
- **操作系统**：Windows / macOS / Linux 均可

---

## 3. 项目结构

- `main.py`：FastAPI 入口和 SQLite 生命周期
- `app/agents/music_team_v3_1/`：当前唯一 Agent Graph 实现
- `app/tools/`：工具协议与 QQ 音乐 Tool 适配层
- `app/services/`：QQ 音乐和用户偏好 Service
- `app/schemas/`：Artifact 与 Preference Schema
- `music-agent-chat-ui/`：Next.js 15 本地聊天前端
- `tests/`：完全离线的协议、节点、API、持久化和 Service 测试
- `reference/spec/`：三个已实现阶段的设计规格
- `docs/current/`：当前架构、进展、限制与路线图

---

## 4. 第一步：启动后端（本地）

在项目根目录（`MusicChatAgent`）打开终端。

> 你当前环境是 Python 3.12.6，可**直接安装依赖并启动**，不强制要求虚拟环境。

### 方案 A（推荐给你当前场景）：不使用虚拟环境

安装依赖：

```bash
pip install -r requirements.txt
```

复制并填写后端环境配置：

```powershell
Copy-Item .env.example .env
```

以下两项控制本地会话持久化：

```dotenv
LANGGRAPH_STRICT_MSGPACK=true
MUSIC_AGENT_STATE_DB=data/music_agent.sqlite3
```

- `LANGGRAPH_STRICT_MSGPACK` 必须在任何 LangGraph 模块导入前设置；缺失时后端会拒绝启动，避免 checkpoint 使用非严格序列化。
- `MUSIC_AGENT_STATE_DB` 的相对路径始终相对项目根目录解析，默认数据库为 `data/music_agent.sqlite3`。

启动后端：

```bash
python main.py
```

### 方案 B（可选）：使用虚拟环境

创建虚拟环境：

```bash
python -m venv .venv
```

Windows（PowerShell）激活：

```bash
.\.venv\Scripts\Activate.ps1
```

安装依赖并启动：

```bash
pip install -r requirements.txt
python main.py
```

默认监听：
- `http://localhost:8000`
- 接口前缀：`/api/v1`

例如健康探活可先尝试访问：
- `http://localhost:8000/docs`（若接口文档可用）

---

## 5. 第二步：启动前端（本地）

新开一个终端，进入前端目录：

```bash
cd music-agent-chat-ui
```

安装依赖：

```bash
corepack pnpm@10.5.1 install
```

启动开发服务：

```bash
corepack pnpm@10.5.1 run dev
```

默认地址：
- `http://localhost:3000`

---

## 6. 前端连接本地后端

前端工程支持通过环境变量直连本地后端。

在 `music-agent-chat-ui/` 下创建 `.env.local`（可参考 `.env.example`），至少确认以下配置：

```bash
NEXT_PUBLIC_API_BASE_URL=http://127.0.0.1:8000
```

> 说明：
> - `NEXT_PUBLIC_API_BASE_URL`：FastAPI 后端地址
> - 修改 `.env` 后需重启前端服务

---

## 7. 推荐测试流程（5 分钟）

1. 确认后端终端无报错并持续运行
2. 打开 `http://localhost:3000`
3. 进入 `/chat/local`（`/chat/online` 仅重定向到本地聊天）
4. 发送一条简单请求（如“推荐几首周杰伦的歌”）
5. 观察是否返回有效响应

---

## 8. 常见问题排查

### 8.1 前端请求失败 / 无响应

优先检查：
- 后端是否已启动（`python main.py`）
- `NEXT_PUBLIC_API_BASE_URL` 是否正确指向 `http://127.0.0.1:8000`
- 前端是否重启过（修改 `.env` 后必须重启）

### 8.2 跨域问题（CORS）

当前后端允许来源：`http://localhost:3000`。如果你前端不是这个端口，请同步调整后端 CORS 配置。

### 8.3 Python 依赖安装报错

建议先升级 pip 再重装：

```bash
python -m pip install --upgrade pip
pip install -r requirements.txt
```

### 8.4 端口冲突

- 前端默认 3000
- 后端默认 8000

如端口被占用，请关闭占用进程，或修改启动端口并同步更新前端环境变量。

### 8.5 本地会话与偏好数据

- FastAPI 使用 SQLite 保存 LangGraph checkpoint，服务重启后可以按当前 QQ 账号和 `thread_id` 恢复对话状态。
- 结构化偏好按当前本机 QQ Music Credential 派生的用户标识隔离；客户端不能自行提交 `user_id`。
- 当前身份绑定只适用于本地单账号/演示环境，不是 Session、JWT 或完整多用户认证系统。
- SQLite 文件没有加密，不应放置在共享目录，也不适合直接用于生产级多实例部署。
- 删除 `MUSIC_AGENT_STATE_DB` 指向的 SQLite 文件会同时清除会话 checkpoint 和结构化用户偏好。
- SQLite、WAL、SHM、Credential 和 Cookie 文件均不应提交到 Git。

---

## 9. 调试建议

- 建议保留两个终端窗口：
  - 终端 A：后端日志
  - 终端 B：前端日志
- 复现问题时记录：
  - 输入内容
  - 页面路径
  - 浏览器控制台报错
  - 后端终端报错

这些信息可以帮助快速定位前后端或外部服务问题。

---

## 10. 运行截图

### 聊天返回示例

![聊天返回示例](docs/images/chat-response.png)

### LangSmith 追踪过程

![LangSmith 追踪过程](docs/images/image.png)

> 说明：其余截图暂未加入 README，可后续按需补充。

---

## 11. 相关说明

- 前端原始模板与更完整 UI 说明见：`music-agent-chat-ui/README.md`
- 当前架构说明见：`docs/current/ARCHITECTURE.md`
- 三个已实现阶段的设计规格见：`reference/spec/`
- 本项目定位为本地单机演示，不覆盖完整生产部署、多实例和数据库加密
