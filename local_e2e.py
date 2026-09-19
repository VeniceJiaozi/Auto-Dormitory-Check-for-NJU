"""本地全链路联调（手动运行）：模拟 QQ 平台事件走 main_handler 完整链路。

用法：python local_e2e.py
- 点名数据：真实调用南大表格接口（需 config/.env 中 ROLLCALL_API_TOKEN 有效）
- QQ 发送：不真发（截获打印），QQ 凭据仅用于格式检查
"""

import base64
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "src"))

for line in open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "config", ".env"), encoding="utf-8"):
    line = line.strip()
    if line and not line.startswith("#") and "=" in line:
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip())

import bot
import qq_sender

sent = []
qq_sender.send_group_reply = lambda group, msg_id, content, msg_seq=1: sent.append(
    {"group": group, "msg_id": msg_id, "content": content})


def run_case(name, event):
    print(f"\n===== {name} =====")
    resp = bot.main_handler(event, None)
    print("HTTP", resp["statusCode"], "| body:", resp["body"])
    for s in sent:
        print("→ 将发送到群:", s["group"], "| 回复内容:")
        print(s["content"])
    sent.clear()


run_case("用例1：QQ平台回调地址验证（op=13）", {"body": json.dumps({
    "op": 13,
    "d": {"plain_token": "EXAMPLE_PLAIN_TOKEN", "event_ts": "1789827632"},
})})

run_case("用例2：群消息「查未点名」（真实点名数据）", {"body": json.dumps({
    "op": 0,
    "type": "GROUP_AT_MESSAGE_CREATE",
    "d": {"id": "LOCAL_TEST_MSG", "group_openid": "LOCAL_TEST_GROUP",
          "content": "<@!1905642455> 查未点名"},
})})

raw = json.dumps({
    "op": 0,
    "type": "GROUP_AT_MESSAGE_CREATE",
    "d": {"id": "LOCAL_TEST_MSG_B64", "group_openid": "LOCAL_TEST_GROUP",
          "content": "帮助"},
}).encode()
run_case("用例3：base64 编码请求体（SCF 网关可能以此方式投递）", {
    "isBase64Encoded": True,
    "body": base64.b64encode(raw).decode(),
})
