"""
Mock 成交工具 (改订单状态) —— HK_SIT
=====================================
调用 mock 平台把订单改成指定状态(报单中/待成交/部成/全成/废单/撤单成功)。

接口(抓包得到):
  POST http://10.60.6.93:8020/deal_mock/
  Content-Type: application/x-www-form-urlencoded (表单)
  站点是 Django, 需要 csrfmiddlewaretoken + csrftoken cookie 配对。

表单参数:
  orderId          订单号
  accountType      option (期权)
  environment      SIT / UAT   <-- 本目录是 SIT, 默认 SIT
  market           HK
  orderType        com
  position         long / short
  operationType    queryMockTypes(查可用类型) / triggerMock(执行)
  mockType         0报单中 1待成交 2部成 3全成 8废单 4撤单成功
  mockPrice        成交价(执行时必带)
  dealAmount       成交数量(执行时必带; = 委托量则全成, 小于则部成)
  csrfmiddlewaretoken  Django CSRF token

已实测的行为坑(重要):
  1. environment 必须大写 "SIT"。传小写 "sit" 返回 {"code":0,"msg":"list index out of range"}；
     SIT 的单传 "UAT" 返回"查找不到订单号，或者该订单已终态"。
  2. **orderId 参数会被服务端忽略**。queryMockTypes 返回体里的 orderId 是平台自己
     挑的那一笔(当前 environment+market+accountType+position 下最新一笔可 mock 的单),
     不一定是你传进去的。所以要 mock 某一笔单, 必须在下单后立刻调用,
     且中间不能有别人下新单。调用前请核对返回体里的 orderId 是不是你要的那笔。
  3. mockType 参数在"全成/部成"上生效靠的是 dealAmount:
     dealAmount == 委托量 -> 全成；小于 -> 部成。
     废单(8)/待成交(1) 动作返回成功但实际不生效。

用法:
  python mock_deal.py                    # 查平台当前挑中的订单及可用 mock 类型
  python mock_deal.py fill               # 全部成交
  python mock_deal.py fill 1148534857241886720   # 指定单号(仅用于核对, 见坑 2)
  python mock_deal.py part               # 部分成交(成交一半)

作为模块引用:
  from mock_deal import query_types, mock_fill, mock_partial
"""
import os
import re
import sys

import requests

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# ============================ 配置 ============================
MOCK_BASE = "http://10.60.6.93:8020"
MOCK_URL = MOCK_BASE + "/deal_mock/"

# 本目录是 HK_SIT
ENVIRONMENT = "SIT"
MARKET = "HK"
ACCOUNT_TYPE = "option"
ORDER_TYPE = "com"

# 默认订单号(仅作占位, 见文件头"坑 2": 服务端实际会忽略它)
ORDER_ID = ""

# mockType 枚举(来自 queryMockTypes 返回)
MOCK_TYPES = {
    "0": "报单中", "1": "待成交", "2": "部分成交",
    "3": "全部成交", "8": "废单", "4": "撤单成功",
}

# 执行 mock 的 operationType 值(抓包确认)
EXEC_OPERATION_TYPE = "triggerMock"

# 服务端返回里代表失败的关键词(含中文)
FAIL_KEYWORDS = ["error", "invalid", "fail", "not found", "unknown",
                 "未知", "不支持", "失败", "错误", "无效", "异常",
                 "查找不到", "index out of range"]


def _base_form(order_id=None, position="long"):
    return {
        "orderId": order_id or ORDER_ID,
        "accountType": ACCOUNT_TYPE,
        "environment": ENVIRONMENT,
        "market": MARKET,
        "orderType": ORDER_TYPE,
        "position": position,
    }


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
        m = re.search(r'name="csrfmiddlewaretoken"\s+value="([^"]+)"', r.text)
        if m:
            token = m.group(1)
        if not token:
            token = s.cookies.get("csrftoken", "")
    except requests.RequestException as e:
        print("访问 mock 页面失败:", e)
    return s, token


def post_mock(session, token, operation_type, order_id=None, position="long",
              mock_type=None, extra=None):
    form = _base_form(order_id, position)
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


def _parse_types(text):
    """解析 queryMockTypes 响应 -> (list[dict], 平台实际挑中的 orderId)"""
    import json
    try:
        arr = json.loads(text)
    except ValueError:
        return [], None
    if isinstance(arr, dict):      # 报错时返回的是 {"msg": ...}
        return [], None
    picked = arr[0].get("orderId") if arr else None
    return arr, picked


def _find_type_info(types, mock_type):
    for item in types:
        if str(item.get("mockType")) == str(mock_type):
            return item
    return None


def query_types(order_id=None, position="long", verbose=True):
    """
    查询平台当前可 mock 的订单及类型。
    返回 (types, picked_order_id)。注意 picked_order_id 是平台自己挑的那一笔。
    """
    s, token = new_session()
    resp = post_mock(s, token, "queryMockTypes", order_id=order_id, position=position)
    types, picked = _parse_types(resp.text)
    if verbose:
        print("===== queryMockTypes (env=%s market=%s position=%s) =====" % (
            ENVIRONMENT, MARKET, position))
        print("状态码:", resp.status_code)
        print("响应  :", resp.text[:600])
        print("平台挑中的订单号:", picked)
        if order_id and picked and str(order_id) != str(picked):
            print(">>> 注意: 你传的是 %s, 平台挑中的却是 %s, mock 会作用在后者上"
                  % (order_id, picked))
    return types, picked


def mock_to(mock_type="3", order_id=None, position="long", deal_qty=None,
            deal_price=None, expect_order_id=None):
    """
    把平台当前挑中的订单 mock 成指定状态。
    mock_type       : 3 全成 / 2 部成 / 0 报单中 ...
    deal_qty        : 成交数量; 不传则用平台返回的 qty(= 全成)
    deal_price      : 成交价; 不传则用平台返回的 price(= 委托价)。
                      传了可以造出"成交价 != 委托价"的场景。
    expect_order_id : 期望被操作的订单号; 与平台挑中的不一致时直接放弃, 避免误操作别人的单
    """
    s, token = new_session()
    print("目标状态: mockType=%s (%s)" % (mock_type, MOCK_TYPES.get(str(mock_type), "?")))

    q = post_mock(s, token, "queryMockTypes", order_id=order_id, position=position)
    types, picked = _parse_types(q.text)
    print("平台挑中的订单号:", picked, " 可用类型:",
          [(t.get("mockType"), t.get("label")) for t in types])

    if not types:
        print(">>> queryMockTypes 没返回可用类型, 原始响应:", q.text[:400])
        return None

    if expect_order_id and str(picked) != str(expect_order_id):
        print(">>> 放弃执行: 期望操作 %s, 但平台挑中的是 %s(不是同一笔, 不动它)"
              % (expect_order_id, picked))
        return None

    info = _find_type_info(types, mock_type)
    if not info:
        print(">>> 该订单当前不支持 mockType=%s, 可用的是 %s"
              % (mock_type, [t.get("mockType") for t in types]))
        return None

    qty = info.get("qty", "")
    extra = {
        "mockPrice": deal_price if deal_price is not None else info.get("price", ""),
        "dealAmount": deal_qty if deal_qty is not None else qty,
        "phone": "",
    }
    print("执行参数: mockPrice=%s dealAmount=%s (委托价=%s 委托量=%s)"
          % (extra["mockPrice"], extra["dealAmount"], info.get("price"), qty))

    resp = post_mock(s, token, EXEC_OPERATION_TYPE, order_id=picked,
                     position=position, mock_type=mock_type, extra=extra)
    print("响应: %s | %s" % (resp.status_code, resp.text[:400]))
    if resp.status_code == 200 and not any(k in resp.text.lower() for k in FAIL_KEYWORDS):
        print(">>> 已接受, 用 query_data.py 复查 internal_status(810 全成 / 350 部成)")
        return picked
    print(">>> 服务端返回疑似失败")
    return None


def mock_fill(order_id=None, position="long", deal_price=None,
              expect_order_id=None):
    """全部成交。deal_price 可指定成交价, 不传则按委托价成交。"""
    return mock_to("3", order_id=order_id, position=position,
                   deal_price=deal_price, expect_order_id=expect_order_id)


def mock_partial(order_id=None, position="long", deal_qty=None, deal_price=None,
                 expect_order_id=None):
    """部分成交: deal_qty 传小于委托量的数量"""
    return mock_to("3", order_id=order_id, position=position, deal_qty=deal_qty,
                   deal_price=deal_price, expect_order_id=expect_order_id)


if __name__ == "__main__":
    arg = sys.argv[1] if len(sys.argv) > 1 else "query"
    oid = sys.argv[2] if len(sys.argv) > 2 else None
    pos = sys.argv[3] if len(sys.argv) > 3 else "long"
    if arg == "query":
        query_types(order_id=oid, position=pos)
    elif arg == "fill":
        mock_fill(order_id=oid, position=pos)
    elif arg == "part":
        mock_partial(order_id=oid, position=pos, deal_qty=1)
    else:
        mock_to(arg, order_id=oid, position=pos)
