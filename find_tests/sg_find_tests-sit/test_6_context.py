"""
6. 并发与上下文透传 (CTX-01 ~ CTX-03)
======================================
并行化后, 子任务里的上下文(traceId / 语言 / 白标租户)是否正确透传。

CTX-01 traceId 日志连续 : 并行子任务日志能关联到同一 traceId
CTX-02 多语言上下文透传 : 并行子任务中触发的错误信息语言与请求语言一致(X-Lang)
CTX-03 白标/多租户      : 并行查询下白标/租户上下文正确, 费用/结果与请求主体匹配
"""
import os
import sys
import uuid

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from common.client import safe, build_headers, send_query, show_fields
from common.config import (
    DEFAULT_FUND_ACCOUNT,
    NOT_EXIST_FUND_ACCOUNT,
    url_for,
)


def _combo_body(**override):
    from test_3_1_combo_option_power import _power_body
    return _power_body(**override)


# ============================ CTX-01 ============================

def ctx_01_trace_id():
    """
    CTX-01 traceId 日志连续
    用固定的 X-Request-Id 发一次请求, 然后到服务端日志按该 ID 检索,
    应能看到主线程 + 所有并行子任务的日志(三/四路查询都带同一 traceId)。
    """
    request_id = "CTX01-" + uuid.uuid4().hex[:16]
    headers = build_headers(fixed_request_id=request_id)

    result = send_query("CTX-01 固定requestId查询", url_for("consume_power"),
                        _combo_body(), headers=headers)
    show_fields(result, ["consumePurchasingPower", "purchasePower"])

    print("\n" + "=" * 60)
    print("请到服务端日志按下面的 ID 检索, 确认并行子任务日志都能关联上:")
    print("   X-Request-Id / traceId =", request_id)
    print("预期: 能看到 用户信息查询 / 购买力查询 / 行情查询 等子任务日志, 且 traceId 一致")
    print("=" * 60)
    return request_id


# ============================ CTX-02 ============================

def ctx_02_multi_language():
    """
    CTX-02 多语言上下文透传
    并行子任务中触发的错误信息语言应与请求 X-Lang 一致。
    做法: 用不存在的资金账号触发子任务内的业务异常, 分别用三种语言请求。
    """
    expects = {
        "1": "简体",
        "2": "繁體",
        "3": "English",
    }
    results = {}
    for lang, tag in expects.items():
        headers = build_headers(lang=lang)
        result = send_query(f"CTX-02 X-Lang={lang}({tag})错误文案", url_for("consume_power"),
                            _combo_body(fund_account=NOT_EXIST_FUND_ACCOUNT), headers=headers)
        msg = (result.get("json") or {}).get("msg")
        print(f"[X-Lang={lang}] msg =", msg)
        results[lang] = msg

    print("\n[校验] 三种语言的 msg 应各不相同且语言正确;")
    print("[校验] 若三者相同 -> 并行子任务未透传语言上下文, 属缺陷 [FAIL]")
    if len(set(v for v in results.values() if v)) <= 1:
        print("[结论] 疑似语言未透传 [FAIL]")
    else:
        print("[结论] 语言透传正常 [PASS]")
    return results


# ============================ CTX-03 ============================

def ctx_03_white_label():
    """
    CTX-03 白标/多租户(如适用)
    并行查询下白标/租户上下文正确, 费用/结果与请求主体匹配。
    做法: 切换 X-Type(1-友信智投 2-uSmart 3-其它), 对比同一账号同一标的的费用是否按租户区分。
    """
    results = {}
    for app_type, tag in {"1": "友信智投", "2": "uSmart", "3": "其它"}.items():
        headers = build_headers(extra={"X-Type": app_type})
        result = send_query(f"CTX-03 X-Type={app_type}({tag})", url_for("consume_power"),
                            _combo_body(fund_account=DEFAULT_FUND_ACCOUNT), headers=headers)
        data = show_fields(result, ["consumePurchasingPower", "purchasePower"])
        results[app_type] = data

    print("\n[校验] 各租户下的费用/购买力应与该租户的佣金套餐匹配;")
    print("[校验] 若环境未开启白标, 三者一致属正常, 记录后跳过即可")
    return results


if __name__ == "__main__":
    safe(ctx_01_trace_id)
    # ctx_02_multi_language()
    # ctx_03_white_label()
