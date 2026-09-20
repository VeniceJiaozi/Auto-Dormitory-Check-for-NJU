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

import api
import bot
import qq_sender

sent = []
qq_sender.send_group_reply = lambda group, msg_id, content, msg_seq=1, msg_type=0: sent.append(
    {"group": group, "msg_id": msg_id, "msg_seq": msg_seq, "msg_type": msg_type, "content": content})


def run_case(name, event):
    print(f"\n===== {name} =====")
    resp = bot.main_handler(event, None)
    print("HTTP", resp["statusCode"], "| body:", resp["body"])
    for s in sent:
        print(f"→ 将发送到群: {s['group']} | msg_seq={s['msg_seq']} msg_type={s['msg_type']} | 回复内容:")
        print(s["content"])
    sent.clear()


run_case("用例1：QQ平台回调地址验证（op=13）", {"body": json.dumps({
    "op": 13,
    "d": {"plain_token": "EXAMPLE_PLAIN_TOKEN", "event_ts": "1789827632"},
})})

AUTHOR = {"id": "ABCD1234EF567890ABCD1234EF567890", "username": "本地测试同学", "bot": False,
          "member_openid": "ABCD1234EF567890ABCD1234EF567890", "union_openid": "", "member_role": "普通成员"}

run_case("用例2：群消息「查未点名」（真实点名数据）", {"body": json.dumps({
    "op": 0,
    "t": "GROUP_AT_MESSAGE_CREATE",
    "d": {"id": "LOCAL_TEST_MSG", "group_openid": "LOCAL_TEST_GROUP", "author": AUTHOR,
          "content": "<@!1905642455> 查未点名"},
})})

raw = json.dumps({
    "op": 0,
    "t": "GROUP_AT_MESSAGE_CREATE",
    "d": {"id": "LOCAL_TEST_MSG_B64", "group_openid": "LOCAL_TEST_GROUP", "author": AUTHOR,
          "content": "帮助"},
}).encode()
run_case("用例3：base64 编码请求体（SCF 网关可能以此方式投递）", {
    "isBase64Encoded": True,
    "body": base64.b64encode(raw).decode(),
})


def bind_case(name, content):
    run_case(name, {"body": json.dumps({
        "op": 0,
        "t": "GROUP_AT_MESSAGE_CREATE",
        "d": {"id": "LOCAL_TEST_MSG_BIND", "group_openid": "LOCAL_TEST_GROUP", "author": AUTHOR,
              "content": content},
    })})


REAL_SID = api.fetch_rollcall_rows()[0]["student_id"]
bind_case(f"用例4：宿舍长「绑定 学号」（{REAL_SID} 取自真实点名表首行）", f"绑定 {REAL_SID}")
bind_case("用例5：绑定不存在的学号", "绑定 000000000")
