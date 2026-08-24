import requests

BASE = "https://jy-sit.usmartsg.com"
TOKEN = "eyJ0eXAiOiJKV1QiLCJhbGciOiJIUzI1NiJ9.eyJleHQiOiJNVGM0T1RZek56TTJOemcxTnciLCJsb2dpblR5cGUiOiJOT1JNQUwiLCJzZXNzaW9uIjoiMzI1MGMxNmIyYWFiNDNlNmJkNjI0NzMzYWQyM2E5ZWYiLCJleHRyYSI6IkYxWXZmTHNVeHUxZXVHZVluQWNLSjBza0tGdXpPV2FxWnF6UmFNK1ZzelVBcVFOWWkzQkhwa0pOWUIrK0FTSjhtRk5NaytxTVdRUUNNVnBuVzBUekc2NGt4V2tyVk9vMFBvNlluZXp2d0VPZUlvSVNGYWdvejZsM3VncUE2TGI0Wks4eWNTbkJTaGJGRFgwUU5hVUlCVjhCRDNSMGpOVUlTRWpOSUJLeEl0TGt0RzRSakF4MFBocm5yMkRpdE95eDdwVFYiLCJzb3VyY2UiOiJhcHAiLCJ1dWlkIjoxMjc5NTM1OTUxMjA1NDIxMDU2LCJjbGllbnRfaWQiOiI4ODcxMjE5OSJ9.ikXqE_mtUcgGNiP4iQPkxSeV0xls_UtbTXB0GbzqEFw"
HEADERS = {"Authorization": TOKEN, "X-Type": "12", "X-Dt": "t1", "X-Lang": "1"}

ORDER_ID = 1608200135293247489

VERTICAL = [{"businessType": "O", "entrustSide": "B", "legRatio": 1, "symbol": "QQQ260819C715000"},
            {"businessType": "O", "entrustSide": "S", "legRatio": 1, "symbol": "QQQ260819C725000"}]
COLLAR = [{"businessType": "S", "entrustSide": "B", "legRatio": 1, "symbol": "QQQ"},
          {"businessType": "O", "entrustSide": "B", "legRatio": 1, "symbol": "QQQ260819P715000"},
          {"businessType": "O", "entrustSide": "S", "legRatio": 1, "symbol": "QQQ260819C725000"}]


def post(path, body):
    r = requests.post(BASE + path, headers=HEADERS, json=body, timeout=30).json()
    return (r.get("data") or {}).get("consumePurchasingPower")


def replace(qty=1, price=1.5, legs=VERTICAL, strategy="VERTICAL_CALL"):
    return post("/order-center-sg/api/order/order-replace-max/v2",
                {"orderId": ORDER_ID, "entrustQty": qty, "entrustPrice": price,
                 "comboLegs": legs, "comboStrategy": strategy})

def new_order(qty):
    return post("/order-center-sg/api/order/stock-order-max-qty-get/v2",
                {"accountType": 1, "businessType": "O", "currencyCode": "USD", "market": "US",
                 "entrustPrice": 1.5, "price": 1.5, "entrustSide": "B", "entrustWay": "NET",
                 "multiplier": 100, "symbol": VERTICAL[0]["symbol"], "entrustQty": qty,
                 "comboLegs": VERTICAL, "comboStrategy": "VERTICAL_CALL"})


print("改单 order-replace-max/v2 —— 改 entrustQty")
for qty in [1, 10, 30, 36]:
    print("  entrustQty=%-4s %s" % (qty, replace(qty=qty)))

print("\n改单 —— 改 entrustPrice")
for price in [0.5, 6.21, 50]:
    print("  entrustPrice=%-6s %s" % (price, replace(price=price)))

print("\n改单 —— 改策略")
print("  VERTICAL_CALL 2腿   %s" % replace(legs=VERTICAL, strategy="VERTICAL_CALL"))
print("  COLLAR 3腿含股票腿   %s" % replace(legs=COLLAR, strategy="COLLAR"))

print("\n对照 新单 stock-order-max-qty-get/v2 —— 改 entrustQty")
for qty in [1, 10, 30, 36]:
    print("  entrustQty=%-4s %s" % (qty, new_order(qty)))
