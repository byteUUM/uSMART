"""
统一下单 —— 股票 / 股票沽空
============================
接口:
  下单: /order-center-sg/admin-api/unified-order-create/v1  (businessType = S / SHORT)
  改单: /order-center-sg/admin-api/unified-order-replace/v1
  撤单: /order-center-sg/admin-api/unified-order-cancel/v1

说明:
  - 可统一配置的字段来自 common.config；本文件顶部只放"股票业务特有"的字段。
  - 需要特殊化时，直接改本文件顶部变量，或在函数里覆盖单个字段即可。
"""
import os
import sys

# --- 引导: 把项目根目录(order_api_tests)加入 sys.path，保证可直接运行本文件 ---
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from common.client import send_order
from common.config import ACCOUNT_TYPE, DEFAULT_FUND_ACCOUNT, SHORT_FUND_ACCOUNT, url_for

# ============================ 股票业务字段(可单独修改) ============================
FUND_ACCOUNT = DEFAULT_FUND_ACCOUNT   # 普通买卖资金账号(默认统一账号，可单独覆盖)
SHORT_ACCOUNT = SHORT_FUND_ACCOUNT    # 股票沽空专用资金账号(沽空权限账号，与普通账号不同)
CURRENCY = "USA"                      # 币种: CNY/USD/HKD
MARKET = "US"                         # 市场: HK/US/HGT/SGT
SYMBOL = "AAPL"                       # 股票代码
ENTRUST_WAY = "NET"                   # 委托方式: TEL/NET
ENTRUST_PROP = "MKT"                  # 委托属性: LMT/ELMT/MKT/AM/AL
ENTRUST_PRICE = "0"                   # 委托价格(市价单传 0)
ENTRUST_QTY = 10                      # 委托数量
FORCE_ENTRUST_FLAG = True             # 是否强制委托
NOTICE = True                         # 是否盘后触发通知
TRADE_CHANNEL = "IB-30%-U90117214"    # 交易通道
TRADE_PERIOD = "N"                    # 交易时段: N-正常, OG-盘后


# ============================ 下单 ============================

def create_stock_buy():
    """股票 - 普通买入 (businessType=S)"""
    body = {
        "accountType": ACCOUNT_TYPE,            # 账户类型: 1-普通, 2-高级
        "businessType": "S",                    # 订单类型: S-股票
        "entrustProp": ENTRUST_PROP,            # 委托属性
        "entrustPrice": ENTRUST_PRICE,          # 委托价格
        "entrustQty": ENTRUST_QTY,              # 委托数量
        "entrustSide": "B",                     # 委托方向: B-买入, S-卖出
        "entrustWay": ENTRUST_WAY,              # 委托方式
        "forceEntrustFlag": FORCE_ENTRUST_FLAG,
        "fundAccount": FUND_ACCOUNT,
        "currency": CURRENCY,
        "market": MARKET,
        "notice": NOTICE,
        "symbol": SYMBOL,
        "tradeChannel": TRADE_CHANNEL,
        "tradePeriod": TRADE_PERIOD,
    }
    return send_order("股票下单(S)-买入", url_for("unified_create"), body)


def create_stock_short():
    """股票沽空 (businessType=SHORT，方向卖出)。使用沽空专用资金账号"""
    body = {
        "accountType": ACCOUNT_TYPE,
        "businessType": "SHORT",                # 订单类型: SHORT-股票沽空
        "entrustProp": ENTRUST_PROP,
        "entrustPrice": ENTRUST_PRICE,
        "entrustQty": ENTRUST_QTY,
        "entrustSide": "S",                     # 沽空为卖出
        "entrustWay": ENTRUST_WAY,
        "forceEntrustFlag": FORCE_ENTRUST_FLAG,
        "fundAccount": SHORT_ACCOUNT,           # 沽空专用账号，不能用 FUND_ACCOUNT
        "currency": CURRENCY,
        "market": MARKET,
        "notice": NOTICE,
        "symbol": SYMBOL,
        "tradeChannel": TRADE_CHANNEL,
        "tradePeriod": TRADE_PERIOD,
    }
    return send_order("股票沽空下单(SHORT)", url_for("unified_create"), body)


# ============================ 改单 ============================

def replace_stock(order_id, entrust_price=ENTRUST_PRICE, entrust_qty=ENTRUST_QTY,
                  force_entrust_flag=FORCE_ENTRUST_FLAG):
    """股票改单: 只需 orderId + 新的价格/数量"""
    body = {
        "accountType": ACCOUNT_TYPE,            # 账户类型(必填)
        "entrustPrice": entrust_price,          # 改单价格(必填)
        "entrustQty": entrust_qty,              # 改单数量(必填)
        "forceEntrustFlag": force_entrust_flag,
        "orderId": order_id,                    # 订单ID(必填, int64)
    }
    return send_order("股票改单", url_for("unified_replace"), body)


# ============================ 撤单 ============================

def cancel_stock(order_id, is_force_cancel=True):
    """股票撤单"""
    body = {
        "accountType": ACCOUNT_TYPE,            # 账户类型(必填)
        "isForceCancel": is_force_cancel,       # 是否强制撤单
        "orderId": order_id,                    # 订单ID(必填, int64)
    }
    return send_order("股票撤单", url_for("unified_cancel"), body)


if __name__ == "__main__":
    # 按需取消注释运行
    # create_stock_buy()
    # create_stock_short()
    replace_stock(1609633428018679808, entrust_price="110", entrust_qty=30)
    # cancel_stock("16005909214509793282")
