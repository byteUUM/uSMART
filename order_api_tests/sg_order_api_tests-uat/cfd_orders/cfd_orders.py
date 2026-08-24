"""
CFD —— 下单 / 改单 / 撤单
=========================
接口:
  下单: /order-center-sg/admin-api/cfd-order-create/v1
  改单: /order-center-sg/admin-api/cfd-order-replace/v1
  撤单: /order-center-sg/admin-api/cfd-order-cancel/v1

重要:
  - CFD 必须使用专用资金账号(70000093)，不能和股票/期权/碎股账号混用。
  - validDate 必须是 yyyy-MM-dd(月/日补零，如 9 要写成 09)，否则报 "could not be parsed"。
  - 市价单(MKT)只支持 GE 订单; 限价单(LMT)才能配 GTC/GTD。
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from common.client import send_order
from common.config import CFD_FUND_ACCOUNT, url_for

# ============================ CFD 业务字段(可单独修改) ============================
FUND_ACCOUNT = CFD_FUND_ACCOUNT       # CFD 专用资金账号
MARKET = "CUS"                        # 市场(CFD1 / CUS 二选一)
SYMBOL = "AAPL"                       # 货币对/标的
ENTRUST_WAY = "NET"
ENTRUST_PROP = "LMT"                  # LMT/ELMT/MKT/AM/AL
ENTRUST_PRICE = 316.18                # 价格(市价单传 0)
ENTRUST_QTY = 12
ORDER_TYPE = "GTD"                    # Time-in-force: GE / GTD / GTC
VALID_DATE = "2026-10-09"             # GTD 订单有效期(GMT), 格式 yyyy-MM-dd
FORCE_ENTRUST_FLAG = False            # 是否强制委托(弹窗二次确认)
FORCED = False                        # 是否强平


# ============================ 下单 ============================

def create_cfd_buy():
    """CFD - 买入"""
    body = {
        "entrustPrice": ENTRUST_PRICE,          # 价格(市价单传 0)
        "entrustProp": ENTRUST_PROP,            # 委托属性
        "entrustQty": ENTRUST_QTY,              # 委托数量
        "entrustSide": "B",                     # 委托方向
        "entrustWay": ENTRUST_WAY,              # 下单方式
        "forceEntrustFlag": FORCE_ENTRUST_FLAG,
        "forced": FORCED,                       # 是否强平
        "fundAccount": FUND_ACCOUNT,            # CFD 专用账号
        "market": MARKET,                       # 市场(CFD1/CUS)
        "orderType": ORDER_TYPE,                # Time-in-force
        "symbol": SYMBOL,
        "validDate": VALID_DATE,                # GTD 有效期
    }
    return send_order("CFD下单-买入", url_for("cfd_create"), body)


def create_cfd_sell():
    """CFD - 卖出"""
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
    return send_order("CFD下单-卖出", url_for("cfd_create"), body)


# ============================ 改单 ============================

def replace_cfd(order_id, entrust_price=ENTRUST_PRICE, entrust_qty=ENTRUST_QTY,
                force_entrust_flag=FORCE_ENTRUST_FLAG, fund_account=FUND_ACCOUNT):
    """CFD 改单"""
    body = {
        "entrustPrice": entrust_price,          # 改单价格(必填)
        "entrustQty": entrust_qty,              # 改单数量(必填)
        "forceEntrustFlag": force_entrust_flag,
        "fundAccount": fund_account,            # 资金账号(中台需要)
        "orderId": order_id,                    # 订单ID(必填, int64)
    }
    return send_order("CFD改单", url_for("cfd_replace"), body)


# ============================ 撤单 ============================

def cancel_cfd(order_id, is_force_cancel=True, fund_account=FUND_ACCOUNT):
    """CFD 撤单"""
    body = {
        "fundAccount": fund_account,            # 资金账号(中台撤单需要)
        "isForceCancel": is_force_cancel,       # 是否强制撤单
        "orderId": order_id,                    # 订单ID(必填, int64)
    }
    return send_order("CFD撤单", url_for("cfd_cancel"), body)


if __name__ == "__main__":
    create_cfd_buy()
    # create_cfd_sell()
    # replace_cfd(1603193623347343360, entrust_price=200.0, entrust_qty=10)
    # cancel_cfd(1603193623347343360)
