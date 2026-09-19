# Project_init_prompt.md — AI 协作强制规范

> 任何 AI 助手（或人类协作者）在本仓库工作前，必须先读本文件与 `PROJECT_MASTER.md`。

## 1. 工作流纪律
1. 每次会话开始：先读 `PROJECT_MASTER.md` 了解当前进度与阻塞项，从**最早的未完成 checklist 项**继续，禁止跨阶段实现。
2. 每完成一项：立即勾选对应 `- [x]`、更新文档头部时间戳，并在「变更记录」追加一行。
3. 需求有歧义时先问清再动手；外部依赖（凭据、接口样例）就绪状态见主控文档第三节。

## 2. 技术红线（违反即返工）
1. **只允许** QQ 开放平台官方 Bot API（已核实域名 `https://api.bot.qq.com`，详见 `docs/qq_bot_api.md`），严禁接入任何第三方非官方协议。
2. 敏感信息（AppID、Secret、Token）**只允许**经环境变量注入；严禁硬编码，严禁提交 `.env`（已被 `.gitignore` 排除）。
3. 目标运行环境为腾讯云 SCF 云函数：不得依赖本地文件持久化、不得启动常驻进程、当前保持纯标准库实现（含内置 Ed25519 参考实现 `src/ed25519.py`），新增第三方依赖必须先在主控文档登记理由。

## 3. 编码规范
- Python 3.9+ 兼容语法（SCF 运行时约束）；标准库优先。
- 云函数入口统一为 `main_handler(event, context)`，返回 API 网关集成响应格式（见 `src/bot.py::_resp`）。
- HTTP 请求用 `urllib.request`，必须显式设置超时（5 秒）。
- 日志用 `print()`（SCF 采集 stdout）；关键路径必须留日志：请求进入、指令识别、回复发送、错误。
- 模块与函数 docstring 用一行中文说明；仅在“为什么”不明显处写注释。
- 单元测试放 `tests/`，用标准库 `unittest`，必须可离线重复运行（不发真实网络请求，外部调用一律 mock）。

## 4. 提交纪律
- 一个 checklist 项 = 一次 commit，格式：`阶段N: 完成内容简述`。
- 提交前必须 `python -m unittest discover tests` 全绿。
