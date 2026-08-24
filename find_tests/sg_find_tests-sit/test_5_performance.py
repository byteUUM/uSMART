"""
5. 性能验证 (PERF-01 ~ PERF-04)
================================
观测点:
  PERF-01 各查询接口响应时间较优化前明显下降(并行 + 缓存 + 批量取价)
  PERF-02 用户信息缓存命中率达到预期, 远程调用量下降
  PERF-03 并发查询线程池 order.thread-pool.concurrent-query
          (默认 core=20 / max=40 / queue=500) 在峰值 QPS 下是否成为瓶颈
  PERF-04 峰值稳定性: 无线程耗尽、无请求堆积导致的超时雪崩

用法:
  1. 优化前(master)执行 perf_01_all_apis(), 把打印的统计结果记下来做基线
  2. 优化后再执行一次, 逐接口对比平均/p50/最大耗时
"""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from common.client import safe, measure, run_concurrent, send_query
from common.config import DEFAULT_FUND_ACCOUNT, url_for

# 各接口的无参调用函数(复用各章节已写好的请求体构造)
def _combo_power():
    from test_3_1_combo_option_power import _power_body
    return send_query("组合购买力", url_for("consume_power"), _power_body(), quiet=True)


def _stock_max():
    from test_3_3_stock_max import _max_body
    return send_query("股票最大可买", url_for("order_max"), _max_body(), quiet=True)


def _short_max():
    from test_3_2_stock_short_max import _short_max_body
    return send_query("沽空最大可买可卖", url_for("short_max"), _short_max_body(), quiet=True)


def _option_short_max():
    from test_3_4_option_short_max import _sell_max_body
    return send_query("期权沽空最大可卖", url_for("option_short_max"),
                      _sell_max_body(DEFAULT_FUND_ACCOUNT), quiet=True)


ALL_APIS = {
    "组合期权购买力": _combo_power,
    "股票最大可买可卖": _stock_max,
    "股票沽空最大可买可卖": _short_max,
    "期权沽空最大可卖": _option_short_max,
}


# ============================ PERF-01 ============================

def perf_01_all_apis(times=20):
    """PERF-01 各查询接口响应时间 —— 优化后应明显下降"""
    print("\n########## PERF-01 各接口响应时间 ##########")
    stats = {}
    for name, task in ALL_APIS.items():
        stats[name] = measure(name, task, times=times)
    print("\n---- 汇总(与优化前基线逐项对比) ----")
    for name, stat in stats.items():
        print(f"  {name}: {stat}")
    return stats


# ============================ PERF-02 ============================

def perf_02_cache_hit_rate(times=20):
    """
    PERF-02 缓存命中率
    做法: 先清缓存跑一次(全回源), 再连续跑 N 次(应命中缓存),
         用「首次耗时 vs 后续平均耗时」间接反映命中效果。
         精确命中率请看服务端监控/远程调用量。
    """
    from common import cache

    print("\n########## PERF-02 缓存命中效果 ##########")
    cache.delete_keys(cache.find_user_keys(DEFAULT_FUND_ACCOUNT))

    first = _combo_power()
    print("清缓存后首次(回源)耗时: %.3fs" % first["elapsed"])

    stat = measure("命中缓存后", _combo_power, times=times)
    if stat:
        print("[校验] 首次 %.3fs -> 后续平均 %.3fs, 降幅 %.1f%%"
              % (first["elapsed"], stat["平均"],
                 (1 - stat["平均"] / first["elapsed"]) * 100))
    print("[校验] 请同时到服务端监控确认: 用户信息远程调用量明显下降")
    return stat


# ============================ PERF-03 ============================

def perf_03_thread_pool(concurrency=60, total=300):
    """
    PERF-03 并发查询线程池
    线程池 order.thread-pool.concurrent-query 默认 core=20 / max=40 / queue=500。
    这里用超过 max(40) 的并发压一轮, 观察是否丢任务/抛拒绝异常/延迟不可接受。
    """
    print(f"\n########## PERF-03 线程池压测 (并发={concurrency}, 总量={total}) ##########")
    results = run_concurrent(_combo_power, times=total, max_workers=concurrency)

    ok = [r for r in results if r and r["status"] == 200]
    fail = [r for r in results if not r or r["status"] != 200]
    costs = sorted(r["elapsed"] for r in ok)

    print(f"成功: {len(ok)}  失败: {len(fail)}")
    if costs:
        p95 = costs[int(len(costs) * 0.95) - 1]
        print("耗时 平均=%.3fs p50=%.3fs p95=%.3fs 最大=%.3fs"
              % (sum(costs) / len(costs), costs[len(costs) // 2], p95, costs[-1]))
    for r in fail[:5]:
        print("失败样本:", (r or {}).get("text"))
    print("[校验] 不应出现 RejectedExecutionException / 任务丢失 / 超时")
    print("[校验] 若 p95 明显劣化, 说明线程池(core=20/max=40/queue=500)已成瓶颈, 需调参")
    return results


# ============================ PERF-04 ============================

def perf_04_peak_stability(duration_sec=300, concurrency=40):
    """
    PERF-04 峰值稳定性
    持续高峰下无线程耗尽、无请求堆积导致的超时雪崩。
    做法: 持续 duration_sec 秒不断施压, 分段打印成功率与耗时趋势。
    """
    print(f"\n########## PERF-04 持续压测 {duration_sec}s (并发={concurrency}) ##########")
    start = time.time()
    round_no = 0
    while time.time() - start < duration_sec:
        round_no += 1
        results = run_concurrent(_combo_power, times=concurrency * 2, max_workers=concurrency)
        ok = [r for r in results if r and r["status"] == 200]
        costs = [r["elapsed"] for r in ok]
        avg = sum(costs) / len(costs) if costs else 0
        print("第 %d 轮 | 已跑 %.0fs | 成功率 %d/%d | 平均耗时 %.3fs"
              % (round_no, time.time() - start, len(ok), len(results), avg))
    print("[校验] 各轮成功率应稳定, 平均耗时不应随时间持续攀升(无堆积雪崩)")


if __name__ == "__main__":
    safe(perf_01_all_apis)
    # perf_02_cache_hit_rate()
    # perf_03_thread_pool()
    # perf_04_peak_stability(duration_sec=120)
