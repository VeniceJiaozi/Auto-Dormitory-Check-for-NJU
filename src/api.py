"""点名数据源：调用南大表格（SeaTable）外部应用接口查询晚点名情况。"""

import base64
import json
import os
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone

TZ_SHANGHAI = timezone(timedelta(hours=8))
API_URL = os.environ.get(
    "ROLLCALL_API_URL",
    "https://table.nju.edu.cn/api/v2.1/universal-apps/"
    "1dbf1104-04c6-40ea-8325-efd0db0fc712/rows/",
)
PAGE_ID = os.environ.get("ROLLCALL_PAGE_ID", "XY1Z")
APP_TOKEN = os.environ.get("ROLLCALL_API_TOKEN", "")

OK_STATUS = "全部到位"
# 令牌余量低于此小时数才在群回复里提醒：平时不显示，免得干扰群里同学
TOKEN_WARN_HOURS = 48


class RollcallApiError(Exception):
    pass


def _keymap(metadata):
    """从 metadata 建「列名前缀 → 字段 key」映射，表结构重建后 key 变化也能兼容。"""
    cols = [(f.get("name") or "", f.get("key") or "") for f in metadata or []]

    def find(prefix):
        for name, key in cols:
            if name.startswith(prefix):
                return key
        return ""

    return {
        "dorm": find("宿舍号"),
        "leader": find("宿舍长姓名"),
        "student_id": find("宿舍长学号"),
        "date": find("当日日期"),
        "status": find("当日晚点名情况"),
    }


def fetch_rollcall_rows():
    """拉取晚点名表全部行，返回 [{dorm, leader, student_id, date, status}]；失败抛 RollcallApiError。"""
    if not APP_TOKEN:
        raise RollcallApiError("missing env: ROLLCALL_API_TOKEN")
    url = f"{API_URL}?page_id={PAGE_ID}&start=0&limit=1000"
    req = urllib.request.Request(url, headers={"Authorization": f"Token {APP_TOKEN}"})
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        e.close()
        raise RollcallApiError(f"HTTP {e.code}（403/401 多为令牌过期，需更新 ROLLCALL_API_TOKEN）")
    except (urllib.error.URLError, TimeoutError, OSError, json.JSONDecodeError) as e:
        raise RollcallApiError(f"request failed: {e}")

    if not data.get("success"):
        raise RollcallApiError(f"api error: {data.get('error_message')}")
    keys = _keymap(data.get("metadata"))
    if not keys["dorm"]:
        raise RollcallApiError("metadata 缺少「宿舍号」列，表结构可能已变更")

    rows = []
    for r in data.get("results") or []:
        rows.append({
            "dorm": r.get(keys["dorm"]),
            "leader": r.get(keys["leader"]),
            "student_id": r.get(keys["student_id"]),
            "date": r.get(keys["date"]),
            "status": r.get(keys["status"]),
        })
    return rows


def summarize(rows, now=None):
    """把点名行分成未报 / 异常 / 已报（当日日期为空或非今天即未报）。"""
    today = (now or datetime.now(TZ_SHANGHAI)).strftime("%Y-%m-%d")
    pending, abnormal, ok_count = [], [], 0
    for r in rows:
        date = str(r.get("date") or "")[:10]
        status = str(r.get("status") or "").strip()
        if date != today:
            pending.append(r)
        elif status == OK_STATUS:
            ok_count += 1
        else:
            abnormal.append(r)
    return {"today": today, "pending": pending, "abnormal": abnormal, "ok_count": ok_count}


def find_leader(rows, student_id):
    """按宿舍长学号在点名行中定位其宿舍，用于「绑定」时核对身份；查不到返回 None。"""
    sid = str(student_id or "").strip()
    if not sid:
        return None
    for r in rows:
        if str(r.get("student_id") or "").strip() == sid:
            return r
    return None


def token_hours_left(now=None):
    """从令牌 JWT 的 exp 离线算出剩余小时数；不是 JWT / 解不出则返回 None（不影响查询）。"""
    try:
        payload = APP_TOKEN.split(".")[1]
        payload += "=" * (-len(payload) % 4)
        exp = json.loads(base64.urlsafe_b64decode(payload).decode())["exp"]
        return (datetime.fromtimestamp(exp, TZ_SHANGHAI) - (now or datetime.now(TZ_SHANGHAI))).total_seconds() / 3600
    except (IndexError, KeyError, TypeError, ValueError):
        return None


def token_expiry_notice(now=None):
    """令牌临期提醒；余量充足或无法判断时返回空串（不给群里加噪音）。"""
    left = token_hours_left(now)
    if left is None or left > TOKEN_WARN_HOURS:
        return ""
    when = "已过期" if left <= 0 else f"将在约 {int(left)} 小时后到期"
    return f"【提醒】点名数据凭证{when}，请班长更新一次，否则查询会失败。"


def build_rollcall_reply(rows=None, now=None):
    """汇总点名数据生成群回复：未报宿舍、异常宿舍、已报统计。"""
    if rows is None:
        rows = fetch_rollcall_rows()
    s = summarize(rows, now)
    pending, abnormal, ok_count, today = s["pending"], s["abnormal"], s["ok_count"], s["today"]
    notice = token_expiry_notice(now)

    if not rows:
        base = f"【晚点名情况 {today}】点名表暂无数据。"
        return f"{base}\n{notice}" if notice else base
    lines = [f"【晚点名情况 {today}】"]
    if pending:
        lines.append(f"未报宿舍 {len(pending)} 个：")
        lines.extend(f"- {r['dorm']}（{r['leader']}）" for r in pending)
    if abnormal:
        lines.append(f"异常情况 {len(abnormal)} 个：")
        lines.extend(f"- {r['dorm']}（{r['leader']}）：{r['status']}" for r in abnormal)
    if not pending and not abnormal:
        lines.append(f"全部 {len(rows)} 个宿舍已报且全部到位。")
    else:
        lines.append(f"其余 {ok_count} 个宿舍已报且全部到位。")
    if notice:
        lines.append(notice)
    return "\n".join(lines)
