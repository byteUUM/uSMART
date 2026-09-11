"""
冒烟自检：验证 config / kibana / redis / app 接口鉴权 是否可用。
用法:
  SIT: python smoke_test.py
  UAT: $env:OPT_ENV="UAT"; python smoke_test.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from common import config
from common.client import send, resp_json, build_headers
from common.config import url_for, SIDE_BUY, ORDER_TYPE_LIMIT, BUSINESS_TYPE_OPTION


def check_env():
    print("=" * 70)
    print(config.env_summary())
    print("=" * 70)


def check_kibana():
    print("\n---- Kibana 日志连通性 ----")
    try:
        from common.kibana import search
        rows = search("option-trade", size=3)
        print(f"最近日志命中 {len(rows)} 条 (option-trade)")
        return True
    except Exception as e:  # noqa: BLE001
        print("Kibana 查询失败:", type(e).__name__, e)
        return False


def check_redis():
    print("\n---- Redis 连通性 + 扫期权缓存 key ----")
    try:
        from common import redis_util
        if not redis_util.ping():
            return False
        keys = redis_util.scan_keys(limit=30)
        print(f"扫到期权前缀 key {len(keys)} 个(前 30):")
        for k in keys[:30]:
            print("   ", k)
        return True
    except Exception as e:  # noqa: BLE001
        print("Redis 失败:", type(e).__name__, e)
        return False


def check_app_auth():
    """用当前 token 打一个 app 端最大可买接口，看鉴权是否通过。"""
    print("\n---- APP 接口鉴权探测 (option-customer-buy-max) ----")
    resp = send("APP最大可买探测", url_for("option_customer_buy_max"), {"price": 1})
    data = resp_json(resp)
    if data is None:
        print(">> 无有效响应")
        return False
    code = data.get("code")
    msg = data.get("msg")
    print(f">> code={code}, msg={msg}")
    if code in (110003,) or (msg and ("无权限" in str(msg) or "登录" in str(msg) or "token" in str(msg).lower())):
        print(">> 鉴权未通过：需要有效的 APP 端 token，请更新 config.AUTHORIZATION")
        return False
    print(">> 鉴权疑似通过(非无权限错误)")
    return True


if __name__ == "__main__":
    check_env()
    ok_k = check_kibana()
    ok_r = check_redis()
    ok_a = check_app_auth()
    print("\n==== 自检结果 ====")
    print(f"Kibana: {'OK' if ok_k else 'FAIL'}")
    print(f"Redis : {'OK' if ok_r else 'FAIL'}")
    print(f"APP鉴权: {'OK' if ok_a else 'FAIL(需换token)'}")
