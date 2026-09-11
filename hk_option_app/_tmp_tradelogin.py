import sys, uuid
sys.path.insert(0, '.')
import requests
from common.config import COMMON_HEADERS, BASE_URL

PATH = "/user-server/api/trade-login/v1"
# GET + 去掉 Content-Type。交易密码 123456。
param_sets = [
    {"tradePassword": "123456"},
    {"password": "123456"},
    {"tradePwd": "123456"},
    {"pwd": "123456"},
]
for params in param_sets:
    h = {k: v for k, v in COMMON_HEADERS.items() if k != "Content-Type"}
    h["X-Request-Id"] = str(uuid.uuid4())
    try:
        r = requests.get(BASE_URL + PATH, headers=h, params=params, timeout=12)
        print(f"GET params={params}\n   -> {r.status_code} {(r.text or '')[:220]}\n")
    except Exception as e:
        print(f"GET params={params} -> ERR {type(e).__name__}: {str(e)[:80]}\n")
