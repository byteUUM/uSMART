"""
统一下单 —— 期权组合(组合期权)
================================
接口:
  下单: /order-center-sg/admin-api/unified-order-create/v1  (带 comboLegs 组合腿)
  改单: /order-center-sg/admin-api/unified-order-replace/v1
  撤单: /order-center-sg/admin-api/unified-order-cancel/v1

组合下单要点(来自接口文档):
  - comboLegs: 组合下单明细(数组)，每条腿包含 businessType / entrustSide / legRatio / symbol
  - legRatio : 每腿期权订单数量比例，最大值 <=1 且两个订单比例必须为系数。
               如 2 和 4 不正确，需改为 1 和 2。
  - comboType/comboStrategy: 组合类型/组合策略
  - 组合下单时顶层 symbol 不用传送(单腿才需要)。

注意: 组合期权的具体腿代码/策略值需按实际测试环境标的调整，下方为示例。
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from common.client import send_order
from common.config import ACCOUNT_TYPE, DEFAULT_FUND_ACCOUNT, url_for

# ============================ 组合业务字段(可单独修改) ============================
FUND_ACCOUNT = DEFAULT_FUND_ACCOUNT
CURRENCY = "USA"
MARKET = "US"
ENTRUST_WAY = "NET"
ENTRUST_PROP = "LMT"
ENTRUST_PRICE = 1.5                   # 组合净价
ENTRUST_QTY = 1
FORCE_ENTRUST_FLAG = True
NOTICE = True
TRADE_CHANNEL = "VELOX-30%-2UT00110"
TRADE_PERIOD = "N"

COMBO_TYPE = 1                        # 组合类型(int)
COMBO_STRATEGY = "VERTICAL"           # 组合策略(示例，按实际取值调整)

# 组合腿(示例: 两腿纵向价差，比例 1:1)
COMBO_LEGS = [
    {
        "businessType": "O",         # 组合腿单类型: S/O 等
        "entrustSide": "B",          # 委托方向: B-买入, S-卖出
        "legRatio": 1,               # 数量比例(见上方说明)
        "symbol": "UTL260918C50000",  # 该腿的期权代码
    },
    {
        "businessType": "O",
        "entrustSide": "S",
        "legRatio": 1,
        "symbol": "UTL260918C55000",
    },
]


# ============================ 下单 ============================

def create_combo():
    """组合期权下单"""
    body = {
        "accountType": ACCOUNT_TYPE,
        "businessType": "O",                    # 组合以期权为主
        # "comboType": COMBO_TYPE,                # 组合类型
        # "comboStrategy": COMBO_STRATEGY,        # 组合策略
        "comboLegs": COMBO_LEGS,                # 组合腿明细
        "entrustProp": ENTRUST_PROP,
        "entrustPrice": ENTRUST_PRICE,
        "entrustQty": ENTRUST_QTY,
        "entrustSide": "B",                     # 组合整体方向
        "entrustWay": ENTRUST_WAY,
        "forceEntrustFlag": FORCE_ENTRUST_FLAG,
        "fundAccount": FUND_ACCOUNT,
        "currency": CURRENCY,
        "market": MARKET,
        "notice": NOTICE,
        # 组合下单不传顶层 symbol
        "tradeChannel": TRADE_CHANNEL,
        "tradePeriod": TRADE_PERIOD,
    }
    return send_order("期权组合下单", url_for("unified_create"), body)


# ============================ 改单 ============================

def replace_combo(order_id, entrust_price=ENTRUST_PRICE, entrust_qty=ENTRUST_QTY,
                  force_entrust_flag=FORCE_ENTRUST_FLAG):
    """组合改单: 与股票/期权改单共用统一改单接口"""
    body = {
        "accountType": ACCOUNT_TYPE,
        "entrustPrice": entrust_price,
        "entrustQty": entrust_qty,
        "forceEntrustFlag": force_entrust_flag,
        "orderId": order_id,
    }
    return send_order("期权组合改单", url_for("unified_replace"), body)


# ============================ 撤单 ============================

def cancel_combo(order_id, is_force_cancel=True):
    """组合撤单: 与股票/期权撤单共用统一撤单接口"""
    body = {
        "accountType": ACCOUNT_TYPE,
        "isForceCancel": is_force_cancel,
        "orderId": order_id,
    }
    return send_order("期权组合撤单", url_for("unified_cancel"), body)


if __name__ == "__main__":
    create_combo()
    # replace_combo(1600243028902756352, entrust_price=1.8, entrust_qty=2)
    # cancel_combo(1600243028902756352)
