# QQ 官方 Bot API 备忘（已核实）

> 核实时间：2026-09-19；来源：QQ 机器人官方文档（bot.q.qq.com）+ 真实凭据实测。
> 部署联调阶段若遇 401 / 校验失败，优先回官方文档复核以下细节是否有更新。

## 1. 鉴权（access token）
- `POST https://api.bot.qq.com/app/getAppAccessToken`
- 请求体：`{"appId": "<AppID>", "clientSecret": "<AppSecret>"}`
- 响应：`{"access_token": "...", "expires_in": <秒>}`（仅这两个字段，2026-09-19 实测）
- **实测注意**：文档写有效期 7200 秒，但实测签发的 `expires_in` 约 3000~3200 秒（约 50 分钟）。代码按返回值动态缓存（`src/qq_sender.py::get_access_token` 缓存至到期前 2 分钟），勿按 7200 硬编码。
- 业务 API 请求头：`Authorization: QQBot <access_token>`
- 凭据实测（2026-09-19）：token 获取成功；用伪造 `group_openid` 调发送接口返回 `{"code":11255,"err_code":40011028,"message":"请求的资源不存在(用户/群已注销)"}`——即鉴权与请求格式均被接受，仅目标群不存在，证明链路正确。

## 2. API 基础域名
- 正式环境：`https://api.bot.qq.com`
- 沙箱环境：官方文档另有说明，部署阶段确认后再补充（未核实，勿臆测）

## 3. 发送群聊消息（被动回复）
- `POST https://api.bot.qq.com/v2/groups/{group_openid}/messages`
- 请求体：
  ```json
  {"msg_type": 0, "content": "文本", "msg_id": "触发消息id", "msg_seq": 1}
  ```
- `msg_type`：0=文本、2=markdown、7=富媒体
- 被动回复规则：必须携带触发消息的 `msg_id`（**5 分钟内有效**，同一消息最多回复 **5 次**，用 `msg_seq` 1~5 区分）
- 响应：`{"id": "...", "timestamp": "...", "ext_info": {...}}`
- 实现：`src/qq_sender.py::send_group_reply`

## 4. Webhook 事件推送
- 事件格式：`{"op": 0, "id": "...", "type": "GROUP_AT_MESSAGE_CREATE", "d": {...}}`
- `d` 关键字段：`id`（消息 id，被动回复用）、`content`（文本，可能含 `<@!机器人AppID>` 前缀，需剥离）、`group_openid`、`author`、`timestamp`
- 平台推送带 `X-Signature-Ed25519` / `X-Signature-Timestamp` 请求头；**校验逻辑计划在上线前的安全加固阶段实现**（防伪造请求）
- 主控文档要求整体响应 ≤ 3 秒：各 HTTP 调用超时设为 5 秒兜底；实测本地全链路（含真实点名查询）单次 0.04~0.10 秒（校园网环境）

## 5. 回调地址验证（配置 Webhook 时平台主动发起，一次性）
- 平台发送：`{"op": 13, "d": {"plain_token": "...", "event_ts": "..."}}`
- 需返回：`{"plain_token": "<原样回传>", "signature": "<64 字节 hex 签名>"}`
- 签名算法：
  1. 种子 = AppSecret 字节序列（不足 32 字节循环填充，超出截断）取前 **32 字节**
  2. 用该种子生成 Ed25519 密钥
  3. 对 **`event_ts + plain_token`**（先 ts 后 token）拼接字符串的字节签名
  4. 签名以 **小写 hex** 编码
- 实现：`src/bot.py::_verify_callback` + `src/ed25519.py`（纯 Python 参考实现，`tests/test_ed25519.py` 用 RFC 8032 官方向量验证正确性）

## 参考来源
- [Webhook 方式 | QQ 机器人官方文档](https://bot.q.qq.com/wiki/develop/api-v2/dev-prepare/event-emit/webhook.html)
- [发送群聊消息 | QQ 机器人官方文档](https://bot.q.qq.com/wiki/develop/api-v2/autogen/api/v2_groups_group_openid_messages.post.html)
- [获取访问凭证 | QQ 机器人官方文档](https://bot.q.qq.com/wiki/develop/api-v2/dev-prepare/access-token.html)
- [接口调用与鉴权 | QQ 机器人官方文档](https://bot.q.qq.com/wiki/develop/api-v2/dev-prepare/interface-framework/api-use.html)
