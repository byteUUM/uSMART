import json

import requests

BASE = "https://jy-sit.usmartsg.com"
TOKEN = "eyJ0eXAiOiJKV1QiLCJhbGciOiJIUzI1NiJ9.eyJleHQiOiJNVGM0T1RZek56TTJOemcxTnciLCJsb2dpblR5cGUiOiJOT1JNQUwiLCJzZXNzaW9uIjoiMzI1MGMxNmIyYWFiNDNlNmJkNjI0NzMzYWQyM2E5ZWYiLCJleHRyYSI6IkYxWXZmTHNVeHUxZXVHZVluQWNLSjBza0tGdXpPV2FxWnF6UmFNK1ZzelVBcVFOWWkzQkhwa0pOWUIrK0FTSjhtRk5NaytxTVdRUUNNVnBuVzBUekc2NGt4V2tyVk9vMFBvNlluZXp2d0VPZUlvSVNGYWdvejZsM3VncUE2TGI0Wks4eWNTbkJTaGJGRFgwUU5hVUlCVjhCRDNSMGpOVUlTRWpOSUJLeEl0TGt0RzRSakF4MFBocm5yMkRpdE95eDdwVFYiLCJzb3VyY2UiOiJhcHAiLCJ1dWlkIjoxMjc5NTM1OTUxMjA1NDIxMDU2LCJjbGllbnRfaWQiOiI4ODcxMjE5OSJ9.ikXqE_mtUcgGNiP4iQPkxSeV0xls_UtbTXB0GbzqEFw"
H = {"Authorization": TOKEN, "X-Type": "12", "X-Dt": "t1", "X-Lang": "1"}

POWER = "/order-center-sg/api/calculate-consumed-purchasing-power/v1"
REPLACE = "/order-center-sg/api/order/order-replace-max/v2"
NEW = "/order-center-sg/api/order/stock-order-max-qty-get/v2"

CASES = [
    ("组合费用符号反-备兑 价格1.5 应为正数", POWER, "consumePurchasingPower",
     {"accountType": 1, "businessType": "O", "currencyCode": "USD", "market": "US",
      "entrustPrice": 1.5, "price": 1.5, "entrustQty": 1, "entrustSide": "B",
      "entrustWay": "NET", "multiplier": 100, "symbol": "QQQ",
      "comboStrategy": "COVERED_CALL",
      "comboLegs": [{"businessType": "S", "entrustSide": "B", "legRatio": 1, "symbol": "QQQ"},
                    {"businessType": "O", "entrustSide": "S", "legRatio": 1, "symbol": "QQQ260819C717000"}]}),

    ("组合费用符号反-对照 牛市价差 价格1.5", POWER, "consumePurchasingPower",
     {"accountType": 1, "businessType": "O", "currencyCode": "USD", "market": "US",
      "entrustPrice": 1.5, "price": 1.5, "entrustQty": 1, "entrustSide": "B",
      "entrustWay": "NET", "multiplier": 100, "symbol": "QQQ260819C715000",
      "comboStrategy": "VERTICAL_CALL",
      "comboLegs": [{"businessType": "O", "entrustSide": "B", "legRatio": 1, "symbol": "QQQ260819C715000"},
                    {"businessType": "O", "entrustSide": "S", "legRatio": 1, "symbol": "QQQ260819C725000"}]}),

    ("股票改单价格不生效 price=100", REPLACE, "maxBuyQty",
     {"businessType": "S", "entrustPrice": 100, "entrustQty": 1, "handQty": 1,
      "orderId": 1608223107248807936}),

    ("股票改单价格不生效 price=2000", REPLACE, "maxBuyQty",
     {"businessType": "S", "entrustPrice": 2000, "entrustQty": 1, "handQty": 1,
      "orderId": 1608223107248807936}),

    ("期权沽空改单价格不生效 price=0.5", REPLACE, "expectMargin",
     {"businessType": "OS", "entrustPrice": 0.5, "entrustQty": 1,
      "orderId": 1608213092622376961}),

    ("期权沽空改单价格不生效 price=50", REPLACE, "expectMargin",
     {"businessType": "OS", "entrustPrice": 50, "entrustQty": 1,
      "orderId": 1608213092622376961}),

    ("期权最大可买不看代码 QQQ260819C715000", NEW, "buyMax",
     {"accountType": 1, "businessType": "O", "currencyCode": "USD", "market": "US",
      "entrustPrice": 1.5, "price": 1.5, "entrustQty": 1, "entrustSide": "B",
      "entrustWay": "NET", "multiplier": 100, "symbol": "QQQ260819C715000"}),

    ("期权最大可买不看代码 AAPL260918C230000", NEW, "buyMax",
     {"accountType": 1, "businessType": "O", "currencyCode": "USD", "market": "US",
      "entrustPrice": 1.5, "price": 1.5, "entrustQty": 1, "entrustSide": "B",
      "entrustWay": "NET", "multiplier": 100, "symbol": "AAPL260918C230000"}),

    ("期权最大可买不看乘数 multiplier=1", NEW, "buyMax",
     {"accountType": 1, "businessType": "O", "currencyCode": "USD", "market": "US",
      "entrustPrice": 1.5, "price": 1.5, "entrustQty": 1, "entrustSide": "B",
      "entrustWay": "NET", "multiplier": 1, "symbol": "QQQ260819C715000"}),
]

for name, path, key, body in CASES:
    r = requests.post(BASE + path, headers=H, json=body, timeout=30).json()
    print("\n%s\nPOST %s\n%s\n%s = %s" % (
        name, BASE + path, json.dumps(body, ensure_ascii=False),
        key, (r.get("data") or {}).get(key)))
