"""api.py 测试：字段映射、未报/异常分类、令牌缺失与过期报错（全部离线，HTTP 调用 mock）。"""

import base64
import io
import json
import os
import sys
import unittest
import urllib.error
from datetime import datetime, timedelta
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import api

NOW = datetime(2026, 9, 19, 22, 0, tzinfo=api.TZ_SHANGHAI)

METADATA = [
    {"name": "宿舍号", "key": "0000", "type": "text"},
    {"name": "宿舍长班级", "key": "Wugn", "type": "single-select"},
    {"name": "宿舍长学号", "key": "FTLe", "type": "text"},
    {"name": "宿舍长姓名", "key": "gZPq", "type": "text"},
    {"name": "当日日期", "key": "230A", "type": "date"},
    {"name": "当日晚点名情况（格式：“全部到位”或 “某同学请假回家”）", "key": "ClfB", "type": "text"},
]

ROWS = [
    {"0000": "南二-101", "gZPq": "张三", "FTLe": "261880001",
     "230A": "2026-09-19T00:00:00+08:00", "ClfB": "全部到位"},
    {"0000": "南二-102", "gZPq": "李四", "FTLe": "261880002",
     "230A": "2026-09-19T00:00:00+08:00", "ClfB": "未全部到位"},
    {"0000": "陶三-201", "gZPq": "王五", "FTLe": "261880003",
     "230A": None, "ClfB": None},
    {"0000": "陶三-202", "gZPq": "赵六", "FTLe": "261880004",
     "230A": "2026-09-18T00:00:00+08:00", "ClfB": "全部到位"},
]

NORMALIZED_ROWS = [
    {"dorm": "南二-101", "leader": "张三", "student_id": "261880001",
     "date": "2026-09-19T00:00:00+08:00", "status": "全部到位"},
    {"dorm": "南二-102", "leader": "李四", "student_id": "261880002",
     "date": "2026-09-19T00:00:00+08:00", "status": "未全部到位"},
    {"dorm": "陶三-201", "leader": "王五", "student_id": "261880003",
     "date": None, "status": None},
    {"dorm": "陶三-202", "leader": "赵六", "student_id": "261880004",
     "date": "2026-09-18T00:00:00+08:00", "status": "全部到位"},
]


def _api_response():
    return {"success": True, "error_message": "", "metadata": METADATA, "results": ROWS}


def _mock_urlopen(payload):
    resp = mock.MagicMock()
    resp.__enter__.return_value = resp
    resp.read.return_value = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    resp.status = 200
    return mock.patch("urllib.request.urlopen", return_value=resp)


class TestFetchRows(unittest.TestCase):
    def test_parses_rows_via_metadata_keymap(self):
        with mock.patch.object(api, "APP_TOKEN", "T"), _mock_urlopen(_api_response()) as u:
            rows = api.fetch_rollcall_rows()
        self.assertEqual(rows, NORMALIZED_ROWS)
        req = u.call_args[0][0]
        self.assertIn("page_id=XY1Z", req.full_url)
        self.assertEqual(req.headers.get("Authorization"), "Token T")

    def test_missing_token_raises(self):
        with mock.patch.object(api, "APP_TOKEN", ""):
            with self.assertRaises(api.RollcallApiError):
                api.fetch_rollcall_rows()

    def test_http_403_raises_with_token_hint(self):
        with mock.patch.object(api, "APP_TOKEN", "T"), \
                mock.patch("urllib.request.urlopen",
                           side_effect=urllib.error.HTTPError(None, 403, "Forbidden", None, None)):
            with self.assertRaises(api.RollcallApiError) as ctx:
                api.fetch_rollcall_rows()
        self.assertIn("令牌过期", str(ctx.exception))

    def test_metadata_without_dorm_column_raises(self):
        payload = _api_response()
        payload["metadata"] = [m for m in METADATA if m["name"] != "宿舍号"]
        with mock.patch.object(api, "APP_TOKEN", "T"), _mock_urlopen(payload):
            with self.assertRaises(api.RollcallApiError):
                api.fetch_rollcall_rows()


class TestBuildReply(unittest.TestCase):
    def test_classifies_pending_and_abnormal(self):
        reply = api.build_rollcall_reply(NORMALIZED_ROWS, now=NOW)
        self.assertIn("【晚点名情况 2026-09-19】", reply)
        self.assertIn("未报宿舍 2 个", reply)
        self.assertNotIn("- 南二-101", reply)  # 已报且到位的宿舍不进未报列表
        self.assertIn("- 陶三-201（王五）", reply)
        self.assertIn("- 陶三-202（赵六）", reply)
        self.assertIn("异常情况 1 个", reply)
        self.assertIn("- 南二-102（李四）：未全部到位", reply)
        self.assertIn("其余 1 个宿舍已报且全部到位", reply)

    def test_all_ok_reply(self):
        rows = [NORMALIZED_ROWS[0]]
        reply = api.build_rollcall_reply(rows, now=NOW)
        self.assertIn("全部 1 个宿舍已报且全部到位", reply)
        self.assertNotIn("未报", reply)

    def test_empty_rows(self):
        reply = api.build_rollcall_reply([], now=NOW)
        self.assertIn("暂无数据", reply)


class TestTokenExpiry(unittest.TestCase):
    @staticmethod
    def _jwt(expires_at):
        def b64(obj):
            return base64.urlsafe_b64encode(json.dumps(obj).encode()).decode().rstrip("=")
        return f"{b64({'alg': 'HS256'})}.{b64({'exp': int(expires_at.timestamp())})}.sig"

    def _hours(self, hours_left):
        return mock.patch.object(api, "APP_TOKEN", self._jwt(NOW + timedelta(hours=hours_left)))

    def test_hours_parsed_from_jwt(self):
        with self._hours(72):
            self.assertAlmostEqual(api.token_hours_left(NOW), 72, places=1)

    def test_non_jwt_token_yields_none_without_breaking_reply(self):
        with mock.patch.object(api, "APP_TOKEN", "plain-old-token"):
            self.assertIsNone(api.token_hours_left(NOW))
            self.assertEqual(api.token_expiry_notice(NOW), "")

    def test_unusable_exp_claim_yields_none(self):
        bad = f"{self._jwt(NOW).split('.')[0]}.{base64.urlsafe_b64encode(b'not-json').decode().rstrip('=')}.sig"
        with mock.patch.object(api, "APP_TOKEN", bad):
            self.assertIsNone(api.token_hours_left(NOW))

    def test_no_notice_while_plenty_of_time(self):
        with self._hours(72):
            self.assertEqual(api.token_expiry_notice(NOW), "")
            self.assertNotIn("提醒", api.build_rollcall_reply(NORMALIZED_ROWS, now=NOW))

    def test_notice_appended_near_expiry(self):
        with self._hours(10):
            reply = api.build_rollcall_reply(NORMALIZED_ROWS, now=NOW)
            empty = api.build_rollcall_reply([], now=NOW)
        self.assertIn("将在约 10 小时后到期", reply)
        self.assertTrue(reply.endswith("否则查询会失败。"))
        self.assertIn("点名表暂无数据", empty)
        self.assertIn("【提醒】", empty)

    def test_notice_when_already_expired(self):
        with self._hours(-1):
            self.assertIn("已过期", api.token_expiry_notice(NOW))


class TestFindLeader(unittest.TestCase):
    def test_matches_student_id_regardless_of_spaces(self):
        self.assertEqual(api.find_leader(NORMALIZED_ROWS, " 261880003 ")["dorm"], "陶三-201")

    def test_blank_or_unknown_returns_none(self):
        self.assertIsNone(api.find_leader(NORMALIZED_ROWS, ""))
        self.assertIsNone(api.find_leader(NORMALIZED_ROWS, None))
        self.assertIsNone(api.find_leader(NORMALIZED_ROWS, "261889999"))


if __name__ == "__main__":
    unittest.main()
