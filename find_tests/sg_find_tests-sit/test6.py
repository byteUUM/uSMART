"""
存量问题复现(SIT 与 UAT 均一致, 非本次优化引入)
基线对比结论: 以 UAT(优化前) 为基线, 下列行为两个环境完全相同。
"""
import requests
import urllib3

urllib3.disable_warnings()

ENVS = [
    ("UAT基线", "https://jy-uat.usmartsg.com",
     "eyJ0eXAiOiJKV1QiLCJhbGciOiJIUzI1NiJ9.eyJleHQiOiJNVGM1TURJME1UYzRPREE1T1EiLCJsb2dpblR5cGUiOiJOT1JNQUwiLCJzZXNzaW9uIjoiYzc1OTMxZWQzNTM2NGJlZDk1NmRiNjk4NmYxYTY3ZDciLCJleHRyYSI6IllJbWFlYXhCVlVRQmhydlN0QmJ1aWJzUFAwSFRZME0vanlGTmFqbnhvenR2Y3Z0czd2QlhYUjd3U0ZLR2JKdWZ0emhiQ1djakZNK2NmMEtyaDQwcG1TTnlBZmM1a05maXlYMHBqRVN0QVF0ZjhCYkVrczA1WCtqcy9EMlZGME5xaFEyYi96TzFuYlcwTVhRQ2oraFMwNFVDcU9GNzQ0TEdibnhZZVZkV1I1K2NPTVVFKzhYLzhZMzlXeHovcWJENUVmND0iLCJzb3VyY2UiOiJhcHAiLCJ1dWlkIjoxMjg5Njc4MTM3MTA1MzY3MDQwLCJjbGllbnRfaWQiOiI4MzczMTc0OSJ9.QC29hNcRToaWkTFX7SWSXryEL9_LMUsSxom8tSuPV6I"),
    ("SIT优化后", "https://jy-sit.usmartsg.com",
     "eyJ0eXAiOiJKV1QiLCJhbGciOiJIUzI1NiJ9.eyJleHQiOiJNVGM0T1RZek56TTJOemcxTnciLCJsb2dpblR5cGUiOiJOT1JNQUwiLCJzZXNzaW9uIjoiMzI1MGMxNmIyYWFiNDNlNmJkNjI0NzMzYWQyM2E5ZWYiLCJleHRyYSI6IkYxWXZmTHNVeHUxZXVHZVluQWNLSjBza0tGdXpPV2FxWnF6UmFNK1ZzelVBcVFOWWkzQkhwa0pOWUIrK0FTSjhtRk5NaytxTVdRUUNNVnBuVzBUekc2NGt4V2tyVk9vMFBvNlluZXp2d0VPZUlvSVNGYWdvejZsM3VncUE2TGI0Wks4eWNTbkJTaGJGRFgwUU5hVUlCVjhCRDNSMGpOVUlTRWpOSUJLeEl0TGt0RzRSakF4MFBocm5yMkRpdE95eDdwVFYiLCJzb3VyY2UiOiJhcHAiLCJ1dWlkIjoxMjc5NTM1OTUxMjA1NDIxMDU2LCJjbGllbnRfaWQiOiI4ODcxMjE5OSJ9.ikXqE_mtUcgGNiP4iQPkxSeV0xls_UtbTXB0GbzqEFw"),
]

POWER = "/order-center-sg/api/calculate-consumed-purchasing-power/v1"
NEW = "/order-center-sg/api/order/stock-order-max-qty-get/v2"

C715, C725 = "QQQ260918C715000", "QQQ260918C725000"


def post(base, tok, path, body, key, lang="1"):
    h = {"Authorization": tok, "X-Type": "12", "X-Dt": "t1", "X-Lang": lang}
    for _ in range(3):
        try:
            r = requests.post(base + path, headers=h, json=body, timeout=30,
                              verify=False).json()
            return (r.get("data") or {}).get(key), r.get("code"), r.get("msg")
        except requests.RequestException:
            continue
    return None, "网络失败", None


def opt(**kw):
    b = {"accountType": 1, "businessType": "O", "currencyCode": "USD", "market": "US",
         "entrustPrice": 1.5, "price": 1.5, "entrustQty": 1, "entrustSide": "B",
         "entrustWay": "NET", "multiplier": 100, "symbol": C715}
    b.update(kw)
    return b


def combo(**kw):
    leg = lambda s, sym: {"businessType": "O", "entrustSide": s, "legRatio": 1, "symbol": sym}
    b = opt(comboLegs=[leg("B", C715), leg("S", C725)], comboStrategy="VERTICAL_CALL")
    b.update(kw)
    return b


print("问题1: 期权最大可买 buyMax 不受期权代码与合约乘数影响(只随委托价变)")
for env, base, tok in ENVS:
    print("  --- %s" % env)
    for sym in [C715, C725, "QQQ260918P710000", "AAPL260918C230000"]:
        print("      symbol=%-20s buyMax=%s" % (sym, post(base, tok, NEW, opt(symbol=sym), "buyMax")[0]))
    for m in [1, 100, 1000]:
        print("      multiplier=%-16s buyMax=%s" % (m, post(base, tok, NEW, opt(multiplier=m), "buyMax")[0]))

print("\n问题2: 组合腿比例 legRatio 传 0 与负数未被拦截, 仍返回 code=0 且参与计算")
for env, base, tok in ENVS:
    print("  --- %s" % env)
    leg = lambda s, sym, r: {"businessType": "O", "entrustSide": s, "legRatio": r, "symbol": sym}
    for r1, r2 in [(1, 1), (0, 0), (-1, 1), (2, 4)]:
        v, code, _ = post(base, tok, POWER,
                          combo(comboLegs=[leg("B", C715, r1), leg("S", C725, r2)]),
                          "consumePurchasingPower")
        print("      legRatio=%-6s code=%-6s consumePurchasingPower=%s" % ("%s/%s" % (r1, r2), code, v))

print("\n问题3: 简体与繁体错误文案相同(X-Lang 1 与 2 无区别)")
stock = {"accountType": 1, "businessType": "S", "currencyCode": "USD", "entrustPrice": 100,
         "entrustSide": "B", "entrustWay": "NET", "handQty": 1, "market": "US",
         "symbol": "NOTEXIST999"}
for env, base, tok in ENVS:
    msgs = [post(base, tok, NEW, stock, "maxBuyQty", lang=lg)[2] for lg in ["1", "2", "3"]]
    print("  %-10s 简体=%s 繁体=%s 英文=%s" % (env, msgs[0], msgs[1], msgs[2]))

print("\n问题4: 部分必填字段缺失仍返回 code=0(businessType / market / handQty=0)")
for env, base, tok in ENVS:
    print("  --- %s" % env)
    base_body = dict(stock, symbol="AAPL")
    for tag, b in [("缺 businessType", {k: v for k, v in base_body.items() if k != "businessType"}),
                   ("缺 market", {k: v for k, v in base_body.items() if k != "market"}),
                   ("handQty=0", dict(base_body, handQty=0)),
                   ("entrustPrice=0", dict(base_body, entrustPrice=0))]:
        v, code, msg = post(base, tok, NEW, b, "maxBuyQty")
        print("      %-16s code=%-6s maxBuyQty=%s" % (tag, code, v))
