"""
3.6 缓存失效 / 刷新触发 (RFS-01 ~ RFS-06)  * 本次最大生产风险区
================================================================
8 小时缓存引入后, 账户信息变更是否及时生效是最大风险点。
需要验证所有变更链路都能刷新缓存, 否则可能出现最长 8h 脏数据。

统一验证套路:
  1. 先查一次(让缓存写入) -> 记录旧值
  2. 执行变更操作(升融资 / 开户MQ / 加权限 / 降级 / 调刷新接口)
  3. 立刻再查 -> 结果应反映新值, 且缓存 key 被删除或已刷新

注意: 变更操作的接口路径/MQ 消息体 文档未提供,
     config.PATHS 里 margin_upgrade / refresh_user_cache 需先补齐。
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from common import cache
from common.client import build_headers, safe, send_query, show_fields
from common.config import (
    ACCOUNT_TYPE,
    CASH_ACCOUNT,
    MARGIN_ACCOUNT,
    PATHS,
    PRO_ACCOUNT,
    TOKENS,
    US_STOCK,
    url_for,
)

POWER_FIELDS = ["purchasePower", "consumePurchasingPower", "accountType"]


# ============================ 公共: 查询购买力 ============================

def _query_power(name, fund_account, token=None):
    """查询消耗购买力(内部会取用户信息, 用于观察缓存是否刷新)。"""
    body = {
        "accountType": ACCOUNT_TYPE,
        "businessType": "S",
        "currencyCode": US_STOCK["currency"],
        "entrustPrice": 100,
        "entrustQty": 10,
        "entrustSide": "B",
        "entrustWay": "NET",
        "fundAccount": fund_account,
        "handQty": US_STOCK["handQty"],
        "market": US_STOCK["market"],
        "symbol": US_STOCK["symbol"],
    }
    headers = build_headers(token=token or TOKENS.get(fund_account) or None)
    result = send_query(name, url_for("consume_power"), body, headers=headers)
    show_fields(result, POWER_FIELDS)
    return result


def _show_cache_state(fund_account, tag=""):
    """打印当前缓存 key 与 TTL 状态。"""
    print(f"\n---- 缓存状态 {tag} (账号 {fund_account}) ----")
    keys = cache.find_user_keys(fund_account)
    for key in keys:
        cache.get_value(key)
        cache.get_ttl(key)
    if not keys:
        print("(无缓存 key)")
    return keys


# ============================ RFS-01 ============================

def rfs_01_cash_to_margin(fund_account=CASH_ACCOUNT):
    """
    RFS-01 现金升融资后购买力 (P0)
    步骤: 查询预热缓存 -> 执行现金升融资 -> 立即查询
    预期: 缓存被刷新, accountType 变为 MARGIN, 购买力按融资口径(通常更高)
    """
    before = _query_power("RFS-01 升融资前购买力", fund_account)
    _show_cache_state(fund_account, "升融资前")

    if not PATHS.get("margin_upgrade"):
        print("\n[RFS-01] 现金升融资接口路径未配置(config.PATHS['margin_upgrade'])。")
        print("         请手工在管理后台执行「现金升融资」, 完成后再运行下面的复查:")
        print("         python -c \"import test_3_6_cache_refresh as t; t.rfs_01_recheck()\"")
        return before

    send_query("RFS-01 执行现金升融资", url_for("margin_upgrade"), {"fundAccount": fund_account})
    return rfs_01_recheck(fund_account, before)


def rfs_01_recheck(fund_account=CASH_ACCOUNT, before=None):
    """RFS-01 复查: 变更完成后立即查询, 对比购买力是否已按新口径。"""
    _show_cache_state(fund_account, "升融资后")
    after = _query_power("RFS-01 升融资后购买力", fund_account)
    if before:
        b = (before.get("json") or {}).get("data") or {}
        a = (after.get("json") or {}).get("data") or {}
        print("[对比] 升级前购买力:", b.get("purchasePower"), " 升级后:", a.get("purchasePower"))
        print("[校验] 升级后应按融资口径(通常更高), 且不应等于升级前的现金口径旧值")
    return after


# ============================ RFS-02 ============================

def rfs_02_new_fund_account_by_mq(new_fund_account=""):
    """
    RFS-02 开通新资金账号(MQ) (P0)
    步骤: 投递开户消息 -> 按新资金账号查询
    预期: 缓存刷新, 可按新资金账号查到用户信息
    """
    if not new_fund_account:
        print("[RFS-02] 请传入新开通的资金账号: rfs_02_new_fund_account_by_mq('8xxxxxxx')")
        return None

    print("[RFS-02] 开通前先查一次(预期查不到或报错):")
    _query_power("RFS-02 开通前查询新账号", new_fund_account)

    from common import mq
    from common.config import MQ_ROUTING_KEY
    if not MQ_ROUTING_KEY:
        print("\n[RFS-02] MQ exchange/routing key 未配置(config.MQ_EXCHANGE / MQ_ROUTING_KEY)。")
        print("         请手工触发开户流程, 完成后运行:")
        print("         python -c \"import test_3_6_cache_refresh as t; t.rfs_02_recheck('8xxxxxxx')\"")
        return None

    # TODO 消息体结构需向开发确认
    mq.publish({"fundAccount": new_fund_account, "eventType": "OPEN_FUND_ACCOUNT"})
    return rfs_02_recheck(new_fund_account)


def rfs_02_recheck(new_fund_account):
    """RFS-02 复查: 消费完消息后按新资金账号查询。"""
    _show_cache_state(new_fund_account, "开户后")
    return _query_power("RFS-02 开通后查询新账号", new_fund_account)


# ============================ RFS-03 ============================

def rfs_03_manual_refresh(fund_account=PRO_ACCOUNT):
    """
    RFS-03 内部接口手动刷新
    预期: 缓存被清并回源为最新
    """
    _query_power("RFS-03 刷新前查询(预热缓存)", fund_account)
    keys_before = _show_cache_state(fund_account, "刷新前")

    if not PATHS.get("refresh_user_cache"):
        print("\n[RFS-03] 刷新缓存内部接口路径未配置(config.PATHS['refresh_user_cache'])。")
        print("         可先用 Redis 直接删 key 验证回源效果:")
        cache.delete_keys(keys_before)
        _query_power("RFS-03 手工删缓存后查询", fund_account)
        return None

    send_query("RFS-03 调用刷新缓存接口", url_for("refresh_user_cache"),
               {"fundAccount": fund_account})
    _show_cache_state(fund_account, "刷新后")
    return _query_power("RFS-03 刷新后查询", fund_account)


# ============================ RFS-04 ============================

def rfs_04_refresh_lock_failed_self_heal(fund_account=PRO_ACCOUNT):
    """
    RFS-04 刷新抢锁失败自愈 (P0)
    预期: 刷新即使拿不到锁, 也会删除该用户缓存, 下次查询自然回源到最新,
         不会残留旧数据最长 8h。
    制造方式: 手工占用刷新锁, 再触发刷新, 然后检查缓存 key 是否已被删除。
    """
    _query_power("RFS-04 预热缓存", fund_account)
    _show_cache_state(fund_account, "占锁前")

    lock_keys = cache.scan_keys("*lock*user*")
    if not lock_keys:
        print("[RFS-04] 未扫描到刷新锁 key, 需向开发确认锁 key 命名")
        return None

    lock_key = lock_keys[0]
    cache.set_raw_value(lock_key, "manual-hold", ttl_seconds=60)
    print(f"[构造] 已占用锁 {lock_key} 60 秒")

    if PATHS.get("refresh_user_cache"):
        send_query("RFS-04 锁被占用时调刷新", url_for("refresh_user_cache"),
                   {"fundAccount": fund_account})
    else:
        print("[RFS-04] 刷新接口未配置, 请手工触发一次账户变更/刷新")
        input("        触发完成后按回车继续检查缓存...")

    keys_after = _show_cache_state(fund_account, "刷新后")
    if not keys_after:
        print("[校验] 缓存 key 已被删除, 自愈生效 [PASS]")
    else:
        print("[校验] 缓存 key 仍存在, 存在残留旧数据风险 [FAIL] 需确认自愈逻辑")

    cache.delete_keys(lock_key)
    return keys_after


# ============================ RFS-05 ============================

def rfs_05_add_trade_permission(fund_account=PRO_ACCOUNT):
    """
    RFS-05 新增交易权限后 (P0 — 文档标注需重点回归)
    预期: 新增权限(如 OPTION_SHORT)的链路应触发缓存刷新。
    风险: 若未接入刷新, 会出现「有权限却被拒(误报无权限)」最长至缓存过期。
    """
    from common.config import OPTION_SYMBOL
    body = {
        "accountType": ACCOUNT_TYPE,
        "entrustPrice": 1.5,
        "entrustQty": 1,
        "entrustSide": "S",
        "fundAccount": fund_account,
        "symbol": OPTION_SYMBOL,
    }

    print("步骤1: 权限开通前查询期权沽空最大可卖(预期无权限报错, 同时把用户信息写入缓存)")
    send_query("RFS-05 加权限前", url_for("option_short_max"), body)
    _show_cache_state(fund_account, "加权限前")

    print("\n步骤2: 请手工为该账号新增 OPTION_SHORT 交易权限")
    input("        开通完成后按回车继续...")

    _show_cache_state(fund_account, "加权限后")
    result = send_query("RFS-05 加权限后", url_for("option_short_max"), body)
    print("[校验] 应立即可用(不再报 NO_CORRESPONDING_TRADE_PERMISSION)")
    print("[校验] 若仍报无权限 -> 该变更链路未接入缓存刷新, 属缺陷, 需提单")
    return result


# ============================ RFS-06 ============================

def rfs_06_account_downgrade(fund_account=MARGIN_ACCOUNT):
    """
    RFS-06 账户降级(MARGIN -> CASH) (P0 — 文档标注需确认)
    预期: 缓存刷新后按 CASH 口径, 避免降级后仍按 MARGIN 高估购买力。
    """
    before = _query_power("RFS-06 降级前购买力(MARGIN)", fund_account)
    _show_cache_state(fund_account, "降级前")

    print("\n步骤: 请手工把该账号从 MARGIN 降级为 CASH")
    input("      降级完成后按回车继续...")

    _show_cache_state(fund_account, "降级后")
    after = _query_power("RFS-06 降级后购买力(应按CASH)", fund_account)

    b = (before.get("json") or {}).get("data") or {}
    a = (after.get("json") or {}).get("data") or {}
    print("[对比] 降级前购买力:", b.get("purchasePower"), " 降级后:", a.get("purchasePower"))
    print("[校验] 降级后购买力应下降到现金口径; 若与降级前相同 -> 缓存未刷新, 会高估购买力 [FAIL]")
    return after


if __name__ == "__main__":
    # 本章用例大多需要手工配合制造账户变更, 建议逐个单独执行
    safe(rfs_03_manual_refresh)
    # rfs_01_cash_to_margin()
    # rfs_02_new_fund_account_by_mq("8xxxxxxx")
    # rfs_04_refresh_lock_failed_self_heal()
    # rfs_05_add_trade_permission()
    # rfs_06_account_downgrade()
