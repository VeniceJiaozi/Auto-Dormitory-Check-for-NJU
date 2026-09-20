"""bot.py 行为测试：回调验证、指令路由、@ 清单与「绑定」（全部离线，外部调用 mock）。"""

import json
import os
import sys
import unittest
from datetime import datetime
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
os.environ.setdefault("QQ_BOT_APP_ID", "102000000")
os.environ.setdefault("QQ_BOT_APP_SECRET", "unit-test-secret-0123456789abcdef")

import api
import bot

TODAY = datetime.now(api.TZ_SHANGHAI).strftime("%Y-%m-%d")
ROSTER = {"261880002": "OPENID_LI"}

# 一号已报且到位；二号未报且已绑定；三号未报但未绑定
ROWS = [
    {"dorm": "南二-101", "leader": "张三", "student_id": "261880001",
     "date": f"{TODAY}T00:00:00+08:00", "status": "全部到位"},
    {"dorm": "南二-102", "leader": "李四", "student_id": "261880002",
     "date": None, "status": None},
    {"dorm": "陶三-201", "leader": "王五", "student_id": "261880003",
     "date": None, "status": None},
]


def _group_event(content, author=None):
    """复刻官方「通用数据结构」网关信封：事件类型在 `t` 字段（不是 `type`）。"""
    return {"body": json.dumps({
        "id": "EVENT1",
        "op": 0,
        "d": {"id": "MSG123", "group_openid": "GROUP1", "content": content,
              "author": author if author is not None else
              {"id": "OPENID_ZHANG", "username": "张三", "bot": False,
               "member_openid": "OPENID_ZHANG", "union_openid": "", "member_role": "普通成员"}},
        "s": 42,
        "t": "GROUP_AT_MESSAGE_CREATE",
    })}


def _calls(send):
    return [(c.kwargs["msg_seq"], c.kwargs.get("msg_type", 0), c.args[2]) for c in send.call_args_list]


class TestCallbackValidation(unittest.TestCase):
    def test_op13_returns_plain_token_and_hex_signature(self):
        event = {"body": json.dumps({"op": 13, "d": {"plain_token": "PTOKEN", "event_ts": "1726759000"}})}
        resp = bot.main_handler(event, None)
        data = json.loads(resp["body"])
        self.assertEqual(resp["statusCode"], 200)
        self.assertEqual(data["plain_token"], "PTOKEN")
        self.assertEqual(len(data["signature"]), 128)
        int(data["signature"], 16)


class TestRollcallCommand(unittest.TestCase):
    def setUp(self):
        patcher = mock.patch.dict(os.environ, {bot.ROSTER_ENV: json.dumps(ROSTER)})
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_text_summary_then_markdown_mentions_bound_monitor(self):
        with mock.patch("api.fetch_rollcall_rows", return_value=ROWS), \
                mock.patch("qq_sender.send_group_reply") as send:
            resp = bot.main_handler(_group_event("<@!102000000> 查未点名"), None)
        data = json.loads(resp["body"])
        self.assertEqual(data["replied"], "rollcall")
        self.assertEqual(data["pending"], 2)
        self.assertEqual([seq for seq, _, _ in _calls(send)], [1, 2])
        self.assertEqual([mt for _, mt, _ in _calls(send)], [0, 2])
        summary, mentions = _calls(send)[0][2], _calls(send)[1][2]
        self.assertIn(f"【晚点名情况 {TODAY}】", summary)
        self.assertIn("- 南二-102（李四）", summary)
        # @ 只对已绑定的宿舍长生效，未绑定的只能列名字
        self.assertIn('<qqbot-at-user id="OPENID_LI" />', mentions)
        self.assertNotIn("OPENID_ZHANG", mentions)
        self.assertIn("陶三-201（王五）", mentions)

    def test_empty_roster_still_lists_unbound(self):
        with mock.patch.dict(os.environ, {bot.ROSTER_ENV: ""}), \
                mock.patch("api.fetch_rollcall_rows", return_value=ROWS), \
                mock.patch("qq_sender.send_group_reply") as send:
            bot.main_handler(_group_event("点名"), None)
        mentions = _calls(send)[1][2]
        self.assertNotIn("qqbot-at-user", mentions)
        self.assertIn("南二-102（李四）", mentions)
        self.assertIn("陶三-201（王五）", mentions)

    def test_all_reported_sends_single_text_reply(self):
        rows = [ROWS[0]]
        with mock.patch("api.fetch_rollcall_rows", return_value=rows), \
                mock.patch("qq_sender.send_group_reply") as send:
            resp = bot.main_handler(_group_event("查未点名"), None)
        self.assertEqual(json.loads(resp["body"])["pending"], 0)
        send.assert_called_once()
        self.assertEqual(send.call_args.kwargs["msg_seq"], 1)

    def test_api_failure_replies_fallback(self):
        with mock.patch("api.fetch_rollcall_rows", side_effect=api.RollcallApiError("HTTP 403")), \
                mock.patch("qq_sender.send_group_reply") as send:
            resp = bot.main_handler(_group_event("查未点名"), None)
        self.assertEqual(json.loads(resp["body"])["error"], "rollcall api")
        self.assertIn("查询失败", send.call_args[0][2])

    def test_send_failure_returns_200_instead_of_crashing(self):
        with mock.patch("api.fetch_rollcall_rows", return_value=ROWS), \
                mock.patch("bot.time.sleep"), \
                mock.patch("qq_sender.send_group_reply",
                           side_effect=RuntimeError("HTTP Error 400: Bad Request")):
            resp = bot.main_handler(_group_event("查未点名"), None)
        data = json.loads(resp["body"])
        self.assertEqual(resp["statusCode"], 200)
        self.assertEqual(data["sent"], [False, False])


class TestSendRetry(unittest.TestCase):
    """真实群出现过「函数跑了 404ms 但群里没回复」，故失败时换 token 重试一次。"""

    def test_second_attempt_succeeds_after_token_invalidated(self):
        with mock.patch("api.fetch_rollcall_rows", return_value=[ROWS[0]]), \
                mock.patch("bot.time.sleep"), \
                mock.patch("qq_sender.invalidate_token") as invalidate, \
                mock.patch("qq_sender.send_group_reply",
                           side_effect=[RuntimeError("HTTP 401"), mock.MagicMock()]) as send:
            resp = bot.main_handler(_group_event("查未点名"), None)
        self.assertEqual(json.loads(resp["body"])["sent"], [True])
        self.assertEqual(send.call_count, 2)
        invalidate.assert_called_once_with()


class TestBindCommand(unittest.TestCase):
    def test_valid_student_id_echoes_pair_for_monitor(self):
        """回复里回显「学号=openid」，班长把它写进 QQ_ROSTER_JSON 后真 @ 才生效。"""
        with mock.patch("api.fetch_rollcall_rows", return_value=ROWS), \
                mock.patch("qq_sender.send_group_reply") as send:
            resp = bot.main_handler(_group_event("绑定 261880002"), None)
        self.assertEqual(json.loads(resp["body"])["replied"], "text")
        text = send.call_args[0][2]
        self.assertIn("绑定成功", text)
        self.assertIn("南二-102 宿舍长 李四", text)
        self.assertIn("261880002=OPENID_ZHANG", text)

    def test_student_id_without_space_is_still_routed(self):
        """真实群里同学发的是「绑定261880002」（无空格），曾被当作无关消息静默忽略。"""
        with mock.patch("api.fetch_rollcall_rows", return_value=ROWS), \
                mock.patch("qq_sender.send_group_reply") as send:
            resp = bot.main_handler(_group_event("绑定261880002"), None)
        self.assertEqual(json.loads(resp["body"])["replied"], "text")
        self.assertIn("绑定成功", send.call_args[0][2])

    def test_unknown_student_id_is_rejected(self):
        with mock.patch("api.fetch_rollcall_rows", return_value=ROWS), \
                mock.patch("qq_sender.send_group_reply") as send:
            bot.main_handler(_group_event("绑定 261889999"), None)
        text = send.call_args[0][2]
        self.assertIn("没有学号 261889999", text)
        self.assertNotIn("OPENID_ZHANG=", text)

    def test_missing_argument_returns_usage(self):
        with mock.patch("api.fetch_rollcall_rows") as fetch, \
                mock.patch("qq_sender.send_group_reply") as send:
            bot.main_handler(_group_event("绑定"), None)
        self.assertIn("本人学号", send.call_args[0][2])
        fetch.assert_not_called()

    def test_api_failure_replies_fallback(self):
        with mock.patch("api.fetch_rollcall_rows", side_effect=api.RollcallApiError("request failed")), \
                mock.patch("qq_sender.send_group_reply") as send:
            resp = bot.main_handler(_group_event("绑定 261880002"), None)
        self.assertEqual(json.loads(resp["body"])["error"], "rollcall api")
        self.assertIn("查询失败", send.call_args[0][2])


class TestOtherRouting(unittest.TestCase):
    def test_help_command(self):
        with mock.patch("qq_sender.send_group_reply") as send:
            bot.main_handler(_group_event("帮助"), None)
        self.assertIn("用法", send.call_args[0][2])
        self.assertIn("绑定", send.call_args[0][2])

    def test_irrelevant_message_ignored(self):
        with mock.patch("qq_sender.send_group_reply") as send:
            resp = bot.main_handler(_group_event("今晚吃什么"), None)
        self.assertEqual(json.loads(resp["body"])["ignored"], "今晚吃什么")
        send.assert_not_called()

    def test_malformed_event_without_msg_id(self):
        event = {"body": json.dumps({"op": 0, "t": "GROUP_AT_MESSAGE_CREATE", "s": 1, "d": {}})}
        with mock.patch("qq_sender.send_group_reply") as send:
            resp = bot.main_handler(event, None)
        self.assertEqual(json.loads(resp["body"])["error"], "malformed event")
        send.assert_not_called()

    def test_invalid_json_body(self):
        resp = bot.main_handler({"body": "not-json"}, None)
        self.assertEqual(json.loads(resp["body"])["error"], "invalid json body")

    def test_other_dispatch_events_are_ignored(self):
        event = {"body": json.dumps({"op": 0, "t": "GROUP_ADD_ROBOT", "d": {}, "s": 1})}
        with mock.patch("qq_sender.send_group_reply") as send:
            resp = bot.main_handler(event, None)
        self.assertEqual(json.loads(resp["body"])["ignored"], "GROUP_ADD_ROBOT")
        send.assert_not_called()

    def test_type_field_is_not_routed(self):
        """官方网关信封的事件类型只有 `t`；曾按 `type` 路由导致真实群事件被静默忽略。"""
        event = {"body": json.dumps({
            "op": 0, "type": "GROUP_AT_MESSAGE_CREATE",
            "d": {"id": "MSG123", "group_openid": "GROUP1", "content": "查未点名"},
        })}
        with mock.patch("qq_sender.send_group_reply") as send:
            resp = bot.main_handler(event, None)
        self.assertEqual(json.loads(resp["body"])["ignored"], "0")
        send.assert_not_called()


class TestRosterParsing(unittest.TestCase):
    def test_missing_or_malformed_env_is_empty_roster(self):
        for raw in ("", "   ", "not-json", '["a"]'):
            with mock.patch.dict(os.environ, {bot.ROSTER_ENV: raw}):
                self.assertEqual(bot._roster(), {})

    def test_keys_and_values_are_stripped(self):
        with mock.patch.dict(os.environ, {bot.ROSTER_ENV: '{" 261880002 ": " OPENID_LI "}'}):
            self.assertEqual(bot._roster(), {"261880002": "OPENID_LI"})


if __name__ == "__main__":
    unittest.main()
