"""qq_sender.py 测试：token 获取/缓存与群回复请求格式（HTTP 层 mock）。"""

import json
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
os.environ.setdefault("QQ_BOT_APP_ID", "102000000")
os.environ.setdefault("QQ_BOT_APP_SECRET", "unit-test-secret-0123456789abcdef")

import qq_sender


def _mock_response(payload):
    resp = mock.MagicMock()
    resp.__enter__.return_value = resp
    resp.read.return_value = json.dumps(payload).encode()
    return resp


class TestAccessToken(unittest.TestCase):
    def test_fetch_parse_and_cache(self):
        qq_sender._token_cache.update({"token": "", "expire_at": 0.0})
        resp = _mock_response({"access_token": "TOKEN123", "expires_in": 7200})
        with mock.patch("urllib.request.urlopen", return_value=resp) as urlopen:
            first = qq_sender.get_access_token()
            second = qq_sender.get_access_token()
        self.assertEqual(first, "TOKEN123")
        self.assertEqual(second, "TOKEN123")
        self.assertEqual(urlopen.call_count, 1)
        req = urlopen.call_args[0][0]
        self.assertEqual(req.full_url, "https://api.bot.qq.com/app/getAppAccessToken")
        body = json.loads(req.data.decode())
        self.assertEqual(body["appId"], "102000000")
        self.assertIn("clientSecret", body)
        qq_sender._token_cache.update({"token": "", "expire_at": 0.0})


class TestSendGroupReply(unittest.TestCase):
    def test_request_format(self):
        resp = _mock_response({"id": "RET1", "timestamp": "2026-09-19T22:00:00+08:00"})
        with mock.patch("qq_sender.get_access_token", return_value="TOKEN123"), \
             mock.patch("urllib.request.urlopen", return_value=resp) as urlopen:
            data = qq_sender.send_group_reply("GROUP1", "MSG123", "你好")
        self.assertEqual(data["id"], "RET1")
        req = urlopen.call_args[0][0]
        self.assertEqual(req.full_url, "https://api.bot.qq.com/v2/groups/GROUP1/messages")
        headers = {k.lower(): v for k, v in req.headers.items()}
        self.assertEqual(headers.get("authorization"), "QQBot TOKEN123")
        body = json.loads(req.data.decode())
        self.assertEqual(body["msg_type"], 0)
        self.assertEqual(body["msg_id"], "MSG123")
        self.assertEqual(body["msg_seq"], 1)
        self.assertEqual(body["content"], "你好")


if __name__ == "__main__":
    unittest.main()
