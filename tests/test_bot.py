"""bot.py 行为测试：回调验证、指令路由、无关消息忽略（全部离线，外部调用 mock）。"""

import json
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
os.environ.setdefault("QQ_BOT_APP_ID", "102000000")
os.environ.setdefault("QQ_BOT_APP_SECRET", "unit-test-secret-0123456789abcdef")

import api
import bot


def _group_event(content):
    return {"body": json.dumps({
        "op": 0,
        "type": "GROUP_AT_MESSAGE_CREATE",
        "d": {"id": "MSG123", "group_openid": "GROUP1", "content": content},
    })}


class TestCallbackValidation(unittest.TestCase):
    def test_op13_returns_plain_token_and_hex_signature(self):
        event = {"body": json.dumps({"op": 13, "d": {"plain_token": "PTOKEN", "event_ts": "1726759000"}})}
        resp = bot.main_handler(event, None)
        data = json.loads(resp["body"])
        self.assertEqual(resp["statusCode"], 200)
        self.assertEqual(data["plain_token"], "PTOKEN")
        self.assertEqual(len(data["signature"]), 128)
        int(data["signature"], 16)


class TestCommandRouting(unittest.TestCase):
    def test_rollcall_command_with_mention_prefix(self):
        with mock.patch("api.build_rollcall_reply", return_value="【晚点名情况】测试回复") as build, \
                mock.patch("qq_sender.send_group_reply") as send:
            resp = bot.main_handler(_group_event("<@!102000000> 查未点名"), None)
        data = json.loads(resp["body"])
        self.assertEqual(data["replied"], "查未点名")
        build.assert_called_once()
        send.assert_called_once()
        args = send.call_args[0]
        self.assertEqual(args[:2], ("GROUP1", "MSG123"))
        self.assertEqual(args[2], "【晚点名情况】测试回复")

    def test_rollcall_api_failure_replies_fallback(self):
        with mock.patch("api.build_rollcall_reply",
                        side_effect=api.RollcallApiError("HTTP 403")), \
                mock.patch("qq_sender.send_group_reply") as send:
            resp = bot.main_handler(_group_event("查未点名"), None)
        self.assertEqual(json.loads(resp["body"])["replied"], "查未点名")
        self.assertIn("查询失败", send.call_args[0][2])

    def test_plain_command(self):
        with mock.patch("api.build_rollcall_reply", return_value="【晚点名情况】测试回复"), \
                mock.patch("qq_sender.send_group_reply") as send:
            resp = bot.main_handler(_group_event("点名"), None)
        self.assertEqual(json.loads(resp["body"])["replied"], "点名")
        send.assert_called_once()

    def test_help_command(self):
        with mock.patch("qq_sender.send_group_reply") as send:
            bot.main_handler(_group_event("帮助"), None)
        self.assertIn("用法", send.call_args[0][2])

    def test_irrelevant_message_ignored(self):
        with mock.patch("qq_sender.send_group_reply") as send:
            resp = bot.main_handler(_group_event("今晚吃什么"), None)
        data = json.loads(resp["body"])
        self.assertEqual(data["ignored"], "今晚吃什么")
        send.assert_not_called()

    def test_invalid_json_body(self):
        resp = bot.main_handler({"body": "not-json"}, None)
        self.assertEqual(json.loads(resp["body"])["error"], "invalid json body")


if __name__ == "__main__":
    unittest.main()
