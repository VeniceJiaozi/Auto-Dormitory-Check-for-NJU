# 南大表格点名系统接口文档（实测 2026-09-19）

数据源是南大表格（SeaTable，`table.nju.edu.cn`）上的外部应用
「【班长】宿舍晚点名情况查看」，页面地址：
`https://table.nju.edu.cn/apps/custom/2026jxnightcheckview/?page_id=XY1Z`

## 数据接口

```
GET https://table.nju.edu.cn/api/v2.1/universal-apps/1dbf1104-04c6-40ea-8325-efd0db0fc712/rows/?page_id=XY1Z&start=0&limit=100
Authorization: Token <JWT访问令牌>
```

- 仅需上述请求头，**无需 Cookie**；已验证可从非浏览器环境（本机 curl / Python）直连成功。
- 返回结构：

```json
{
  "success": true,
  "error_message": "",
  "metadata": [{"name": "宿舍号", "key": "0000", "type": "text"}, ...],
  "results": [ { "<列key>": "<值>", ... }, ... ]
}
```

- 行数据按 `metadata` 里的 key（而非列名）存放，当前关键列：

| 列名 | key | 说明 |
|---|---|---|
| 宿舍号 | `0000` | 如 `南二-425` |
| 宿舍长姓名 | `gZPq` | |
| 宿舍长学号 | `FTLe` | |
| 当日日期 | `230A` | `2026-09-19T00:00:00+08:00`，未报为 `null` |
| 当日晚点名情况 | `ClfB` | `全部到位` / 其他说明文字，未报为 `null` |

- 注意：key 会随表结构重建而变化，`src/api.py` 通过 metadata 按**列名前缀**动态解析，不硬编码 key。

## 业务规则（已实测确认）

- 每天 19:00 表内自动化规则（Automation Rule）清空「当日日期」「晚点名情况」两列。
- **已报** = 当日日期为今天；**未报** = 当日日期为空或不是今天。
- **异常** = 已报但情况不等于「全部到位」（如「未全部到位」或请假说明），需在回复中展示原文。

## 访问令牌（JWT）生命周期

- 令牌嵌在应用页面 HTML 中（`accessToken: '...'`），**有效期约 3 天**（约 259200 秒）。
- 每次用浏览器登录态打开页面都会签发新令牌（页面 URL 见文首）。
- 获取方法：浏览器打开页面 → F12 控制台执行
  `copy(document.documentElement.outerHTML.match(/accessToken:\s*'([^']+)'/)[1])`
  → 令牌已复制到剪贴板 → 更新 `config/.env` 或 SCF 环境变量 `ROLLCALL_API_TOKEN`。
- 令牌过期后接口返回 403，机器人回复「点名数据查询失败」并在日志中提示令牌过期。
- 签发页面需要南大统一身份认证（CAS）登录态；令牌本身与登录 Cookie 无关，可离线使用。
- **自动临期提醒（2026-09-20 上线）**：这串令牌本身就是 JWT，`exp` 字段即到期时间，**不用发请求就能离线解出余量**。机器人现在在余量 **≤ 48 小时**时，于「查未点名」回复末尾自动追加一行「【提醒】点名数据凭证将在约 N 小时后到期，请班长更新一次，否则查询会失败。」；余量充足时不显示，不打扰群里同学。实现见 `src/api.py::token_hours_left` / `token_expiry_notice`，阈值常量 `TOKEN_WARN_HOURS`。

## 长期鉴权方案（阶段 5 运维决策）

当前账号对该表格只有外部应用权限（无工作区权限），无法生成永久 API Token。可选方案：

1. **定期手动换令牌**（现状）：约每 3 天一次，成本最低。
2. 请表格所有者（学院管理员）为该 base 生成 API Token 提供给机器人 → 永久有效，最佳。
3. 存储 SeaTable 会话 Cookie 由机器人自动刷新令牌 → Cookie 有效期未知，需实测，且保存 Cookie 敏感性更高。
4. 自动化 CAS 登录 → 涉及校园账号密码，风险高，不建议。
