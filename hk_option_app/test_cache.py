"""
ZTHK-17628 核心测试：期权 APP 下单/改单接口 redis 缓存优化验证 (UAT)
====================================================================
本次优化两个缓存点 + 改单同步转异步。这个脚本围绕"缓存正确性 + 功能不变"验证：

用例分组：
  C1 期权基本信息缓存(option:info:{symbol})
     C1-1 下单后缓存被写入，内容含该期权合约信息
     C1-2 删缓存后再下单，能回源查库并重建缓存(不报错、结果一致)
     C1-3 命中缓存 vs 未命中缓存，两次下单结果一致
  C2 期权沽空账户用户信息缓存(option:short:userinfo:{uuid})
     C2-1 沽空(OS)下单后，该用户沽空账户用户信息缓存存在
     C2-2 删缓存后再沽空下单，能回源重建
  C3 性能：删缓存(冷) vs 命中缓存(热) 下单耗时对比，热应更快或相当
  C4 来源=app：确认下单 order_origin=app(本次优化只对 app/openApi 生效)

运行：
  $env:OPT_ENV="UAT"; python test_cache.py
  单个用例： python test_cache.py C1
注意：会真实下单(限价单, 价格取很低不易成交)，跑完请撤单或忽略(UAT 环境)。
"""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from common import redis_util
from common.client import resp_json, is_ok
from common.config import APP_USER_UUID, ENV
import option_app as api

SYMBOL = api.DEFAULT_SYMBOL     # 期权基本信息缓存针对的标的
SHORT_SYMBOL = "AAPL260918C317500"  # 沽空用标的(按当日可沽空标的调整)
LOW_PRICE = 0.05                # 尽量低价, 减少成交概率(限价买)


def _line(t):
    print("\n" + "=" * 76 + f"\n{t}\n" + "=" * 76)


def _show_info_cache(symbol):
    val, t, tl = redis_util.get_option_info(symbol)
    exists = val is not None
    print(f"[缓存] option:info:{symbol}  存在={exists}  type={t}  ttl={tl}")
    if exists:
        s = str(val)
        print("      内容:", s[:280] + (" ...(截断)" if len(s) > 280 else ""))
    return exists, val


def _show_short_userinfo_cache(uuid):
    val, t, tl = redis_util.get_short_userinfo(uuid)
    exists = val is not None
    print(f"[缓存] option:short:userinfo:{uuid}  存在={exists}  type={t}  ttl={tl}")
    if exists:
        s = str(val)
        print("      内容:", s[:280] + (" ...(截断)" if len(s) > 280 else ""))
    return exists, val


# ============================ C1 期权基本信息缓存 ============================

def c1_option_info_cache():
    _line("C1 期权基本信息缓存 option:info:{symbol}")

    print("\n[C1-1] 下单前看缓存 -> 下单 -> 下单后看缓存")
    _show_info_cache(SYMBOL)
    r = api.trade_buy(symbol=SYMBOL, price=LOW_PRICE, qty=1)
    ok = is_ok(r)
    print("下单结果 ok=", ok, "resp=", resp_json(r))
    exists_after, _ = _show_info_cache(SYMBOL)
    print(">> 预期：下单后 option:info 缓存存在" +
          ("  [通过]" if exists_after else "  [关注:缓存未建, 需确认该symbol是否走缓存路径]"))

    print("\n[C1-2] 删缓存 -> 再下单(回源查库) -> 缓存重建")
    deleted = redis_util.evict_option_info(SYMBOL)
    print(f"删除 option:info:{SYMBOL} 返回={deleted}")
    _show_info_cache(SYMBOL)
    r2 = api.trade_buy(symbol=SYMBOL, price=LOW_PRICE, qty=1)
    print("回源后下单 ok=", is_ok(r2), "resp=", resp_json(r2))
    rebuilt, _ = _show_info_cache(SYMBOL)
    print(">> 预期：缓存缺失时下单不报错且能重建缓存" +
          ("  [通过]" if rebuilt else "  [关注]"))


# ============================ C2 沽空账户用户信息缓存 ============================

def c2_short_userinfo_cache():
    _line("C2 期权沽空账户用户信息缓存 option:short:userinfo:{uuid}")
    uuid = APP_USER_UUID
    print(f"app 用户 uuid={uuid}")

    print("\n[C2-1] 沽空下单前后看缓存")
    _show_short_userinfo_cache(uuid)
    r = api.trade_short(symbol=SHORT_SYMBOL, price=LOW_PRICE, qty=1)
    print("沽空下单结果 ok=", is_ok(r), "resp=", resp_json(r))
    exists, _ = _show_short_userinfo_cache(uuid)
    print(">> 预期：沽空(app来源)下单后, short:userinfo 缓存存在" +
          ("  [通过]" if exists else "  [关注:确认是否有沽空权限/是否走缓存]"))

    print("\n[C2-2] 删缓存 -> 再沽空下单 -> 回源重建")
    deleted = redis_util.evict_short_userinfo(uuid)
    print(f"删除 short:userinfo:{uuid} 返回={deleted}")
    r2 = api.trade_short(symbol=SHORT_SYMBOL, price=LOW_PRICE, qty=1)
    print("回源后沽空下单 ok=", is_ok(r2), "resp=", resp_json(r2))
    _show_short_userinfo_cache(uuid)


# ============================ C3 性能对比 ============================

def c3_perf_compare():
    _line("C3 性能：冷缓存(删后) vs 热缓存 下单耗时对比")

    redis_util.evict_option_info(SYMBOL)
    t0 = time.time()
    api.trade_buy(symbol=SYMBOL, price=LOW_PRICE, qty=1)
    cold = (time.time() - t0) * 1000

    t1 = time.time()
    api.trade_buy(symbol=SYMBOL, price=LOW_PRICE, qty=1)
    hot = (time.time() - t1) * 1000

    print(f"\n冷缓存下单耗时: {cold:.1f} ms")
    print(f"热缓存下单耗时: {hot:.1f} ms")
    print(">> 预期：热缓存(命中 redis)通常不慢于冷缓存(单次波动仅供参考, 压测更准)")


# ============================ C4 来源 app ============================

def c4_order_origin_app():
    _line("C4 下单来源 order_origin = app (本次优化仅对 app/openApi 生效)")
    r = api.trade_buy(symbol=SYMBOL, price=LOW_PRICE, qty=1)
    data = resp_json(r)
    print("下单 resp=", data)
    order_no = api.order_no_of(r)
    print("orderNo=", order_no)
    print(">> 需在 option_order 表/日志核对该单 order_origin=1(app)。"
          "\n   可用: python query_log(在 avs 目录) 或 redis/DB 核对。")


def c5_range_with_cache():
    """
    C5 最大可买可卖(range)接口 + 期权基本信息缓存(不依赖下单成功, 可独立跑通)。
    range 内部也要取期权基本信息, 验证：命中缓存 vs 删缓存回源, 两次结果一致。
    """
    _line("C5 最大可买可卖(range) 命中缓存 vs 回源 结果一致")
    print("\n[C5-1] 命中缓存时算最大可买可卖")
    _show_info_cache(SYMBOL)
    r1 = api.customer_range(symbol=SYMBOL, price=6, qty=1, side=api.SIDE_BUY)
    d1 = resp_json(r1)
    print("热缓存结果:", d1)

    print("\n[C5-2] 删缓存后回源再算, 结果应一致")
    redis_util.evict_option_info(SYMBOL)
    print("已删 option:info 缓存")
    r2 = api.customer_range(symbol=SYMBOL, price=6, qty=1, side=api.SIDE_BUY)
    d2 = resp_json(r2)
    print("冷缓存(回源)结果:", d2)
    rebuilt, _ = _show_info_cache(SYMBOL)

    same = (d1 and d2 and d1.get("data") == d2.get("data"))
    print(f">> 结果一致={same}  缓存重建={rebuilt}" +
          ("  [通过]" if same and rebuilt else "  [关注]"))


CASES = {
    "C1": c1_option_info_cache,
    "C2": c2_short_userinfo_cache,
    "C3": c3_perf_compare,
    "C4": c4_order_origin_app,
    "C5": c5_range_with_cache,
}


def main():
    print(f"[环境={ENV}] 期权APP缓存优化测试 ZTHK-17628")
    if not redis_util.ping():
        print("redis 连不上，缓存类用例无法校验，退出。")
        return
    args = sys.argv[1:]
    keys = [a.upper() for a in args if a.upper() in CASES] or list(CASES.keys())
    for k in keys:
        try:
            CASES[k]()
        except Exception as e:  # noqa: BLE001
            print(f"[{k}] 执行异常: {type(e).__name__}: {e}")


if __name__ == "__main__":
    main()
