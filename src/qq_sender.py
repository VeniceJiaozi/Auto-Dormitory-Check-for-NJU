"""QQ 官方 Bot API 客户端：access token 获取（带缓存）与群聊被动回复。"""

import json
import os
import time
import urllib.error
import urllib.request

API_BASE = "https://api.bot.qq.com"

APP_ID = os.environ.get("QQ_BOT_APP_ID", "")
APP_SECRET = os.environ.get("QQ_BOT_APP_SECRET", "")

_token_cache = {"token": "", "expire_at": 0.0}


def _post_json(url, payload, headers=None):
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json", **(headers or {})},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        # HTTPError 的 str 只有状态码，QQ 的 code/err_code/message 在响应体里，不读出来就永远查不到原因
        detail = e.read().decode("utf-8", "replace")[:300]
        raise RuntimeError(f"HTTP {e.code} {url[len(API_BASE):]} -> {detail}") from None


def invalidate_token():
    """丢弃缓存的 access token：重试发送前强制换一张（多实例各持一份缓存）。"""
    _token_cache.update({"token": "", "expire_at": 0.0})


def get_access_token():
    """获取 access token 并缓存至到期前 2 分钟（官方有效期 7200 秒）。"""
    now = time.time()
    if _token_cache["token"] and now < _token_cache["expire_at"]:
        return _token_cache["token"]
    data = _post_json(
        f"{API_BASE}/app/getAppAccessToken",
        {"appId": APP_ID, "clientSecret": APP_SECRET},
    )
    expires_in = int(data.get("expires_in") or 7200)
    _token_cache["token"] = data["access_token"]
    _token_cache["expire_at"] = now + max(expires_in - 120, 60)
    print("access token refreshed, expires_in =", expires_in)
    return _token_cache["token"]


def send_group_reply(group_openid, msg_id, content, msg_seq=1, msg_type=0):
    """群聊被动回复。msg_id 须为触发消息 id（5 分钟内有效，最多回复 5 次，靠 msg_seq 区分）。"""
    token = get_access_token()
    payload = {"msg_type": msg_type, "msg_id": msg_id, "msg_seq": msg_seq}
    if msg_type == 2:
        payload["markdown"] = {"content": content}
    else:
        payload["content"] = content
    data = _post_json(
        f"{API_BASE}/v2/groups/{group_openid}/messages",
        payload,
        {"Authorization": f"QQBot {token}"},
    )
    print("group reply sent, msg_id =", data.get("id"))
    return data
