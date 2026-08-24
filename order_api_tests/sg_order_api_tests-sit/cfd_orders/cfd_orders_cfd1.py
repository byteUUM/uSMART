"""
CFD1(外汇货币对) —— 限价单 下单 / 改单 / 撤单
=============================================
接口:
  下单: /order-center-sg/admin-api/cfd-order-create/v1
  改单: /order-center-sg/admin-api/cfd-order-replace/v1
  撤单: /order-center-sg/admin-api/cfd-order-cancel/v1

与 cfd_orders.py(CUS 市场) 的差异:
  - market  : CUS -> CFD1
  - symbol  : 股票标的(TSLA) -> 货币对(EUR/USD), 响应里对应 currencyPair
              baseCurrency=EUR / bidCurrency=USD 由服务端按货币对解析
  - 价格/数量: 按货币对量级(1.1 左右的汇率, 数量 1000, lotSize=1)

重要:
  - CFD 必须使用专用资金账号，不能和股票/期权/碎股账号混用。
  - validDate 必须是 yyyy-MM-dd(月/日补零，如 9 要写成 09)，否则报 "could not be parsed"。
  - 限价单(LMT)才能配 GTC/GTD; 市价单(MKT)只支持 GE。
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from common.client import send_order
from common.config import CFD_FUND_ACCOUNT, url_for

# ============================ CFD1 业务字段(可单独修改) ============================
FUND_ACCOUNT = CFD_FUND_ACCOUNT       # CFD 专用资金账号(若该账号无 CFD1 权限, 可换成 "70000431")
MARKET = "CFD1"                       # 市场: CFD1(外汇货币对)
SYMBOL = "EUR/USD"                    # 货币对(响应 currencyPair), lotSize=1
ENTRUST_WAY = "NET"
ENTRUST_PROP = "LMT"                  # 限价单(LMT/ELMT/MKT/AM/AL)
ENTRUST_PRICE = 1.10000               # 限价(EUR/USD 汇率量级, 挂在市价之外便于改单/撤单)
ENTRUST_QTY = 1000                    # 委托数量
ORDER_TYPE = "GTD"                    # Time-in-force: GE / GTD / GTC
VALID_DATE = "2026-10-09"             # GTD 订单有效期(GMT), 格式 yyyy-MM-dd
FORCE_ENTRUST_FLAG = False            # 是否强制委托(弹窗二次确认)
FORCED = False                        # 是否强平


# ============================ 下单 ============================

def create_cfd1_buy():
    """CFD1 限价单 - 买入"""
    body = {
        "entrustPrice": ENTRUST_PRICE,          # 限价
        "entrustProp": ENTRUST_PROP,            # LMT
        "entrustQty": ENTRUST_QTY,              # 委托数量
        "entrustSide": "B",                     # 委托方向
        "entrustWay": ENTRUST_WAY,              # 下单方式
        "forceEntrustFlag": FORCE_ENTRUST_FLAG,
        "forced": FORCED,                       # 是否强平
        "fundAccount": FUND_ACCOUNT,            # CFD 专用账号
        "market": MARKET,                       # CFD1
        "orderType": ORDER_TYPE,                # Time-in-force
        "symbol": SYMBOL,                       # 货币对
        "validDate": VALID_DATE,                # GTD 有效期
    }
    return send_order("CFD1下单-限价买入", url_for("cfd_create"), body)


def create_cfd1_sell():
    """CFD1 限价单 - 卖出"""
    body = {
        "entrustPrice": ENTRUST_PRICE,
        "entrustProp": ENTRUST_PROP,
        "entrustQty": ENTRUST_QTY,
        "entrustSide": "S",
        "entrustWay": ENTRUST_WAY,
        "forceEntrustFlag": FORCE_ENTRUST_FLAG,
        "forced": FORCED,
        "fundAccount": FUND_ACCOUNT,
        "market": MARKET,
        "orderType": ORDER_TYPE,
        "symbol": SYMBOL,
        "validDate": VALID_DATE,
    }
    return send_order("CFD1下单-限价卖出", url_for("cfd_create"), body)


# ============================ 改单 ============================

def replace_cfd1(order_id, entrust_price=ENTRUST_PRICE, entrust_qty=ENTRUST_QTY,
                 force_entrust_flag=FORCE_ENTRUST_FLAG, fund_account=FUND_ACCOUNT):
    """CFD1 改单"""
    body = {
        "entrustPrice": entrust_price,          # 改单价格(必填)
        "entrustQty": entrust_qty,              # 改单数量(必填)
        "forceEntrustFlag": force_entrust_flag,
        "fundAccount": fund_account,            # 资金账号(中台需要)
        "orderId": order_id,                    # 订单ID(必填, int64)
    }
    return send_order("CFD1改单", url_for("cfd_replace"), body)


# ============================ 撤单 ============================

def cancel_cfd1(order_id, is_force_cancel=True, fund_account=FUND_ACCOUNT):
    """CFD1 撤单"""
    body = {
        "fundAccount": fund_account,            # 资金账号(中台撤单需要)
        "isForceCancel": is_force_cancel,       # 是否强制撤单
        "orderId": order_id,                    # 订单ID(必填, int64)
    }
    return send_order("CFD1撤单", url_for("cfd_cancel"), body)


if __name__ == "__main__":
    # create_cfd1_buy()
    # create_cfd1_sell()
    replace_cfd1(1609393562869682176, entrust_price=1.09000, entrust_qty=4000)
    # cancel_cfd1(1609250095258451968)
