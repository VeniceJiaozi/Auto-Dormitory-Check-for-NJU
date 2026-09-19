"""api.py 测试：字段映射、未报/异常分类、令牌缺失与过期报错（全部离线，HTTP 调用 mock）。"""

import io
import json
import os
import sys
import unittest
import urllib.error
from datetime import datetime
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


if __name__ == "__main__":
    unittest.main()
