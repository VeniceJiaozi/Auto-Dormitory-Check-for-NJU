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
- **换票是否互相顶掉（2026-09-20 14:52 实测：不成立）**：约 1 秒内连续两次 `getAppAccessToken`，返回的 `expires_in` 分别是 **4145 / 4144**（不是固定的 7200）。⇒ 服务端给的是**同一张票的剩余有效期**在倒数，不是每次重新签发。所以「别处调试换了一张新票、把云函数里缓存的旧票顶失效」这个猜测没有证据支持，排查发送失败时不要再往这个方向走。

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
- 事件信封（官方「通用数据结构」，`bot.q.qq.com/wiki/develop/api-v2/dev-prepare/event-emit/payload.html`）：
  ```json
  {"id": "event_id", "op": 0, "d": {}, "s": 42, "t": "GROUP_AT_MESSAGE_CREATE"}
  ```
  **事件类型字段是 `t`，不存在 `type` 字段**；`s` 为下行序列号；`op=0` 为 Dispatch，`op=13` 为回调地址验证，回包侧另有 `op=12` HTTP Callback ACK。
  > 事故记录（2026-09-20）：本文件早先把它记成 `"type": ...`，`bot.py` 照此路由，导致真实群 @ 事件推到时 1 毫秒内被当作未知事件忽略、机器人完全无响应，而按同一错误假设手拼的自测数据却能通过——自测数据必须复刻官方信封，否则等于没有测。
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

## 6. 在群消息中 @ 指定成员（2026-09-20 真实群实测：仅 markdown 生效）
- **官方出站语法**（「文本交互」页）：文本/markdown 中嵌入 `<qqbot-at-user id="" />`，标注「@某人｜群聊、文字子频道可用」；旧协议 `<@userid>` 已废弃。
- **实测一（13:39，文本 msg_type 0）**：接口返回成功，但**客户端把标签原样显示成一串代码**，未渲染成 @。
- **实测二（13:5x，同一标签放进 markdown `msg_type:2`）：@ 成功渲染成蓝色可点的成员**。⇒ **结论：`<qqbot-at-user>` 只在 markdown 消息里生效，纯文本消息里不解析。** 官方文档未写明这一区别，只能实测得出。
- **实测附带结论**：
  - 事件 `d.author` 实际只有 `{"id","username","bot","member_openid","union_openid":"","member_role"}`——**没有 `user_openid`**；且 **`id` 与 `member_openid` 完全相同，是 32 位十六进制串，不是 QQ 号**。⇒ 拿 QQ 号无法核对成员身份，官方也没有公开的「QQ号 → openid」转换接口；@ 时 `id` 填 `member_openid`。
  - 机器人的**每一条被动回复都被平台自动加了 `@触发者` 前缀**（连不含 @ 标签的纯文本回复也有）。⇒ 判断「我们的 @ 是否生效」必须排除这个自动 @。
- **实测三（13:54 发出、约 14:00 确认，非触发者）：@ 成功**——群主发 `@机器人 测试at <某同学的 member_openid>`，被 @ 的同学确实收到提醒。**⇒ markdown 能 @ 任意群成员，不限于触发者**，「@ 未报宿舍长」方案成立。（此前两次测试目标都恰好是触发者本人，与平台自动 @ 无法区分，故必须有这一次。）
- 一次性探针指令 `测试at` 已于功能落地后从 `src/bot.py` 移除；本节的 @ 语法现由「查未点名」的第二条 markdown 回复长期使用。
- **群成员列表** `GET /v2/groups/{group_openid}/members` → `member_openid` / `username` / `joined_at`，60 QPM，官方标注「**该接口仅白名单机器人可用，请联系平台运营申请权限**」（未申请、未实测）。
- **@ 全员**：官方说明仅文字子频道且有权限时支持，群聊不可用。

## 7. 排查「函数跑了但群里没回复」

- **不用开 CLS 也能看日志**：SCF 控制台 → 函数代码 → 底部「测试事件」填好 JSON → 点「测试」，右侧「执行摘要 / 返回结果 / **执行日志**」会完整给出 `START RequestId`、代码里所有 `print` 输出和 `Report ... Duration`。
  - 事件要按云函数原生格式填：`{"body": "<QQ 事件 JSON 字符串>", "isBase64Encoded": false}`。
  - 编辑器里的内容**必须用真实键盘事件写入**（自动化时 `fill` 有效，直接改隐藏 textarea 的 value 会被 React 状态覆盖回模板）。
  - 局限：只覆盖**这次由控制台发起的调用**。真实群推送的日志仍看不到，除非开通 CLS 日志投递（按量计费，需班长同意）。
- **错误详情必须自己从响应体里捞**：`urllib.error.HTTPError` 的字符串只有 `HTTP Error 400: Bad Request`，QQ 真正的 `code` / `err_code` / `message` 在 `e.read()` 里。`src/qq_sender.py::_post_json` 已改成抛出 `HTTP 400 /v2/groups/xxx/messages -> {body}` 形式的 `RuntimeError`。
- **已确认的错误码**：`{"code":11255,"err_code":40011028,"message":"请求的资源不存在(用户/群已注销)"}` = `group_openid` 是假的（自测用伪造群号时的正常表现），不代表线上故障。

## 参考来源
- [Webhook 方式 | QQ 机器人官方文档](https://bot.q.qq.com/wiki/develop/api-v2/dev-prepare/event-emit/webhook.html)
- [发送群聊消息 | QQ 机器人官方文档](https://bot.q.qq.com/wiki/develop/api-v2/autogen/api/v2_groups_group_openid_messages.post.html)
- [获取访问凭证 | QQ 机器人官方文档](https://bot.q.qq.com/wiki/develop/api-v2/dev-prepare/access-token.html)
- [接口调用与鉴权 | QQ 机器人官方文档](https://bot.q.qq.com/wiki/develop/api-v2/dev-prepare/interface-framework/api-use.html)
- [文本交互（@ 成员语法）| QQ 机器人官方文档](https://bot.q.qq.com/wiki/develop/api-v2/server-inter/message/trans/text-chain.html)
- [获取群成员列表 | QQ 机器人官方文档](https://bot.q.qq.com/wiki/develop/api-v2/autogen/api/v2_groups_group_openid_members.get.html)
- [群聊 @机器人 消息创建事件 | QQ 机器人官方文档](https://bot.q.qq.com/wiki/develop/api-v2/autogen/event/group_at_message_create.html)
- [通用数据结构（事件信封 `t` 字段）| QQ 机器人官方文档](https://bot.q.qq.com/wiki/develop/api-v2/dev-prepare/event-emit/payload.html)
