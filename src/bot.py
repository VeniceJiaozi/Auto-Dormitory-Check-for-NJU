"""QQ群点名机器人 - 腾讯云 SCF 云函数主入口：事件入口、回调验证与指令路由。"""

import base64
import json
import os
import re
import time

import api
import ed25519
import qq_sender

MENTION = re.compile(r"<@!\d+>")
ROLLCALL_COMMANDS = ("查未点名", "点名")
BIND_COMMAND = "绑定"
# 宿舍长绑定表 {学号: member_openid}，由班长在云函数环境变量中维护（SCF 无持久磁盘）
ROSTER_ENV = "QQ_ROSTER_JSON"
# 实测：@ 成员标签只在 markdown 消息（msg_type=2）里渲染成蓝色可点名字，纯文本会原样显示标签
MSG_TYPE_MARKDOWN = 2
HELP_TEXT = (
    "用法：@我 发送「查未点名」查看未报与异常宿舍名单。\n"
    "宿舍长请 @我 发送「绑定 本人学号」，之后查未点名时会被直接 @ 到。"
)


def at_tag(openid):
    return f'<qqbot-at-user id="{openid}" />'


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
    # 官方 payload 用 `t` 表示事件类型（op=0 Dispatch 时），不是 `type`
    if body.get("op") == 0 and body.get("t") == "GROUP_AT_MESSAGE_CREATE":
        return _resp(_handle_group_message(body.get("d") or {}))

    print("ignored event:", body.get("t") or body.get("op"))
    return _resp({"ignored": str(body.get("t") or body.get("op"))})


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
        return _handle_rollcall(group_openid, msg_id)

    if content.startswith(BIND_COMMAND):
        sender = str((d.get("author") or {}).get("member_openid") or "")
        return _handle_bind(group_openid, msg_id, sender, content[len(BIND_COMMAND):].strip())

    if content in ("帮助", "help"):
        return {"sent": _send(group_openid, msg_id, 1, HELP_TEXT)}

    print("ignored message:", content)
    return {"ignored": content}


def _handle_rollcall(group_openid, msg_id):
    """两条被动回复：先文本名单，再用 markdown @ 未报宿舍长（被动回复靠 msg_seq 区分）。"""
    rows = _fetch_rows(group_openid, msg_id)
    if rows is None:
        return {"error": "rollcall api"}
    sent = [_send(group_openid, msg_id, 1, api.build_rollcall_reply(rows))]
    pending = api.summarize(rows)["pending"]
    if pending:
        sent.append(_send(group_openid, msg_id, 2,
                          _mention_unreported(pending, _roster()), msg_type=MSG_TYPE_MARKDOWN))
    return {"replied": "rollcall", "pending": len(pending), "sent": sent}


def _handle_bind(group_openid, msg_id, sender, student_id):
    if not student_id:
        return _reply(group_openid, msg_id, f"用法：@我 发送「{BIND_COMMAND} 本人学号」（限宿舍长）。")
    if not sender:
        return _reply(group_openid, msg_id, "未取到您的群成员标识，请重新 @我 再试。")
    rows = _fetch_rows(group_openid, msg_id)
    if rows is None:
        return {"error": "rollcall api"}
    row = api.find_leader(rows, student_id)
    if not row:
        return _reply(group_openid, msg_id,
                      f"点名表里没有学号 {student_id} 对应的宿舍长，请核对学号或联系班长。")
    # 回复中回显「学号=openid」，由班长抄进 QQ_ROSTER_JSON 环境变量后才真正生效
    return _reply(
        group_openid, msg_id,
        f"绑定成功：{row['dorm']} 宿舍长 {row['leader']}。\n"
        f"待班长登记后即可在查未点名时 @ 到您。\n{student_id}={sender}")


def _fetch_rows(group_openid, msg_id):
    """拉点名表；失败时已回复兜底文案并返回 None。"""
    try:
        return api.fetch_rollcall_rows()
    except api.RollcallApiError as e:
        print("rollcall api error:", e)
        _send(group_openid, msg_id, 1, "点名数据查询失败，请稍后重试或联系管理员。")
        return None


def _reply(group_openid, msg_id, text):
    sent = _send(group_openid, msg_id, 1, text)
    return {"replied": "text", "sent": sent}


def _roster():
    """读 QQ_ROSTER_JSON（{学号: member_openid}）；未配置或格式错误按空表处理。"""
    raw = os.environ.get(ROSTER_ENV) or ""
    if not raw.strip():
        return {}
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        print(f"invalid {ROSTER_ENV}:", e)
        return {}
    return {str(k).strip(): str(v).strip() for k, v in data.items()} if isinstance(data, dict) else {}


def _mention_unreported(pending, roster):
    """未报宿舍的 @ 清单：已绑定的用 @ 标签，未绑定的列宿舍号与姓名。"""
    tags, unbound = [], []
    for r in pending:
        openid = roster.get(str(r.get("student_id") or "").strip())
        if openid:
            tags.append(at_tag(openid))
        else:
            unbound.append(f"{r['dorm']}（{r['leader']}）")
    lines = []
    if tags:
        lines.append("请以下宿舍长尽快完成晚点名登记：\n" + " ".join(tags))
    if unbound:
        lines.append("以下宿舍长未绑定，请自行留意：" + "、".join(unbound))
    return "\n\n".join(lines)


def _send(group_openid, msg_id, seq, content, msg_type=0):
    """被动回复失败时换一张 access token 重试一次（真实群出现过「函数跑了但群里没回复」）。"""
    for attempt in (1, 2):
        try:
            qq_sender.send_group_reply(group_openid, msg_id, content, msg_seq=seq, msg_type=msg_type)
            return True
        except Exception as e:
            print(f"send group reply (msg_seq={seq}) failed, try {attempt}:", e)
            if attempt == 2:
                return False
            qq_sender.invalidate_token()
            time.sleep(0.4)


def _resp(data, status=200):
    return {
        "isBase64Encoded": False,
        "statusCode": status,
        "headers": {"Content-Type": "application/json"},
        "body": json.dumps(data, ensure_ascii=False),
    }
