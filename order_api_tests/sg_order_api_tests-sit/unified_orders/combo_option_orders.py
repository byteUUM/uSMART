"""
统一下单 —— 期权组合(组合期权)
================================
接口:
  下单: /order-center-sg/admin-api/unified-order-create/v1  (带 comboLegs 组合腿)
  改单: /order-center-sg/admin-api/unified-order-replace/v1
  撤单: /order-center-sg/admin-api/unified-order-cancel/v1

组合下单要点(SIT 实测):
  - 顶层 symbol 必传! 且必须是"期权代码"(businessType=O 时服务端按期权校验)。
    组合场景取第一条期权腿的 symbol 即可; 带股票腿的策略(备兑/领式)不能取股票腿。
    不传顶层 symbol 时服务端直接抛 100012 "服务繁忙,请稍后重试"(内部空指针)。
  - comboLegs   : 组合腿明细, 每条腿 businessType / entrustSide / legRatio / symbol。
  - comboStrategy: 组合策略枚举(见 COMBO_STRATEGIES)。实测不传也能下单成功,
                   但建议按策略显式传, 服务端才能正确识别组合类型。
  - comboType   : 文档里的"组合类型", 实测不需要传, 传了也不影响, 这里不传。
  - legRatio    : 每腿数量比例, 需 >=1 且各腿比例互质(2 和 4 不合法, 应写 1 和 2)。
  - 期权代码格式: 标的 + 到期日(YYMMDD) + C/P + 行权价x1000(6位)
                  例: UTL 2026-09-18 Call 行权价 50 -> UTL260918C50000
  - 到期日必须晚于当前日期, 否则报 400060 "期权已过期，不可交易"。

实测结果(SIT, 账号 80125438): 下方 6 个策略均返回 code:0。
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
ENTRUST_WAY = "NET"                   # 组合按净价委托
ENTRUST_PROP = "LMT"
ENTRUST_PRICE = 1.5                   # 组合净价
ENTRUST_QTY = 1
ENTRUST_SIDE = "B"                    # 组合整体方向
FORCE_ENTRUST_FLAG = True
NOTICE = True
TRADE_CHANNEL = "VELOX-30%-2UT00110"
TRADE_PERIOD = "N"

# ============================ 组合策略(comboStrategy 枚举 + 对应腿) ============================
# VERTICAL_CALL 垂直价差(Call)  买低行权价 Call + 卖高行权价 Call
# VERTICAL_PUT  垂直价差(Put)   买高行权价 Put  + 卖低行权价 Put
# STRADDLE      跨式            同行权价 买 Call + 买 Put
# STRANGLE      宽跨式          不同行权价 买 Put + 买 Call
# COVERED_CALL  备兑            买股票 + 卖 Call
# COLLAR        领式            买股票 + 买 Put + 卖 Call
COMBO_STRATEGIES = {
    "牛市价差": {
        "comboStrategy": "VERTICAL_CALL",
        "comboLegs": [
            {"businessType": "O", "entrustSide": "B", "legRatio": 1, "symbol": "UTL260918C50000"},
            {"businessType": "O", "entrustSide": "S", "legRatio": 1, "symbol": "UTL260918C55000"},
        ],
    },
    "熊市价差": {
        "comboStrategy": "VERTICAL_PUT",
        "comboLegs": [
            {"businessType": "O", "entrustSide": "B", "legRatio": 1, "symbol": "UTL260918P55000"},
            {"businessType": "O", "entrustSide": "S", "legRatio": 1, "symbol": "UTL260918P50000"},
        ],
    },
    "跨式": {
        "comboStrategy": "STRADDLE",
        "comboLegs": [
            {"businessType": "O", "entrustSide": "B", "legRatio": 1, "symbol": "UTL260918C50000"},
            {"businessType": "O", "entrustSide": "B", "legRatio": 1, "symbol": "UTL260918P50000"},
        ],
    },
    "宽跨式": {
        "comboStrategy": "STRANGLE",
        "comboLegs": [
            {"businessType": "O", "entrustSide": "B", "legRatio": 1, "symbol": "UTL260918P50000"},
            {"businessType": "O", "entrustSide": "B", "legRatio": 1, "symbol": "UTL260918C55000"},
        ],
    },
    "备兑": {
        "comboStrategy": "COVERED_CALL",
        "comboLegs": [
            {"businessType": "S", "entrustSide": "B", "legRatio": 1, "symbol": "UTL"},
            {"businessType": "O", "entrustSide": "S", "legRatio": 1, "symbol": "UTL260918C50000"},
        ],
    },
    "领式": {
        "comboStrategy": "COLLAR",
        "comboLegs": [
            {"businessType": "S", "entrustSide": "B", "legRatio": 1, "symbol": "UTL"},
            {"businessType": "O", "entrustSide": "B", "legRatio": 1, "symbol": "UTL260918P50000"},
            {"businessType": "O", "entrustSide": "S", "legRatio": 1, "symbol": "UTL260918C55000"},
        ],
    },
}

# 默认使用的策略
DEFAULT_STRATEGY = "牛市价差"


def _top_symbol(combo_legs):
    """
    顶层 symbol 取值: 第一条期权腿(businessType=O)的代码。
    因为顶层 businessType=O, 服务端会按期权代码校验; 若传股票腿代码会报
    400064 "期权代码不存在请重新输入"。
    """
    for leg in combo_legs:
        if leg.get("businessType") == "O":
            return leg["symbol"]
    return combo_legs[0]["symbol"]


# ============================ 下单 ============================

def create_combo(strategy=DEFAULT_STRATEGY, entrust_price=ENTRUST_PRICE,
                 entrust_qty=ENTRUST_QTY, entrust_side=ENTRUST_SIDE, **override):
    """
    组合期权下单。
    strategy: COMBO_STRATEGIES 的 key, 如 "牛市价差" / "跨式" / "备兑"。
    override: 需要临时覆盖的请求体字段。
    """
    s = COMBO_STRATEGIES[strategy]
    combo_legs = s["comboLegs"]
    body = {
        "accountType": ACCOUNT_TYPE,
        "businessType": "O",                       # 组合以期权为主
        "comboLegs": combo_legs,                   # 组合腿明细
        "comboStrategy": s["comboStrategy"],       # 组合策略
        "entrustProp": ENTRUST_PROP,
        "entrustPrice": entrust_price,
        "entrustQty": entrust_qty,
        "entrustSide": entrust_side,               # 组合整体方向
        "entrustWay": ENTRUST_WAY,
        "forceEntrustFlag": FORCE_ENTRUST_FLAG,
        "fundAccount": FUND_ACCOUNT,
        "currency": CURRENCY,
        "market": MARKET,
        "notice": NOTICE,
        "symbol": _top_symbol(combo_legs),         # 必传: 首个期权腿代码
        "tradeChannel": TRADE_CHANNEL,
        "tradePeriod": TRADE_PERIOD,
    }
    body.update(override)
    return send_order(f"期权组合下单-{strategy}({s['comboStrategy']})",
                      url_for("unified_create"), body)


def create_all_strategies():
    """依次下单所有策略, 返回 {策略名: orderId} (仅收集 code=0 的)。"""
    result = {}
    for name in COMBO_STRATEGIES:
        resp = create_combo(name)
        if resp is None:
            continue
        try:
            data = resp.json()
        except ValueError:
            continue
        if data.get("code") == 0 and data.get("data"):
            result[name] = data["data"]["id"]
    print("\n>>> 下单成功的组合订单:", result)
    return result


# ============================ 改单 ============================

def replace_combo(order_id, strategy=DEFAULT_STRATEGY, entrust_price=ENTRUST_PRICE,
                  entrust_qty=ENTRUST_QTY, force_entrust_flag=FORCE_ENTRUST_FLAG):
    """
    组合改单: 与股票/期权改单共用统一改单接口。
    组合订单改单不传 businessType, 但要带上 comboLegs + comboStrategy。
    """
    s = COMBO_STRATEGIES[strategy]
    body = {
        "accountType": ACCOUNT_TYPE,
        "comboLegs": s["comboLegs"],
        "comboStrategy": s["comboStrategy"],
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
    create_combo()                      # 默认牛市价差(VERTICAL_CALL)
    # create_combo("跨式")
    # create_combo("备兑")
    # create_all_strategies()           # 跑一遍全部 6 个策略
    # replace_combo(1608215465948340225, entrust_price=1.8, entrust_qty=2)
    # cancel_combo(1608215465948340225)
