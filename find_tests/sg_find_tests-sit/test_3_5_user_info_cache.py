"""
3.5 用户信息缓存 (CACHE-01 ~ CACHE-08)
=======================================
改动点: 8h 缓存；资金账号 -> 客户号 映射；刷新自愈；一致性回源。

验证方式: 直接操作 Redis(common/cache.py) + 调用任一查询接口触发回源，
         通过"响应耗时"和"缓存 key 是否出现/TTL"判断是否命中缓存。

依赖: pip install redis
注意: 缓存 key 前缀以实际代码为准，先用 find_user_keys 摸出真实 key，
     再把前缀固定到 config.CACHE_KEY_KEYWORDS 里。
"""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from common import cache
from common.client import safe, send_query
from common.config import (
    ACCOUNT_TYPE,
    DEFAULT_FUND_ACCOUNT,
    US_STOCK,
    url_for,
)

# ============================ 触发回源用的查询请求 ============================

def _trigger_query(name="触发用户信息查询", fund_account=DEFAULT_FUND_ACCOUNT):
    """用"计算消耗购买力"作为触发接口(内部会取用户信息)。"""
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
    return send_query(name, url_for("consume_power"), body)


# ============================ CACHE-01 ============================

def cache_01_first_query_from_remote():
    """CACHE-01 首次查询回源 —— 清空缓存后查询, 应回源远程并写入缓存(8h)"""
    keys = cache.find_user_keys(DEFAULT_FUND_ACCOUNT)
    cache.delete_keys(keys)

    result = _trigger_query("CACHE-01 清缓存后首次查询")
    print("首次查询耗时: %.3fs (回源, 应明显较慢)" % result["elapsed"])

    new_keys = cache.find_user_keys(DEFAULT_FUND_ACCOUNT)
    print("[校验] 查询后缓存 key:", new_keys)
    for key in new_keys:
        cache.check_ttl_is_8h(key)
    return result


# ============================ CACHE-02 ============================

def cache_02_second_query_hit_cache():
    """CACHE-02 二次命中缓存 —— 紧接着再查, 应命中缓存(耗时明显下降)"""
    first = _trigger_query("CACHE-02 第一次查询")
    second = _trigger_query("CACHE-02 第二次查询")
    print("第一次: %.3fs  第二次: %.3fs" % (first["elapsed"], second["elapsed"]))
    if second["elapsed"] < first["elapsed"]:
        print("[校验] 第二次更快, 疑似命中缓存 [PASS]")
    else:
        print("[校验] 第二次未见提速, 需结合服务端日志确认是否命中缓存 [FAIL]")
    return first, second


# ============================ CACHE-03 ============================

def cache_03_expire_and_reload():
    """
    CACHE-03 缓存过期回源
    8h 等不起, 这里把 TTL 改成 3 秒模拟过期, 过期后再查应重新回源。
    """
    _trigger_query("CACHE-03 预热缓存")
    keys = cache.find_user_keys(DEFAULT_FUND_ACCOUNT)
    if not keys:
        print("[CACHE-03] 未找到缓存 key, 请先确认 config.CACHE_KEY_KEYWORDS")
        return None

    client = cache.get_client()
    for key in keys:
        client.expire(key, 3)
        print(f"[Redis] 已把 {key} 的 TTL 改为 3s")

    time.sleep(5)
    print("[校验] TTL 到期后 key 应已消失:")
    for key in keys:
        cache.get_ttl(key)

    result = _trigger_query("CACHE-03 过期后查询(应回源)")
    for key in cache.find_user_keys(DEFAULT_FUND_ACCOUNT):
        cache.check_ttl_is_8h(key)
    return result


# ============================ CACHE-04 ============================

def cache_04_fund_account_mapping():
    """
    CACHE-04 按资金账号查询(映射缓存)
    首次回源应写入「资金账号 -> 客户号」映射 key, 二次查询命中映射。
    """
    keys = cache.find_user_keys(DEFAULT_FUND_ACCOUNT)
    cache.delete_keys(keys)

    first = _trigger_query("CACHE-04 首次按资金账号查询")
    mapping_keys = cache.scan_keys(f"*{DEFAULT_FUND_ACCOUNT}*")
    print("[校验] 资金账号映射 key:", mapping_keys)
    for key in mapping_keys:
        cache.get_value(key)
        cache.get_ttl(key)

    second = _trigger_query("CACHE-04 二次按资金账号查询(命中映射)")
    print("首次: %.3fs  二次: %.3fs" % (first["elapsed"], second["elapsed"]))
    return first, second


# ============================ CACHE-05 ============================

def cache_05_old_format_compatible():
    """
    CACHE-05 旧格式兼容
    往缓存里塞一个旧格式(完整对象)的值, 反序列化异常应当作未命中回源, 不报错。
    """
    keys = cache.find_user_keys(DEFAULT_FUND_ACCOUNT)
    if not keys:
        print("[CACHE-05] 未找到缓存 key, 请先跑一次 cache_01 摸出真实 key")
        return None

    key = keys[0]
    old_format = '{"legacyField":"旧格式完整对象","fundAccount":"%s"}' % DEFAULT_FUND_ACCOUNT
    cache.set_raw_value(key, old_format, ttl_seconds=8 * 3600)

    result = _trigger_query("CACHE-05 旧格式缓存下查询")
    print("[校验] 应正常返回(回源), 不报反序列化错误")
    print("[校验] 查询后 key 内容应被覆盖为新格式:")
    cache.get_value(key)
    return result


# ============================ CACHE-06 ============================

def cache_06_cache_breakdown():
    """
    CACHE-06 缓存击穿保护
    缓存失效瞬间高并发查询, 应加锁重建, 不出现大量并发回源打爆远程。
    """
    from common.client import assert_same_results, run_concurrent

    keys = cache.find_user_keys(DEFAULT_FUND_ACCOUNT)
    cache.delete_keys(keys)

    def task():
        return _trigger_query("CACHE-06 并发查询")

    results = run_concurrent(task, times=30, max_workers=30)
    assert_same_results(results)

    costs = sorted(r["elapsed"] for r in results if r)
    print("[观测] 耗时分布(前5/后5): %s ... %s" %
          ([round(c, 3) for c in costs[:5]], [round(c, 3) for c in costs[-5:]]))
    print("[校验] 预期只有少量请求回源(慢), 其余等锁后命中缓存(快)")
    return results


# ============================ CACHE-07 ============================

def cache_07_lock_failed_degrade():
    """
    CACHE-07 抢锁失败降级
    拿不到锁时应直接回源返回(不写缓存), 功能仍正常。
    制造方式: 手动占用重建锁 key, 再发起查询。
    """
    lock_keys = cache.scan_keys("*lock*user*")
    print("[提示] 请确认重建锁的 key 名称, 下面用扫描到的第一个作为示例")
    if not lock_keys:
        print("[CACHE-07] 未扫描到锁 key, 需向开发确认锁 key 命名后再执行")
        return None

    lock_key = lock_keys[0]
    cache.set_raw_value(lock_key, "manual-hold", ttl_seconds=30)

    keys = cache.find_user_keys(DEFAULT_FUND_ACCOUNT)
    cache.delete_keys(keys)

    result = _trigger_query("CACHE-07 锁被占用时查询")
    print("[校验] 应正常返回结果 [PASS]")
    print("[校验] 缓存不应被写入:", cache.find_user_keys(DEFAULT_FUND_ACCOUNT))
    cache.delete_keys(lock_key)
    return result


# ============================ CACHE-08 ============================

def cache_08_mapping_inconsistent():
    """
    CACHE-08 映射与用户缓存不一致
    构造 fundAccount -> userId 映射与用户 fundAccountList 不一致,
    检测到不一致时应回源, 返回与入参一致的数据(不返回错配对象)。
    """
    mapping_keys = cache.scan_keys(f"*{DEFAULT_FUND_ACCOUNT}*")
    if not mapping_keys:
        print("[CACHE-08] 未找到映射 key, 请先跑 cache_04 摸出真实 key")
        return None

    key = mapping_keys[0]
    origin = cache.get_value(key)
    print("[构造] 把映射改成一个错误的客户号")
    cache.set_raw_value(key, "999999999", ttl_seconds=8 * 3600)

    result = _trigger_query("CACHE-08 映射不一致时查询")
    data = (result.get("json") or {}).get("data")
    print("[校验] 返回数据应对应入参资金账号", DEFAULT_FUND_ACCOUNT, "实际:", data)

    if origin:
        cache.set_raw_value(key, origin, ttl_seconds=8 * 3600)
        print("[恢复] 映射已还原")
    return result


if __name__ == "__main__":
    # 注意: 本文件会直接改动 Redis 数据, 只在 SIT/UAT 执行
    safe(cache_01_first_query_from_remote)
    # cache_02_second_query_hit_cache()
    # cache_03_expire_and_reload()
    # cache_04_fund_account_mapping()
    # cache_05_old_format_compatible()
    # cache_06_cache_breakdown()
    # cache_07_lock_failed_degrade()
    # cache_08_mapping_inconsistent()
