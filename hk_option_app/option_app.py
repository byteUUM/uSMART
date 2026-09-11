"""
HK 期权 APP 端接口封装 (UAT)
=============================
对应需求 ZTHK-17628。封装 app 端下单 / 改单 / 撤单 / 最大可买可卖 / 订单查询，
供各测试用例调用。

APP 端接口(网关 jy-uat.yxzq.com, X-Channel=2)：
  下单   POST /option-order-server/api/option-trade/v1
  改单   POST /option-order-server/api/option-replace-order/v1   (body 用 orderNo!)
  撤单   POST /option-order-server/api/option-cancel-order/v1
  下单页最大可买可卖  /api/option-customer-range/v1
  改单页最大可买可卖  /api/option-customer-replace-range/v1
  订单列表 /api/user-all-option-order-list/v1
  订单详情 /api/user-option-order-detail/v1

要点(SIT/UAT 日志实测)：
  - app 下单 body 不带 capitalAccount，服务端按 token 用户 + businessType 定账户；
    沽空(OS)自动落到该用户沽空子账户。
  - 限价单(orderType=2)必须带 price；盘前(sessionType=1/10)只支持限价。
  - 改单 body 用 orderNo(委托编号)，不是 orderId。
  - side=2 普通卖出需有持仓，否则提示走沽空；OS 需该用户有沽空权限。
"""
import os
import sys
import uuid

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from common.client import send, resp_json, is_ok, data_of
from common.config import (
    url_for,
    APP_USER_UUID,
    BUSINESS_TYPE_OPTION, BUSINESS_TYPE_OPTION_SHORT,
    ORDER_TYPE_LIMIT,
    ENTRUST_TYPE_INTERNET,
    SIDE_BUY, SIDE_SELL,
    SESSION_TYPE_REGULAR, SESSION_TYPE_PRE_MARKET, SESSION_TYPE_PRE_AND_REGULAR,
)

# 默认测试标的(UAT redis 中有 info 缓存的活跃期权代码, 可按当日实际调整)
DEFAULT_SYMBOL = "AAPL260911C315000"
DEFAULT_PRICE = 1.0
DEFAULT_QTY = 1


# ============================ 请求体构造 ============================

def build_trade_body(side=SIDE_BUY, business_type=BUSINESS_TYPE_OPTION,
                     symbol=DEFAULT_SYMBOL, price=DEFAULT_PRICE, qty=DEFAULT_QTY,
                     order_type=ORDER_TYPE_LIMIT, session_type=SESSION_TYPE_REGULAR,
                     hold_id=None, force_entrust=False, maturity_verify=True,
                     app_is_popup=False, **override):
    """按 app 端 OptionTradeRequest 拼下单请求体。"""
    body = {
        "requestId": str(uuid.uuid4()),
        "side": side,
        "qty": qty,
        "symbol": symbol,
        "orderType": order_type,
        "businessType": business_type,
        "sessionType": session_type,
        "forceEntrustFlag": force_entrust,
        "maturityDayVerify": maturity_verify,
        "appIsPopup": app_is_popup,
    }
    if order_type == ORDER_TYPE_LIMIT:
        body["price"] = price
    if hold_id is not None:
        body["holdId"] = hold_id
    body.update(override)
    return body


# ============================ 下单 ============================

def trade_buy(**kw):
    """APP 期权买入 (O, side=1)"""
    return send("APP期权下单-买入(O)", url_for("option_trade"),
                build_trade_body(side=SIDE_BUY, **kw))


def trade_sell(hold_id=None, **kw):
    """APP 期权卖出/平仓 (O, side=2)，需该标的有持仓"""
    return send("APP期权下单-卖出(O)", url_for("option_trade"),
                build_trade_body(side=SIDE_SELL, hold_id=hold_id, **kw))


def trade_short(**kw):
    """APP 期权沽空开仓 (OS, side=2)，需该用户有沽空权限"""
    return send("APP期权沽空下单(OS)", url_for("option_trade"),
                build_trade_body(side=SIDE_SELL,
                                 business_type=BUSINESS_TYPE_OPTION_SHORT, **kw))


def trade_close_short(hold_id=None, **kw):
    """APP 买入平仓 (OS, side=1)，平掉沽空空头持仓"""
    return send("APP期权买入平仓(OS)", url_for("option_trade"),
                build_trade_body(side=SIDE_BUY, hold_id=hold_id,
                                 business_type=BUSINESS_TYPE_OPTION_SHORT, **kw))


# ---- AVS 盘前场景 ----
def trade_buy_pre_market(**kw):
    """仅盘前买入 (sessionType=1)，只能盘前时段、只支持限价"""
    return send("APP期权下单-仅盘前买入", url_for("option_trade"),
                build_trade_body(side=SIDE_BUY, session_type=SESSION_TYPE_PRE_MARKET,
                                 order_type=ORDER_TYPE_LIMIT, **kw))


def trade_buy_pre_and_regular(**kw):
    """盘前+盘中买入 (sessionType=10)，只支持限价"""
    return send("APP期权下单-盘前+盘中买入", url_for("option_trade"),
                build_trade_body(side=SIDE_BUY,
                                 session_type=SESSION_TYPE_PRE_AND_REGULAR,
                                 order_type=ORDER_TYPE_LIMIT, **kw))


# ============================ 改单 ============================

def replace(order_no, price=DEFAULT_PRICE, qty=DEFAULT_QTY):
    """
    APP 期权改单。body 用 orderNo(委托编号, int64)；price、qty 都要传。
    """
    body = {
        "requestId": str(uuid.uuid4()),
        "orderNo": int(order_no),
        "qty": qty,
        "price": price,
    }
    return send("APP期权改单", url_for("option_replace"), body)


# ============================ 撤单 ============================

def cancel(order_no, is_force_cancel=True):
    """APP 期权撤单(按 orderNo)。"""
    body = {
        "requestId": str(uuid.uuid4()),
        "orderNo": int(order_no),
        "isForceCancel": is_force_cancel,
    }
    return send("APP期权撤单", url_for("option_cancel"), body)


# ============================ 最大可买可卖 ============================

def customer_range(symbol=DEFAULT_SYMBOL, price=DEFAULT_PRICE, qty=1,
                   side=SIDE_BUY, business_type=BUSINESS_TYPE_OPTION,
                   add_cover_call=True):
    """下单页最大可买可卖。"""
    body = {
        "price": price, "symbol": symbol, "businessType": business_type,
        "entrustQty": qty, "side": side,
        "optionCustomerRangeDO": {
            "price": price, "symbol": symbol, "businessType": business_type,
            "side": side, "entrustType": ENTRUST_TYPE_INTERNET, "entrustQty": qty,
            "amount": 0, "businessQty": 0, "businessAmount": 0,
            "addCoverCall": add_cover_call,
        },
    }
    return send("APP最大可买可卖(下单页)", url_for("option_customer_range"), body)


def replace_range(order_no, price=DEFAULT_PRICE):
    """改单页最大可买可卖(按 orderNo)。字段以实测为准，先按下单页结构 + orderNo。"""
    body = {"orderNo": int(order_no), "price": price}
    return send("APP改单最大可买可卖", url_for("option_replace_range"), body)


# ============================ 订单查询 ============================

def order_list():
    """当日全部期权委托列表。"""
    return send("APP期权订单列表", url_for("user_order_list"), {})


def order_detail(order_no):
    """订单详情。"""
    return send("APP期权订单详情", url_for("user_order_detail"),
                {"orderNo": int(order_no)})


# ============================ 辅助 ============================

def order_no_of(resp):
    """从下单响应取 orderNo/orderId(在 data 字段)。"""
    d = data_of(resp)
    if d is None:
        return None
    if isinstance(d, dict):
        return d.get("orderNo") or d.get("orderId") or d.get("id")
    try:
        return int(d)
    except (ValueError, TypeError):
        return None


if __name__ == "__main__":
    # 手动冒烟：下单页最大可买可卖
    customer_range()
