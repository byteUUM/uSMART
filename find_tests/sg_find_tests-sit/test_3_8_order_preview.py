"""
3.8 下单预览(组合) (PRV-01 ~ PRV-02)
=====================================
改动点: 多腿 SHORT 复用用户信息(不再每腿都查一次远程)。

注意: 组合下单预览接口路径 png 文档未提供,
     需先向开发确认并填入 config.PATHS["combo_preview"] 后本文件才能跑通。
     在补齐前, PRV-01/02 会退化为用「计算消耗购买力」验证 deltaMargin 与多腿性能。
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from common.client import safe, check_baseline, measure, send_query, show_fields
from common.config import (
    ACCOUNT_TYPE,
    COMBO_LEGS_MULTI_SHORT,
    COMBO_STRATEGIES,
    DEFAULT_FUND_ACCOUNT,
    OPTION_MARKET,
    OPTION_MULTIPLIER,
    PATHS,
    url_for,
)

ENTRUST_PRICE = 1.5
ENTRUST_QTY = 1

PRV_FIELDS = ["deltaMargin", "consumePurchasingPower", "purchasePower", "estimateMargin"]


# ============================ 请求体构造 ============================

def _preview_body(combo_legs, combo_strategy="VERTICAL", entrust_side="B", **override):
    """组合下单预览 / 消耗购买力 请求体。"""
    body = {
        "accountType": ACCOUNT_TYPE,
        "businessType": "O",
        "comboLegs": combo_legs,
        "comboStrategy": combo_strategy,
        "currencyCode": "USD",
        "entrustPrice": ENTRUST_PRICE,
        "entrustQty": ENTRUST_QTY,
        "entrustSide": entrust_side,
        "entrustWay": "NET",
        "fundAccount": DEFAULT_FUND_ACCOUNT,
        "market": OPTION_MARKET,
        "multiplier": OPTION_MULTIPLIER,
        "price": ENTRUST_PRICE,
        "symbol": combo_legs[0]["symbol"],
    }
    body.update(override)
    return body


def _preview_url():
    """预览接口路径未配置时退化到消耗购买力接口。"""
    if PATHS.get("combo_preview"):
        return url_for("combo_preview"), "组合下单预览"
    print("[提示] config.PATHS['combo_preview'] 未配置, 本次改用「计算消耗购买力」接口验证")
    return url_for("consume_power"), "计算消耗购买力(替代预览)"


# ============================ PRV-01 ============================

def prv_01_combo_preview_delta_margin():
    """PRV-01 组合下单预览 deltaMargin —— 结果与基线一致"""
    url, tag = _preview_url()
    strategy = COMBO_STRATEGIES["牛市价差"]
    result = send_query(f"PRV-01 {tag}", url,
                        _preview_body(strategy["comboLegs"], strategy["comboStrategy"]))
    show_fields(result, PRV_FIELDS)
    check_baseline("PRV-01", result)
    return result


# ============================ PRV-02 ============================

def prv_02_multi_short_leg_performance():
    """
    PRV-02 多 SHORT 腿性能
    预览结果应正确; 用户信息在多腿间复用(远程调用次数下降, 不再每腿都查)。
    观测方式: 对比「1 条 SHORT 腿」与「3 条 SHORT 腿」的耗时增长是否近似线性。
              若已复用用户信息, 腿数增加带来的耗时增长应明显小于线性。
    """
    url, tag = _preview_url()

    one_leg = COMBO_LEGS_MULTI_SHORT[:2]     # 至少两腿才构成组合
    multi_leg = COMBO_LEGS_MULTI_SHORT       # 三条 SHORT 腿

    result = send_query(f"PRV-02 {tag}(3条SHORT腿)", url, _preview_body(multi_leg, entrust_side="S"))
    show_fields(result, PRV_FIELDS)
    check_baseline("PRV-02", result)

    print("\n[辅助观测] 腿数 vs 耗时:")
    s2 = measure("2条SHORT腿", lambda: send_query("PRV-02 2腿", url,
                                                _preview_body(one_leg, entrust_side="S"),
                                                quiet=True), times=5)
    s3 = measure("3条SHORT腿", lambda: send_query("PRV-02 3腿", url,
                                                _preview_body(multi_leg, entrust_side="S"),
                                                quiet=True), times=5)
    if s2 and s3:
        print("[校验] 耗时增幅 = %.1f%% (已复用用户信息时应远小于腿数增幅 50%%)"
              % ((s3["平均"] / s2["平均"] - 1) * 100))
    print("[校验] 请到服务端日志确认用户信息远程调用次数不再随腿数线性增长")
    return result


if __name__ == "__main__":
    safe(prv_01_combo_preview_delta_margin)
    # prv_02_multi_short_leg_performance()
