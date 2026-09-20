"""qq_sender.py 测试：token 获取/缓存与群回复请求格式（HTTP 层 mock）。"""

import io
import json
import os
import sys
import unittest
import urllib.error
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

    def test_markdown_payload_shape(self):
        resp = _mock_response({"id": "RET2"})
        with mock.patch("qq_sender.get_access_token", return_value="TOKEN123"), \
             mock.patch("urllib.request.urlopen", return_value=resp) as urlopen:
            qq_sender.send_group_reply("GROUP1", "MSG123", "@ 测试", msg_seq=3, msg_type=2)
        body = json.loads(urlopen.call_args[0][0].data.decode())
        self.assertEqual(body["msg_type"], 2)
        self.assertEqual(body["markdown"], {"content": "@ 测试"})
        self.assertNotIn("content", body)
        self.assertEqual(body["msg_seq"], 3)

    def test_http_error_detail_is_preserved(self):
        err = urllib.error.HTTPError(
            "https://api.bot.qq.com/v2/groups/GROUP1/messages",
            400, "Bad Request", {}, io.BytesIO(b'{"code":11293,"err_code":40011026,"message":"msg_id is invalid"}'),
        )
        with mock.patch("qq_sender.get_access_token", return_value="TOKEN123"), \
             mock.patch("urllib.request.urlopen", side_effect=err):
            with self.assertRaises(RuntimeError) as ctx:
                qq_sender.send_group_reply("GROUP1", "MSG123", "你好")
        text = str(ctx.exception)
        self.assertIn("HTTP 400", text)
        self.assertIn("msg_id is invalid", text)


if __name__ == "__main__":
    unittest.main()
