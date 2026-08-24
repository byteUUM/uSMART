"""
统一下单 —— 期权 / 期权沽空
============================
接口:
  下单: /order-center-sg/admin-api/unified-order-create/v1  (businessType = O / OS)
  改单: /order-center-sg/admin-api/unified-order-replace/v1
  撤单: /order-center-sg/admin-api/unified-order-cancel/v1

说明:
  - 期权沽空(OS)必须使用期权代码，不能用股票代码，否则报"期权代码不存在"。
  - 期权交易通道与股票不同，这里单独配置。
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from common.client import send_order
from common.config import ACCOUNT_TYPE, DEFAULT_FUND_ACCOUNT, url_for

# ============================ 期权业务字段(可单独修改) ============================
FUND_ACCOUNT = DEFAULT_FUND_ACCOUNT
CURRENCY = "USA"
MARKET = "US"
SYMBOL = "UTL260918C50000"            # 期权代码(单腿)
ENTRUST_WAY = "NET"
ENTRUST_PROP = "LMT"                  # 期权一般用限价单
ENTRUST_PRICE = 1.5
ENTRUST_QTY = 1
FORCE_ENTRUST_FLAG = True
NOTICE = True
TRADE_CHANNEL = "VELOX-30%-2UT00110"  # 期权专用交易通道
TRADE_PERIOD = "N"


# ============================ 下单 ============================

def create_option_buy():
    """期权 - 买入 (businessType=O)"""
    body = {
        "accountType": ACCOUNT_TYPE,
        "businessType": "O",                    # 订单类型: O-期权
        "entrustProp": ENTRUST_PROP,
        "entrustPrice": ENTRUST_PRICE,
        "entrustQty": ENTRUST_QTY,
        "entrustSide": "B",
        "entrustWay": ENTRUST_WAY,
        "forceEntrustFlag": FORCE_ENTRUST_FLAG,
        "fundAccount": FUND_ACCOUNT,
        "currency": CURRENCY,
        "market": MARKET,
        "notice": NOTICE,
        "symbol": SYMBOL,                       # 单腿期权代码
        "tradeChannel": TRADE_CHANNEL,
        "tradePeriod": TRADE_PERIOD,
    }
    return send_order("期权下单(O)-买入", url_for("unified_create"), body)


def create_option_short():
    """期权沽空 (businessType=OS，方向卖出)"""
    body = {
        "accountType": ACCOUNT_TYPE,
        "businessType": "OS",                   # 订单类型: OS-期权沽空
        "entrustProp": ENTRUST_PROP,
        "entrustPrice": ENTRUST_PRICE,
        "entrustQty": ENTRUST_QTY,
        "entrustSide": "S",
        "entrustWay": ENTRUST_WAY,
        "forceEntrustFlag": FORCE_ENTRUST_FLAG,
        "fundAccount": FUND_ACCOUNT,
        "currency": CURRENCY,
        "market": MARKET,
        "notice": NOTICE,
        "symbol": SYMBOL,                       # 期权沽空必须用期权代码
        "tradeChannel": TRADE_CHANNEL,
        "tradePeriod": TRADE_PERIOD,
    }
    return send_order("期权沽空下单(OS)", url_for("unified_create"), body)


# ============================ 改单 ============================

def replace_option(order_id, entrust_price=ENTRUST_PRICE, entrust_qty=ENTRUST_QTY,
                   force_entrust_flag=FORCE_ENTRUST_FLAG):
    """期权改单: 只需 orderId + 新的价格/数量"""
    body = {
        "accountType": ACCOUNT_TYPE,
        "entrustPrice": entrust_price,
        "entrustQty": entrust_qty,
        "forceEntrustFlag": force_entrust_flag,
        "orderId": order_id,
    }
    return send_order("期权改单", url_for("unified_replace"), body)


# ============================ 撤单 ============================

def cancel_option(order_id, is_force_cancel=True):
    """期权撤单"""
    body = {
        "accountType": ACCOUNT_TYPE,
        "isForceCancel": is_force_cancel,
        "orderId": order_id,
    }
    return send_order("期权撤单", url_for("unified_cancel"), body)


if __name__ == "__main__":
    #create_option_buy()
    create_option_short()
    # replace_option(1603187803628908544, entrust_price=1.8, entrust_qty=2)
    # cancel_option(1603187803628908544)
