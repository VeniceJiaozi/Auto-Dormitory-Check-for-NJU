"""QQ群点名机器人 - 腾讯云 SCF 云函数主入口：事件入口、回调验证与指令路由。"""

import base64
import json
import re

import api
import ed25519
import qq_sender

MENTION = re.compile(r"<@!\d+>")
ROLLCALL_COMMANDS = ("查未点名", "点名")


def main_handler(event, context):
    if not (qq_sender.APP_ID and qq_sender.APP_SECRET):
        print("missing env: QQ_BOT_APP_ID / QQ_BOT_APP_SECRET")
        return _resp({"error": "missing env config"})

    raw = event.get("body") or "{}"
    if event.get("isBase64Encoded"):
        raw = base64.b64decode(raw).decode("utf-8", "replace")
    try:
        body = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        print("invalid json body:", raw[:100])
        return _resp({"error": "invalid json body"})

    if body.get("op") == 13:
        return _resp(_verify_callback(body.get("d") or {}))
    if body.get("op") == 0 and body.get("type") == "GROUP_AT_MESSAGE_CREATE":
        return _resp(_handle_group_message(body.get("d") or {}))

    print("ignored event:", body.get("type") or body.get("op"))
    return _resp({"ignored": str(body.get("type") or body.get("op"))})


def _verify_callback(d):
    """回调地址验证：用 AppSecret 派生 Ed25519 种子对 event_ts + plain_token 签名，算法见 docs/qq_bot_api.md。"""
    plain_token = str(d.get("plain_token") or "")
    event_ts = str(d.get("event_ts") or "")
    secret = qq_sender.APP_SECRET.encode()
    seed = (secret * (32 // len(secret) + 1))[:32]
    signature = ed25519.sign((event_ts + plain_token).encode(), seed)
    return {"plain_token": plain_token, "signature": signature.hex()}


def _handle_group_message(d):
    content = MENTION.sub("", d.get("content") or "").strip()
    msg_id = d.get("id") or ""
    group_openid = d.get("group_openid") or ""

    if not (msg_id and group_openid):
        print("malformed group event:", d)
        return {"error": "malformed event"}

    if content in ROLLCALL_COMMANDS:
        reply = _rollcall_reply()
    elif content in ("帮助", "help"):
        reply = "用法：@我 并发送「查未点名」，我会回复当前未晚点名的同学名单。"
    else:
        print("ignored message:", content)
        return {"ignored": content}

    qq_sender.send_group_reply(group_openid, msg_id, reply)
    return {"replied": content}


def _rollcall_reply():
    try:
        return api.build_rollcall_reply()
    except api.RollcallApiError as e:
        print("rollcall api error:", e)
        return "点名数据查询失败，请稍后重试或联系管理员。"


def _resp(data, status=200):
    return {
        "isBase64Encoded": False,
        "statusCode": status,
        "headers": {"Content-Type": "application/json"},
        "body": json.dumps(data, ensure_ascii=False),
    }
