"""
Mock 成交工具 (改订单状态)
============================
调用 mock 平台把订单改成指定状态(报单中/待成交/部成/全成/废单/撤单成功)。

接口(抓包得到):
  POST http://10.60.6.93:8020/deal_mock/
  Content-Type: application/x-www-form-urlencoded (表单)
  站点是 Django, 需要 csrfmiddlewaretoken + csrftoken cookie 配对。

表单参数:
  orderId          订单号
  accountType      option (期权)
  environment      UAT
  market           HK
  orderType        com
  position         long / short
  operationType    queryMockTypes(查可用类型) / 执行mock的动作
  mockType         0报单中 1待成交 2部成 3全成 8废单 4撤单成功
  csrfmiddlewaretoken  Django CSRF token

用法:
  python mock_deal.py              # 先查该订单可用的 mock 类型
  python mock_deal.py fill         # 把订单改成全部成交(mockType=3)
"""
import os
import sys
import re

import requests

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# ============================ 配置 ============================
MOCK_BASE = "http://10.60.6.93:8020"
MOCK_URL = MOCK_BASE + "/deal_mock/"

ORDER_ID = "1147184413096816640"   # 要操作的订单号

# 该订单固定的业务参数(来自抓包)
BASE_FORM = {
    "orderId": ORDER_ID,
    "accountType": "option",
    "environment": "UAT",
    "market": "HK",
    "orderType": "com",
    "position": "long",
}

# mockType 枚举(来自 queryMockTypes 返回)
MOCK_TYPES = {
    "0": "报单中", "1": "待成交", "2": "部分成交",
    "3": "全部成交", "8": "废单", "4": "撤单成功",
}

# 执行 mock(触发成交)的 operationType 值(抓包确认)
EXEC_OPERATION_TYPE = "triggerMock"

# 执行时额外需要的表单字段(抓包确认): mockPrice 成交价 / dealAmount 成交数量 / phone
# 这些值默认从 queryMockTypes 返回的对应 mockType 里自动取(price/qty), 无需手填。

# 服务端返回里代表失败的关键词(含中文)
FAIL_KEYWORDS = ["error", "invalid", "fail", "not found", "unknown",
                 "未知", "不支持", "失败", "错误", "无效"]


def new_session():
    """建立会话并访问 mock 页面, 拿到 csrftoken cookie 和页面里的 token。"""
    s = requests.Session()
    s.headers.update({
        "User-Agent": "Mozilla/5.0",
        "Referer": MOCK_URL,
        "Origin": MOCK_BASE,
    })
    token = ""
    try:
        r = s.get(MOCK_URL, timeout=15)
        # Django 页面通常有 <input name="csrfmiddlewaretoken" value="...">
        m = re.search(r'name="csrfmiddlewaretoken"\s+value="([^"]+)"', r.text)
        if m:
            token = m.group(1)
        # 兜底: 从 cookie 取
        if not token:
            token = s.cookies.get("csrftoken", "")
    except requests.RequestException as e:
        print("访问 mock 页面失败:", e)
    return s, token


def post_mock(session, token, operation_type, mock_type=None, extra=None):
    form = dict(BASE_FORM)
    form["operationType"] = operation_type
    form["csrfmiddlewaretoken"] = token
    if mock_type is not None:
        form["mockType"] = mock_type
    if extra:
        form.update(extra)
    resp = session.post(MOCK_URL, data=form, timeout=20,
                        headers={"X-CSRFToken": token,
                                 "Content-Type": "application/x-www-form-urlencoded"})
    return resp


def _find_type_info(query_resp_text, mock_type):
    """从 queryMockTypes 的响应里取出指定 mockType 的 price/qty。"""
    import json
    try:
        arr = json.loads(query_resp_text)
    except ValueError:
        return None
    for item in arr:
        if str(item.get("mockType")) == str(mock_type):
            return item
    return None


def query_types():
    """查询该订单当前可用的 mock 类型。"""
    s, token = new_session()
    print("csrf token:", token[:20] + "..." if token else "(空)")
    resp = post_mock(s, token, "queryMockTypes")
    print("\n===== queryMockTypes =====")
    print("状态码:", resp.status_code)
    print("响应  :", resp.text)
    return resp


def mock_to(mock_type="3"):
    """把订单 mock 成指定状态, 默认 3=全部成交。逐个尝试执行动作值。"""
    s, token = new_session()
    print("目标状态: mockType=%s (%s)" % (mock_type, MOCK_TYPES.get(mock_type, "?")))
    print("csrf token:", (token[:20] + "...") if token else "(空)")

    # 先查一次, 拿目标 mockType 的成交价(price)和数量(qty)作为 mockPrice/dealAmount
    q = post_mock(s, token, "queryMockTypes")
    print("\n----- 先查可用类型 -----")
    print("状态码:", q.status_code, " 响应:", q.text[:500])

    info = _find_type_info(q.text, mock_type)
    if not info:
        print("\n>>> queryMockTypes 未返回 mockType=%s, 该订单当前可能不支持此操作" % mock_type)
        return None

    extra = {
        "mockPrice": info.get("price", ""),   # 成交价
        "dealAmount": info.get("qty", ""),    # 成交数量(全成时=委托数量)
        "phone": "",
    }
    print("执行参数: mockPrice=%s dealAmount=%s" % (extra["mockPrice"], extra["dealAmount"]))

    # 执行 mock
    resp = post_mock(s, token, EXEC_OPERATION_TYPE, mock_type=mock_type, extra=extra)
    print("\n----- 执行 operationType=%s mockType=%s -----" % (EXEC_OPERATION_TYPE, mock_type))
    print("状态码:", resp.status_code)
    print("响应  :", resp.text[:500])
    if resp.status_code == 200 and not any(k in resp.text.lower() for k in FAIL_KEYWORDS):
        print("\n>>> 执行请求已接受, 用 query_data.py 复查订单状态是否变为全成(internal_status=810)")
        return resp
    print("\n>>> 服务端返回疑似失败, 见上方响应")
    return None


if __name__ == "__main__":
    arg = sys.argv[1] if len(sys.argv) > 1 else "query"
    if arg == "query":
        query_types()
    elif arg == "fill":
        mock_to("3")   # 3 = 全部成交
    else:
        # 允许直接传 mockType 数字
        mock_to(arg)
