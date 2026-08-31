"""
HK 期权中台下单 —— 期权 / 期权沽空 (AVS 盘前交易)
==================================================
接口:
  下单: POST /option-order-server/admin-api/option-single-order/v1
  改单: POST /option-order-server/admin-api/option-replace-order/v1
  撤单: POST /option-order-server/admin-api/option-cancel-order/v1

重要: HK(admin-uat.yxzq.com) 与 SG(usmartsg.com) 是两套独立系统。
  HK 期权走独立服务 option-order-server, 请求体是 OptionSingleOrderAdminRequest,
  字段名与 SG 的统一下单(order-center-sg/unified-order-create)完全不同:

    HK                     SG(不要再用在这个接口上)
    capitalAccount    <->  fundAccount
    orderType(int)    <->  entrustProp("LMT")
    price / qty       <->  entrustPrice / entrustQty
    side(int 1/2)     <->  entrustSide("B"/"S")
    sessionType(int)  <->  tradePeriod("N")
    transactionPassage<->  tradeChannel
    requestId(必填)    ->  SG 无此字段
    (HK 无 accountType / entrustWay / forceEntrustFlag / notice / currency / market)

  之前脚本直接把 SG 的 body 发给 HK 接口, 必填字段全部缺失,
  服务端返回 {"code":400,"msg":"must not be null"}。

UAT 实测要点:
  - 限价单(orderType=2)必须传 price; 市价单(orderType=1)不传 price,
    但 US 期权当前会被流动性规则拦: 800040 "不支持市价单，请用限价单下单"。
  - sessionType 只有 0(盘中) / 1(仅盘前) / 10(盘前+盘中) 合法;
    非盘前时段送 1 或 10 会被 801116 "当前时段不支持盘前期权交易" 拦下,
    这是时间窗口限制, 不是参数错误, 要在盘前时段跑。
  - side=2(卖出)需要该标的有持仓, 否则 830015 提示改走沽空。
  - businessType=OS(沽空)当前账号 77001164 报 810006 "请先开户",
    需要换有期权沽空权限的 HK 账号。
  - requestId 每次必须是新的 UUID(脚本自动生成)。
  - 改单/撤单请求体里没有 capitalAccount, 只认 orderId, 且 orderId 是 int64,
    要按数字传(传字符串服务端反序列化会失败)。
"""
import os
import sys
import uuid

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from common.client import send_order
from common.config import (
    BROKER_ACCOUNT,
    BUSINESS_TYPE_OPTION,
    BUSINESS_TYPE_OPTION_SHORT,
    CAPITAL_ACCOUNT,
    ENTRUST_TYPE_NORMAL,
    ORDER_TYPE_LIMIT,
    SESSION_TYPE_PRE_AND_REGULAR,
    SESSION_TYPE_PRE_MARKET,
    SESSION_TYPE_REGULAR,
    SIDE_BUY,
    SIDE_SELL,
    url_for,
)

# ============================ 期权业务字段(可单独修改) ============================
SYMBOL = "UTL260918C50000"       # 期权代码: 标的+到期日(YYMMDD)+C/P+行权价x1000
PRICE = 1.5                      # 价格, 最多两位小数, >0; 市价单不传
QTY = 1                          # 数量, 最多两位小数, >0
ORDER_TYPE = ORDER_TYPE_LIMIT    # 2-限价(盘前只支持限价)
ENTRUST_TYPE = ENTRUST_TYPE_NORMAL
SESSION_TYPE = SESSION_TYPE_REGULAR   # 默认盘中; 盘前测试改成 SESSION_TYPE_PRE_MARKET
TRANSACTION_PASSAGE = None       # 不传由服务端按持仓/在途/全局设置选通道; AVS 场景可传 "AVS"


# ============================ 请求体构造 ============================

def build_option_body(side=SIDE_BUY, business_type=BUSINESS_TYPE_OPTION,
                      symbol=SYMBOL, price=PRICE, qty=QTY,
                      order_type=ORDER_TYPE, session_type=SESSION_TYPE,
                      entrust_type=ENTRUST_TYPE, hold_id=None,
                      transaction_passage=TRANSACTION_PASSAGE,
                      broker_account=BROKER_ACCOUNT, **override):
    """
    按 OptionSingleOrderAdminRequest 拼请求体。
    选填字段为 None 时不放进 body, 避免服务端把 null 当非法值。
    """
    body = {
        "capitalAccount": CAPITAL_ACCOUNT,   # 必填: 资金账号
        "entrustType": entrust_type,         # 必填: 委托类型
        "orderType": order_type,             # 必填: 1-市价 2-限价
        "requestId": str(uuid.uuid4()),      # 必填: 每次新 UUID
        "side": side,                        # 必填: 1-买入 2-卖出
        "symbol": symbol,                    # 必填: 期权代码
        "businessType": business_type,       # 选填: O-期权 OS-期权沽空
        "qty": qty,                          # 选填(下单实际必传)
    }
    # 限价单必须带价格, 市价单不能带价格
    if order_type == ORDER_TYPE_LIMIT:
        body["price"] = price
    if session_type is not None:
        body["sessionType"] = session_type   # 选填: 0-盘中 1-仅盘前 10-盘前+盘中
    if hold_id is not None:
        body["holdId"] = hold_id             # 选填: 卖出/平仓指定持仓
    if transaction_passage:
        body["transactionPassage"] = transaction_passage
    if broker_account:
        body["brokerAccount"] = broker_account
    body.update(override)
    return body


# ============================ 下单 ============================

def create_option_buy(**kw):
    """期权买入 (businessType=O, side=1)"""
    return send_order("HK期权下单(O)-买入", url_for("option_create"),
                      build_option_body(side=SIDE_BUY, **kw))


def create_option_sell(hold_id=None, **kw):
    """期权卖出/平仓 (businessType=O, side=2), 需该标的有持仓"""
    return send_order("HK期权下单(O)-卖出", url_for("option_create"),
                      build_option_body(side=SIDE_SELL, hold_id=hold_id, **kw))


def create_option_short(**kw):
    """期权沽空 (businessType=OS, side=2), 需账号有期权沽空权限"""
    return send_order("HK期权沽空下单(OS)", url_for("option_create"),
                      build_option_body(side=SIDE_SELL,
                                        business_type=BUSINESS_TYPE_OPTION_SHORT, **kw))


# ---- AVS 盘前场景 ----

def create_option_buy_pre_market(**kw):
    """仅盘前买入 (sessionType=1), 只能在盘前时段下单, 只支持限价"""
    return send_order("HK期权下单-仅盘前买入", url_for("option_create"),
                      build_option_body(side=SIDE_BUY,
                                        session_type=SESSION_TYPE_PRE_MARKET,
                                        order_type=ORDER_TYPE_LIMIT,
                                        transaction_passage="AVS", **kw))


def create_option_buy_pre_and_regular(**kw):
    """盘前+盘中买入 (sessionType=10), 只支持限价"""
    return send_order("HK期权下单-盘前+盘中买入", url_for("option_create"),
                      build_option_body(side=SIDE_BUY,
                                        session_type=SESSION_TYPE_PRE_AND_REGULAR,
                                        order_type=ORDER_TYPE_LIMIT,
                                        transaction_passage="AVS", **kw))


# ============================ 改单 ============================
# POST /option-order-server/admin-api/option-replace-order/v1
# OptionReplaceAdminRequest: requestId(必填) / orderId(int64) / price / qty
# 不带 capitalAccount, 只认 orderId; orderId 是 int64, 要按数字传。
#
# UAT 实测: 文档把 price、qty 标成非必填, 实际两个都必须传 ——
#   缺 qty   -> 400 "must not be null"
#   缺 price -> 500 "系统异常，请稍后重试"(服务端空指针)
# 所以"只改价"也要把原数量一起带上, "只改量"也要把原价格带上。

def replace_option(order_id, price=PRICE, qty=QTY):
    """
    期权改单。price、qty 必须同时传(不变的那项传原值)。
    改大数量/价格会走购买力校验, 不足时报 800043 "期权购买力不足"。
    """
    body = {
        "requestId": str(uuid.uuid4()),
        "orderId": int(order_id),
        "price": price,
        "qty": qty,
    }
    return send_order("HK期权改单", url_for("option_replace"), body)


# ============================ 撤单 ============================
# POST /option-order-server/admin-api/option-cancel-order/v1
# OptionOrderCancelAdminRequest: orderId(int64) / isForceCancel / requestId
# AVS 订单允许强制撤单(isForceCancel=True)。

def cancel_option(order_id, is_force_cancel=True):
    """期权撤单"""
    body = {
        "requestId": str(uuid.uuid4()),
        "orderId": int(order_id),
        "isForceCancel": is_force_cancel,
    }
    return send_order("HK期权撤单", url_for("option_cancel"), body)


def cancel_options(order_ids, is_force_cancel=True):
    """批量撤单, 返回 {orderId: 响应体文本}"""
    result = {}
    for oid in order_ids:
        resp = cancel_option(oid, is_force_cancel)
        result[oid] = resp.text if resp is not None else None
    return result


def order_id_of(resp):
    """从下单响应里取 orderId(接口返回在 data 字段, 字符串形式的 int64)。"""
    if resp is None:
        return None
    try:
        data = resp.json()
    except ValueError:
        return None
    if data.get("code") == 0 and data.get("data"):
        return int(data["data"])
    return None


def buy_then_replace_then_cancel(price=PRICE, qty=QTY,
                                 new_price=1.2, new_qty=QTY):
    """下单 -> 改单 -> 撤单 全链路跑一遍, 返回 orderId。"""
    order_id = order_id_of(create_option_buy(price=price, qty=qty))
    if order_id is None:
        print(">>> 下单未成功, 后续改单/撤单跳过")
        return None
    replace_option(order_id, price=new_price, qty=new_qty)
    cancel_option(order_id)
    return order_id


if __name__ == "__main__":
    create_option_buy()
    # create_option_sell()
    # create_option_short()                  # 需沽空权限账号
    # create_option_buy_pre_market()         # 盘前时段跑
    # create_option_buy_pre_and_regular()    # 盘前时段跑
    # replace_option(1146771310882336768, price=1.8, qty=2)
    # cancel_option(1146771310882336768)
    # buy_then_replace_then_cancel(new_price=1.8, new_qty=2)
