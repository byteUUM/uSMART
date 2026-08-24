"""
3.4 期权沽空 最大可卖 (OPS-01 ~ OPS-09)
========================================
接口:
  期权沽空最大可卖     : /order-center-sg/admin-api/short-option-sell-max/v1
  期权沽空改单最大可卖 : /order-center-sg/admin-api/short-option-replace-sell-max/v1

改动点: 四路查询并行；两种取用户信息路径(不传/传 fundAccount)；权限校验方式变化。
验证重点:
  - 不传 fundAccount 时按 token 用户取资金账号
  - 无沽空权限错误码已从 OPTION_NO_OPTION_PRIVILEGE 变为 NO_CORRESPONDING_TRADE_PERMISSION
  - 传 entrustQty + entrustSide 才算 deltaMargin, 任一为空时预计保证金返回 0
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from common.client import (
    check_baseline,
    expect_code,
    expect_error,
    expect_no_server_error,
    send_query,
    show_fields,
)
from common.config import (
    ACCOUNT_TYPE,
    DEFAULT_FUND_ACCOUNT,
    NO_OPTION_SHORT_ACCOUNT,
    NOT_EXIST_FUND_ACCOUNT,
    OPTION_SHORT_ORDER_ID,
    OPTION_SYMBOL,
    url_for,
)

# ============================ 期权沽空业务字段(可单独修改) ============================
ENTRUST_PRICE = 1.5         # 委托价格(无需乘以乘数)
ENTRUST_QTY = 1             # 委托数量
ENTRUST_SIDE = "S"          # 沽空为卖出

# 关注字段(响应 data)
# ★未验证: 手上所有账号都没有 OPTION_SHORT 权限(全部返回 400505「无对应交易权限」)，
#   所以拿不到一次成功响应, 下面的字段名仍是按文档推测的, 拿到成功响应后需要校正。
OPS_FIELDS = ["maxSellQty", "maxPurchasePower", "deltaMargin", "underlyingPrice"]


# ============================ 请求体构造 ============================

def _sell_max_body(fund_account=None, **override):
    """
    期权沽空最大可卖 请求体。
    fund_account 传 None = 不传 fundAccount(按 token 用户取), 中台请求才需要传。
    """
    body = {
        "accountType": ACCOUNT_TYPE,        # 1-普通账户, 2-高级账户(必填)
        "entrustPrice": ENTRUST_PRICE,      # 委托价格(必填)
        "entrustQty": ENTRUST_QTY,          # 委托数量(必填)
        "entrustSide": ENTRUST_SIDE,        # B-买入 S-卖出(必填)
        "symbol": OPTION_SYMBOL,            # 期权代码(必填)
    }
    if fund_account is not None:
        body["fundAccount"] = fund_account
    body.update(override)
    return body


def _replace_sell_max_body(order_id, fund_account=DEFAULT_FUND_ACCOUNT, **override):
    """期权沽空改单最大可卖 请求体。"""
    body = {
        "entrustPrice": ENTRUST_PRICE,      # 价格必须传
        "entrustQty": ENTRUST_QTY,          # 委托数量(必填)
        "fundAccount": fund_account,        # 资金账号(中台请求需要)
        "orderId": order_id,                # 订单编号
    }
    body.update(override)
    return body


# ============================ OPS-01 ============================

def ops_01_without_fund_account():
    """
    OPS-01 不传资金账号(APP 侧) —— 按 token 用户取资金账号

    实测阻塞: 在中台地址(usmartclient-sit + admin-api)上不传 fundAccount 会直接返回
             「资金帐号不能为空」, 中台路由不会按 token 取资金账号。
             本用例必须在 **APP 网关地址** 上验证:
             先在 config.py 配好 APP_BASE_URL, 再把 USE_APP_GATEWAY 设为 True。
    """
    from common.config import USE_APP_GATEWAY

    result = send_query("OPS-01 不传fundAccount", url_for("option_short_max"),
                        _sell_max_body(fund_account=None))
    if not USE_APP_GATEWAY:
        print("[阻塞] 当前走中台地址, 不传 fundAccount 必然报「资金帐号不能为空」。")
        print("       请配置 config.APP_BASE_URL 并设 USE_APP_GATEWAY=True 后重跑本用例。")
        return result
    show_fields(result, OPS_FIELDS)
    check_baseline("OPS-01", result)
    return result


# ============================ OPS-02 ============================

def ops_02_with_fund_account():
    """OPS-02 传资金账号 + 有沽空权限 —— 正常返回最大可卖/购买力/预计保证金"""
    result = send_query("OPS-02 传fundAccount(有权限)", url_for("option_short_max"),
                        _sell_max_body(DEFAULT_FUND_ACCOUNT))
    show_fields(result, OPS_FIELDS)
    check_baseline("OPS-02", result)
    return result


# ============================ OPS-03 ============================

def ops_03_no_permission():
    """
    OPS-03 传资金账号 + 无沽空权限
    期望 NO_CORRESPONDING_TRADE_PERMISSION(文案「无对应交易权限」)。
    注意: 错误码较原 OPTION_NO_OPTION_PRIVILEGE 已变化, 前端/告警需同步核对。
    """
    if not NO_OPTION_SHORT_ACCOUNT:
        print("[OPS-03] 跳过: 请先在 config.NO_OPTION_SHORT_ACCOUNT 填入无期权沽空权限的账号")
        return None
    result = send_query("OPS-03 无沽空权限", url_for("option_short_max"),
                        _sell_max_body(NO_OPTION_SHORT_ACCOUNT))
    # 实测: code=400505, msg=「无对应交易权限」-> 新错误码已生效
    hit_new = expect_code(result, "NO_CORRESPONDING_TRADE_PERMISSION")
    if not hit_new:
        print("[提示] 检查是否仍返回旧文案(期权无权限/OPTION_NO_OPTION_PRIVILEGE):")
        expect_error(result, "期权")
    return result


# ============================ OPS-04 ============================

def ops_04_fund_account_not_exist():
    """OPS-04 资金账号不存在 —— 期望 OPTION_FUND_ACCOUNT_ERROR"""
    result = send_query("OPS-04 资金账号不存在", url_for("option_short_max"),
                        _sell_max_body(NOT_EXIST_FUND_ACCOUNT))
    # 实测: code=400092, msg=「资金账号不正确！」
    expect_code(result, "OPTION_FUND_ACCOUNT_ERROR")
    expect_no_server_error(result)
    return result


# ============================ OPS-05 ============================

def ops_05_with_qty_and_side():
    """OPS-05 传委托数量 + 方向 —— 计算预计保证金 deltaMargin"""
    result = send_query("OPS-05 传entrustQty+entrustSide", url_for("option_short_max"),
                        _sell_max_body(DEFAULT_FUND_ACCOUNT, entrustQty=2, entrustSide="S"))
    data = show_fields(result, OPS_FIELDS)
    print("[校验] deltaMargin 应有值, 实际:", data.get("deltaMargin"))
    check_baseline("OPS-05", result)
    return result


# ============================ OPS-06 ============================

def ops_06_without_qty_or_side():
    """OPS-06 不传委托数量/方向 —— 预计保证金应返回 0"""
    body = _sell_max_body(DEFAULT_FUND_ACCOUNT)
    body.pop("entrustQty", None)
    r1 = send_query("OPS-06 不传entrustQty", url_for("option_short_max"), body)
    d1 = show_fields(r1, OPS_FIELDS)
    print("[校验] deltaMargin 应为 0, 实际:", d1.get("deltaMargin"))

    body2 = _sell_max_body(DEFAULT_FUND_ACCOUNT)
    body2.pop("entrustSide", None)
    r2 = send_query("OPS-06 不传entrustSide", url_for("option_short_max"), body2)
    d2 = show_fields(r2, OPS_FIELDS)
    print("[校验] deltaMargin 应为 0, 实际:", d2.get("deltaMargin"))
    return r1, r2


# ============================ OPS-07 ============================

def ops_07_fee_pack_fallback():
    """
    OPS-07 佣金套餐兜底分配(rejesteredFeePack)
    packId 传 null 不影响, 内部仅用 userId —— 应正常返回不报错。
    """
    result = send_query("OPS-07 佣金套餐兜底", url_for("option_short_max"),
                        _sell_max_body(DEFAULT_FUND_ACCOUNT, feeId=None))
    show_fields(result, OPS_FIELDS)
    expect_no_server_error(result)
    return result


# ============================ OPS-08 ============================

def ops_08_user_info_none():
    """
    OPS-08 用户信息缓存为空 —— 抛业务异常, 不出现 NPE
    实测: 空 fundAccount -> 「资金帐号不能为空」; 取不到用户信息 -> 450004「获取用户信息异常」
    """
    r1 = send_query("OPS-08 空资金账号", url_for("option_short_max"), _sell_max_body(""))
    expect_code(r1, "FUNDACCOUNT_EMPTY")
    expect_no_server_error(r1)

    r2 = send_query("OPS-08 取不到用户信息", url_for("option_short_max"),
                    _sell_max_body(NOT_EXIST_FUND_ACCOUNT))
    expect_no_server_error(r2)
    return r1, r2


# ============================ OPS-09 ============================

def ops_09_parallel_consistency(times=5):
    """OPS-09 四路并行一致性 —— 购买力/正股价/保证金算法/预计保证金 多次结果应一致"""
    baseline = None
    for i in range(times):
        result = send_query(f"OPS-09 第{i + 1}次查询", url_for("option_short_max"),
                            _sell_max_body(DEFAULT_FUND_ACCOUNT))
        data = (result.get("json") or {}).get("data")
        if baseline is None:
            baseline = data
        elif data != baseline:
            print(f"[校验] 第{i + 1}次与首次结果不一致 [FAIL]")
            print("   首次:", baseline)
            print("   本次:", data)
            return False
    print(f"[校验] {times} 次并行查询结果完全一致 [PASS]")
    return True


# ============================ 期权沽空改单最大可卖 ============================

def ops_replace_sell_max(order_id=OPTION_SHORT_ORDER_ID):
    """期权沽空改单最大可卖"""
    if not order_id:
        print("[OPS-改单] 跳过: 请先在 config.OPTION_SHORT_ORDER_ID 填入期权沽空在途订单ID")
        return None
    result = send_query("OPS 期权沽空改单最大可卖", url_for("option_short_replace_max"),
                        _replace_sell_max_body(order_id))
    show_fields(result, OPS_FIELDS)
    check_baseline("OPS-replace", result)
    return result


if __name__ == "__main__":
    ops_01_without_fund_account()
    # ops_02_with_fund_account()
    # ops_03_no_permission()
    # ops_04_fund_account_not_exist()
    # ops_05_with_qty_and_side()
    # ops_06_without_qty_or_side()
    # ops_07_fee_pack_fallback()
    # ops_08_user_info_none()
    # ops_09_parallel_consistency()
    # ops_replace_sell_max()
