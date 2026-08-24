"""
碎股 —— 下单 / 改单 / 撤单
==========================
接口:
  下单: /order-center-sg/admin-api/odd-order-create/v1
  改单: /order-center-sg/admin-api/odd-order-modify/v1
  撤单: /order-center-sg/admin-api/odd-order-cancel/v1

说明:
  - 该 fundAccount 在 SIT 环境是美股账户，market 传 HK 会报"市场不合法"。
  - seatNo / tradeChannel 需与账号对应的真实席位/通道一致。
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from common.client import send_order
from common.config import DEFAULT_FUND_ACCOUNT, url_for

# ============================ 碎股业务字段(可单独修改) ============================
FUND_ACCOUNT = DEFAULT_FUND_ACCOUNT
MARKET = "US"                         # HK-香港, US-美股, HGT-沪港通, SGT-深港通
SYMBOL = "AAPL"                       # 符号代码(与 MARKET 保持一致)
ENTRUST_WAY = "NET"                   # TEL-电话委托, NET-internet委托
ENTRUST_PROP = "LMT"                  # LMT/ELMT/MKT/AM/AL
ENTRUST_PRICE = 300                   # 委托价格(市价单/竞价单传 0)
ENTRUST_QTY = 0.3                     # 委托数量(碎股可为小数)
ENTRUST_AMOUNT = 0                    # 委托金额(按金额下单时使用)
ENTRUST_TAB = 1                       # 1-按股数, 2-按金额, 默认 1
DISPOSAL_SALE = False                 # 是否为强平订单
FORCE_ENTRUST_FLAG = True
NOTICE = True
SEAT_NO = "U9342387"                  # 席位号
TRADE_CHANNEL = "IB-30%-U9342387"     # 美股交易通道
TRADE_PERIOD = "N"                    # N-正常, G-暗盘, AB-盘前盘后


# ============================ 下单 ============================

def create_odd_buy():
    """碎股 - 买入"""
    body = {
        "disposalSale": DISPOSAL_SALE,          # 是否为强平订单
        "entrustAmount": ENTRUST_AMOUNT,        # 委托金额
        "entrustPrice": ENTRUST_PRICE,          # 委托价格
        "entrustProp": ENTRUST_PROP,            # 委托属性
        "entrustQty": ENTRUST_QTY,              # 委托数量
        "entrustSide": "B",                     # 委托方向: B-买入, S-卖出
        "entrustTab": ENTRUST_TAB,              # 1-按股数, 2-按金额
        "entrustWay": ENTRUST_WAY,              # 委托方式
        "forceEntrustFlag": FORCE_ENTRUST_FLAG,
        "fundAccount": FUND_ACCOUNT,            # 资金账号(必填)
        "market": MARKET,                       # 市场(必填)
        "notice": NOTICE,
        "seatNo": SEAT_NO,                      # 席位号
        "symbol": SYMBOL,                       # 符号代码(必填)
        "tradeChannel": TRADE_CHANNEL,          # 交易通道(美股必传)
        "tradePeriod": TRADE_PERIOD,
    }
    return send_order("碎股下单-买入", url_for("odd_create"), body)


def create_odd_sell():
    """碎股 - 卖出"""
    body = {
        "disposalSale": DISPOSAL_SALE,
        "entrustAmount": ENTRUST_AMOUNT,
        "entrustPrice": ENTRUST_PRICE,
        "entrustProp": ENTRUST_PROP,
        "entrustQty": ENTRUST_QTY,
        "entrustSide": "S",
        "entrustTab": ENTRUST_TAB,
        "entrustWay": ENTRUST_WAY,
        "forceEntrustFlag": FORCE_ENTRUST_FLAG,
        "fundAccount": FUND_ACCOUNT,
        "market": MARKET,
        "notice": NOTICE,
        "seatNo": SEAT_NO,
        "symbol": SYMBOL,
        "tradeChannel": TRADE_CHANNEL,
        "tradePeriod": TRADE_PERIOD,
    }
    return send_order("碎股下单-卖出", url_for("odd_create"), body)


# ============================ 改单 ============================

def modify_odd(order_id, entrust_price=ENTRUST_PRICE, entrust_qty=ENTRUST_QTY,
               entrust_amount=None, force_entrust_flag=FORCE_ENTRUST_FLAG):
    """
    碎股改单。
    entrust_amount: 委托金额，当按股数方式时可不传(传 None 则不带该字段)。
    """
    body = {
        "entrustPrice": entrust_price,          # 改单价格(必填)
        "entrustQty": entrust_qty,              # 改单数量(必填)
        "forceEntrustFlag": force_entrust_flag,
        "orderId": order_id,                    # 订单ID(必填, int64)
    }
    if entrust_amount is not None:
        body["entrustAmount"] = entrust_amount  # 委托金额(按金额方式时传)
    return send_order("碎股改单", url_for("odd_modify"), body)


# ============================ 撤单 ============================

def cancel_odd(order_id, is_force_cancel=True):
    """碎股撤单"""
    body = {
        "isForceCancel": is_force_cancel,       # 是否强制撤单
        "orderId": order_id,                    # 订单ID(必填, int64)
    }
    return send_order("碎股撤单", url_for("odd_cancel"), body)


if __name__ == "__main__":
    create_odd_buy()
    # create_odd_sell()
    # modify_odd(1600243028902756352, entrust_price=310, entrust_qty=0.5)
    # cancel_odd(1600243028902756352)
