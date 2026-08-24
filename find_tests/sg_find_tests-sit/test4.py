import requests

# 多腿组合购买力 —— 计算消耗购买力
URL = "https://jy-sit.usmartsg.com/order-center-sg/api/calculate-consumed-purchasing-power/v1"

HEADERS = {
    "Authorization": "eyJ0eXAiOiJKV1QiLCJhbGciOiJIUzI1NiJ9.eyJleHQiOiJNVGM0T1RZek56TTJOemcxTnciLCJsb2dpblR5cGUiOiJOT1JNQUwiLCJzZXNzaW9uIjoiMzI1MGMxNmIyYWFiNDNlNmJkNjI0NzMzYWQyM2E5ZWYiLCJleHRyYSI6IkYxWXZmTHNVeHUxZXVHZVluQWNLSjBza0tGdXpPV2FxWnF6UmFNK1ZzelVBcVFOWWkzQkhwa0pOWUIrK0FTSjhtRk5NaytxTVdRUUNNVnBuVzBUekc2NGt4V2tyVk9vMFBvNlluZXp2d0VPZUlvSVNGYWdvejZsM3VncUE2TGI0Wks4eWNTbkJTaGJGRFgwUU5hVUlCVjhCRDNSMGpOVUlTRWpOSUJLeEl0TGt0RzRSakF4MFBocm5yMkRpdE95eDdwVFYiLCJzb3VyY2UiOiJhcHAiLCJ1dWlkIjoxMjc5NTM1OTUxMjA1NDIxMDU2LCJjbGllbnRfaWQiOiI4ODcxMjE5OSJ9.ikXqE_mtUcgGNiP4iQPkxSeV0xls_UtbTXB0GbzqEFw",
    "X-Type": "12",            # 必须是 12, 写 1 返回 107005 非法请求
    "X-Dt": "t1",
    "X-Lang": "1",
    "Content-Type": "application/json",
}

# 期权代码格式: 标的 + 到期日(YYMMDD) + C/P + 行权价×1000(6位)
# 例: 行权价 717 -> 717000
BODY = {
    "accountType": 1,
    "businessType": "O",
    "comboStrategy": "STRADDLE",     # 跨式: 买入看跌 + 买入看涨, 同行权价
    "comboLegs": [
        {"businessType": "O", "entrustSide": "B", "legRatio": 1, "symbol": "QQQ260819C717000"},
        {"businessType": "O", "entrustSide": "B", "legRatio": 1, "symbol": "QQQ260819P717000"},
    ],
    "currencyCode": "USD",
    "entrustPrice": 5.57,
    "entrustQty": 1,
    "entrustSide": "B",
    "entrustWay": "NET",
    "market": "US",
    "multiplier": 100,
    "price": 5.57,
    "symbol": "QQQ260819C717000",
}

r = requests.post(URL, headers=HEADERS, json=BODY, timeout=30)
print(r.status_code, r.text)
