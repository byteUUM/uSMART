"""
UAT 部署后回归
==============
UAT 原为优化前版本, 合并部署后变为优化后版本, 因此可做同环境同账号的前后对比。
BASELINE_* 常量为部署前采集的快照。

比对分两类:
  错误码与行为规律  必须完全一致, 出现差异即视为回归风险
  绝对数值          允许漂移(行情与账户资金会变动), 仅输出偏差供人工判断
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from common.client import build_headers, send_query
from common.config import (COMBO_STRATEGIES, OPTION_MULTIPLIER, OPTION_SHORT_ORDER_ID,
                           STOCK_ORDER_ID, url_for)

POWER = url_for("consume_power")
NEW = url_for("order_max")
REPLACE = url_for("order_replace_max")

LEG_BUY = COMBO_STRATEGIES["牛市价差"]["comboLegs"][0]["symbol"]
LEG_SELL = COMBO_STRATEGIES["牛市价差"]["comboLegs"][1]["symbol"]
LEG_PUT = COMBO_STRATEGIES["跨式"]["comboLegs"][1]["symbol"]

# ---------------- 部署前快照 ----------------
BASELINE_SIGN = {"牛市价差": "正", "跨式": "正", "宽跨式": "正", "备兑": "正", "领式": "正"}
BASELINE_VALUE = {"牛市价差": 966.51, "跨式": 156.48, "宽跨式": 156.48,
                  "备兑": 1055.93, "领式": 578.16}
BASELINE_BEHAVIOR = {
    "组合 entrustQty": "随之变化", "组合 entrustPrice": "随之变化", "组合 策略": "随之变化",
    "组合 重复6次-牛市价差": "稳定", "组合 重复6次-备兑": "稳定", "组合 重复6次-领式": "稳定",
    "股票 entrustPrice": "递减", "股票 handQty": "按手数取整", "股票 currencyCode": "随之变化",
    "期权买入 symbol": "恒定不变", "期权买入 multiplier": "恒定不变", "期权买入 price": "随之变化",
    "期权沽空 symbol": "随之变化", "期权沽空 price": "恒定不变", "期权沽空 entrustQty": "随之变化",
    "改单股票 entrustPrice(市价单)": "恒定不变", "改单股票 handQty": "随之变化",
    "改单期权沽空 entrustPrice": "恒定不变", "改单期权沽空 entrustQty": "随之变化",
}
BASELINE_CODE = {
    "缺 businessType": 0, "缺 entrustPrice": 450003, "缺 market": 0, "缺 symbol": 100067,
    "handQty=0": 0, "handQty=-1": 0, "entrustPrice=0": 0, "entrustPrice=-1": 0,
    "symbol 不存在": 100067, "businessType 非法": 450003, "缺 accountType": 0,
    "组合 策略与腿不匹配": 450003, "组合 只1条腿": 450003, "组合 两腿相同": 450003,
    "组合 comboStrategy 非法": 450004, "组合 缺 comboStrategy": 450004,
    "组合 legRatio=0": 0, "组合 legRatio=-1": 0, "组合 legRatio=2/4": 0,
    "组合 期权代码不存在": 400064, "组合 缺 entrustQty": 450004, "组合 缺 entrustSide": 450004,
    "不传 token": 107003, "无效 token": 110002, "X-Type=1": 107005,
}
BASELINE_AVAIL = {"股票沽空": "有值", "港股00700": "有值", "OTC OTCM": "有值", "A股600519": "无值"}
BASELINE_NUM = {"股票沽空": 9998658, "港股00700": 76726600, "OTC OTCM": 9997800,
                "股票 price=100": 10001526, "改单股票": 3101288, "改单期权沽空": 5370.0}

CHANGED = []
DRIFTED = []


def call(path, body, headers=None):
    return send_query("", path, body, headers=headers, quiet=True).get("json") or {}


def field(path, body, key):
    return (call(path, body).get("data") or {}).get(key)


def compare(item, actual, expect):
    same = actual == expect
    if not same:
        CHANGED.append((item, expect, actual))
    print("  %-32s 部署前=%-12s 现在=%-12s %s" % (item, expect, actual, "OK" if same else "变化"))
    return same


def compare_num(item, actual, before):
    if not isinstance(actual, (int, float)) or not before:
        print("  %-32s 部署前=%-12s 现在=%-12s 无法比对" % (item, before, actual))
        return
    delta = (actual - before) / before * 100
    if abs(delta) > 1:
        DRIFTED.append((item, before, actual, round(delta, 2)))
    print("  %-32s 部署前=%-12s 现在=%-12s 偏差=%+.2f%%" % (item, before, actual, delta))


def stock(**kw):
    body = {"accountType": 1, "businessType": "S", "currencyCode": "USD", "entrustPrice": 100,
            "entrustSide": "B", "entrustWay": "NET", "handQty": 1, "market": "US",
            "symbol": "AAPL"}
    body.update(kw)
    return body


def option(**kw):
    body = {"accountType": 1, "businessType": "O", "currencyCode": "USD", "market": "US",
            "entrustPrice": 1.5, "price": 1.5, "entrustQty": 1, "entrustSide": "B",
            "entrustWay": "NET", "multiplier": OPTION_MULTIPLIER, "symbol": LEG_BUY}
    body.update(kw)
    return body


def combo(name="牛市价差", **kw):
    conf = COMBO_STRATEGIES[name]
    body = option(comboLegs=conf["comboLegs"], comboStrategy=conf["comboStrategy"],
                  symbol=conf["comboLegs"][0]["symbol"])
    body.update(kw)
    return body


def sweep(path, build, values, key):
    out = [field(path, build(v), key) for v in values]
    real = [v for v in out if v is not None]
    return out, len(set(map(str, real))) > 1


def section(title):
    print("\n" + "=" * 92)
    print(title)


section("一、组合策略消耗购买力")
for name in ["牛市价差", "跨式", "宽跨式", "备兑", "领式"]:
    value = field(POWER, combo(name), "consumePurchasingPower")
    sign = "正" if isinstance(value, (int, float)) and value > 0 else (
        "负" if isinstance(value, (int, float)) and value < 0 else "无值")
    compare("符号-" + name, sign, BASELINE_SIGN[name])
    compare_num("数值-" + name, value, BASELINE_VALUE[name])

section("二、组合入参是否参与计算")
for item, values, build in [
        ("组合 entrustQty", [1, 10, 36], lambda v: combo(entrustQty=v)),
        ("组合 entrustPrice", [0.5, 1.5, 50], lambda v: combo(entrustPrice=v, price=v)),
        ("组合 策略", ["牛市价差", "跨式", "领式"], lambda v: combo(v))]:
    out, changed = sweep(POWER, build, values, "consumePurchasingPower")
    print("      取值 %s" % out)
    compare(item, "随之变化" if changed else "恒定不变", BASELINE_BEHAVIOR[item])

section("三、同参数重复调用稳定性")
for name in ["牛市价差", "备兑", "领式"]:
    values = [field(POWER, combo(name), "consumePurchasingPower") for _ in range(6)]
    print("      %s" % values)
    compare("组合 重复6次-" + name, "稳定" if len(set(map(str, values))) == 1 else "波动",
            BASELINE_BEHAVIOR["组合 重复6次-" + name])

section("四、股票新单")
out, changed = sweep(NEW, lambda v: stock(entrustPrice=v), [100, 500, 2000], "maxBuyQty")
print("      %s" % out)
compare("股票 entrustPrice",
        "递减" if all(a > b for a, b in zip(out, out[1:])) else ("变化非递减" if changed else "恒定不变"),
        BASELINE_BEHAVIOR["股票 entrustPrice"])
compare_num("股票 price=100", out[0], BASELINE_NUM["股票 price=100"])

out, _ = sweep(NEW, lambda v: stock(handQty=v), [1, 10, 100], "maxBuyQty")
print("      %s" % out)
compare("股票 handQty",
        "按手数取整" if all((v or 0) % h == 0 for v, h in zip(out, [1, 10, 100])) else "未取整",
        BASELINE_BEHAVIOR["股票 handQty"])

out, changed = sweep(NEW, lambda v: stock(currencyCode=v), ["USD", "HKD", "JPY"], "maxBuyQty")
print("      %s" % out)
compare("股票 currencyCode", "随之变化" if changed else "恒定不变",
        BASELINE_BEHAVIOR["股票 currencyCode"])

section("五、期权买入")
for item, values, build in [
        ("期权买入 symbol", [LEG_BUY, LEG_SELL, LEG_PUT], lambda v: option(symbol=v)),
        ("期权买入 multiplier", [1, 100, 1000], lambda v: option(multiplier=v)),
        ("期权买入 price", [0.5, 1.5, 50], lambda v: option(entrustPrice=v, price=v))]:
    out, changed = sweep(NEW, build, values, "buyMax")
    print("      %s" % out)
    compare(item, "随之变化" if changed else "恒定不变", BASELINE_BEHAVIOR[item])

section("六、期权沽空")
for item, values, build in [
        ("期权沽空 symbol", [LEG_BUY, LEG_SELL, LEG_PUT],
         lambda v: option(businessType="OS", entrustSide="S", symbol=v)),
        ("期权沽空 price", [0.5, 1.5, 50],
         lambda v: option(businessType="OS", entrustSide="S", entrustPrice=v, price=v)),
        ("期权沽空 entrustQty", [1, 10, 30],
         lambda v: option(businessType="OS", entrustSide="S", entrustQty=v))]:
    out, changed = sweep(NEW, build, values, "expectMargin")
    print("      %s" % out)
    compare(item, "随之变化" if changed else "恒定不变", BASELINE_BEHAVIOR[item])

section("七、其他业务类型可用性")
for item, body, key in [
        ("股票沽空", stock(businessType="SHORT", entrustSide="S"), "maxSellQty"),
        ("港股00700", stock(symbol="00700", market="HK", currencyCode="HKD", handQty=100),
         "maxBuyQty"),
        ("OTC OTCM", stock(symbol="OTCM"), "maxBuyQty"),
        ("A股600519", stock(symbol="600519", market="HGT", currencyCode="CNY", handQty=100),
         "maxBuyQty")]:
    value = field(NEW, body, key)
    compare(item, "有值" if value is not None else "无值", BASELINE_AVAIL[item])
    if item in BASELINE_NUM:
        compare_num("  " + item, value, BASELINE_NUM[item])

section("八、改单接口")
if STOCK_ORDER_ID:
    out, changed = sweep(REPLACE, lambda v: {"businessType": "S", "entrustPrice": v,
                                             "entrustQty": 1, "handQty": 1,
                                             "orderId": STOCK_ORDER_ID},
                         [100, 500, 2000], "maxBuyQty")
    print("      价格扫描 %s" % out)
    compare("改单股票 entrustPrice(市价单)", "随之变化" if changed else "恒定不变",
            BASELINE_BEHAVIOR["改单股票 entrustPrice(市价单)"])
    compare_num("改单股票", out[0], BASELINE_NUM["改单股票"])

    out, changed = sweep(REPLACE, lambda v: {"businessType": "S", "entrustPrice": 100,
                                             "entrustQty": 1, "handQty": v,
                                             "orderId": STOCK_ORDER_ID},
                         [1, 10, 100], "maxBuyQty")
    print("      手数扫描 %s" % out)
    compare("改单股票 handQty", "随之变化" if changed else "恒定不变",
            BASELINE_BEHAVIOR["改单股票 handQty"])
else:
    print("  跳过: STOCK_ORDER_ID 未配置")

if OPTION_SHORT_ORDER_ID:
    out, changed = sweep(REPLACE, lambda v: {"businessType": "OS", "entrustPrice": v,
                                             "entrustQty": 1,
                                             "orderId": OPTION_SHORT_ORDER_ID},
                         [0.5, 1.5, 50], "expectMargin")
    print("      价格扫描 %s" % out)
    compare("改单期权沽空 entrustPrice", "随之变化" if changed else "恒定不变",
            BASELINE_BEHAVIOR["改单期权沽空 entrustPrice"])
    compare_num("改单期权沽空", out[0], BASELINE_NUM["改单期权沽空"])

    out, changed = sweep(REPLACE, lambda v: {"businessType": "OS", "entrustPrice": 1.5,
                                             "entrustQty": v,
                                             "orderId": OPTION_SHORT_ORDER_ID},
                         [1, 10, 30], "expectMargin")
    print("      数量扫描 %s" % out)
    compare("改单期权沽空 entrustQty", "随之变化" if changed else "恒定不变",
            BASELINE_BEHAVIOR["改单期权沽空 entrustQty"])
else:
    print("  跳过: OPTION_SHORT_ORDER_ID 未配置")

section("九、参数校验返回码")
for item, body in [
        ("缺 businessType", {k: v for k, v in stock().items() if k != "businessType"}),
        ("缺 entrustPrice", {k: v for k, v in stock().items() if k != "entrustPrice"}),
        ("缺 market", {k: v for k, v in stock().items() if k != "market"}),
        ("缺 symbol", {k: v for k, v in stock().items() if k != "symbol"}),
        ("handQty=0", stock(handQty=0)), ("handQty=-1", stock(handQty=-1)),
        ("entrustPrice=0", stock(entrustPrice=0)), ("entrustPrice=-1", stock(entrustPrice=-1)),
        ("symbol 不存在", stock(symbol="NOTEXIST999")),
        ("businessType 非法", stock(businessType="XXX")),
        ("缺 accountType", {k: v for k, v in stock().items() if k != "accountType"})]:
    compare(item, call(NEW, body).get("code"), BASELINE_CODE[item])

section("十、组合参数校验返回码")


def leg(side, symbol, ratio=1):
    return {"businessType": "O", "entrustSide": side, "legRatio": ratio, "symbol": symbol}


for item, body in [
        ("组合 策略与腿不匹配", combo(comboStrategy="COLLAR")),
        ("组合 只1条腿", combo(comboLegs=[leg("B", LEG_BUY)])),
        ("组合 两腿相同", combo(comboLegs=[leg("B", LEG_BUY), leg("B", LEG_BUY)])),
        ("组合 comboStrategy 非法", combo(comboStrategy="XXX")),
        ("组合 缺 comboStrategy", {k: v for k, v in combo().items() if k != "comboStrategy"}),
        ("组合 legRatio=0", combo(comboLegs=[leg("B", LEG_BUY, 0), leg("S", LEG_SELL, 0)])),
        ("组合 legRatio=-1", combo(comboLegs=[leg("B", LEG_BUY, -1), leg("S", LEG_SELL, 1)])),
        ("组合 legRatio=2/4", combo(comboLegs=[leg("B", LEG_BUY, 2), leg("S", LEG_SELL, 4)])),
        ("组合 期权代码不存在", combo(comboLegs=[leg("B", "QQQ990101C1000"), leg("S", LEG_SELL)])),
        ("组合 缺 entrustQty", {k: v for k, v in combo().items() if k != "entrustQty"}),
        ("组合 缺 entrustSide", {k: v for k, v in combo().items() if k != "entrustSide"})]:
    compare(item, call(POWER, body).get("code"), BASELINE_CODE[item])

section("十一、鉴权")
headers_no_token = build_headers()
headers_no_token.pop("Authorization", None)
compare("不传 token", call(NEW, stock(), headers_no_token).get("code"),
        BASELINE_CODE["不传 token"])
compare("无效 token", call(NEW, stock(), build_headers(token="INVALID_TOKEN")).get("code"),
        BASELINE_CODE["无效 token"])
compare("X-Type=1", call(NEW, stock(), build_headers(extra={"X-Type": "1"})).get("code"),
        BASELINE_CODE["X-Type=1"])

section("十二、多语言")
messages = [call(NEW, stock(symbol="NOTEXIST999"), build_headers(lang=lang)).get("msg")
            for lang in ["1", "2", "3"]]
print("      简体=%s 繁体=%s 英文=%s" % tuple(messages))
compare("多语言", "简繁相同,英文不同" if messages[0] == messages[1] != messages[2] else "其他",
        "简繁相同,英文不同")

section("回归结论")
if CHANGED:
    print("  行为或错误码变化 %d 处:" % len(CHANGED))
    for item, before, after in CHANGED:
        print("    %s: 部署前=%s 现在=%s" % (item, before, after))
else:
    print("  行为与错误码全部与部署前一致, 未发现回归")
if DRIFTED:
    print("  数值偏差超过 1%% 的 %d 处, 需结合行情与账户资金变动判断:" % len(DRIFTED))
    for item, before, after, delta in DRIFTED:
        print("    %s: %s -> %s (%+.2f%%)" % (item, before, after, delta))
