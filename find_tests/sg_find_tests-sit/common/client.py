"""
公共请求客户端模块
==================
封装所有查询用例共用的能力:
  - build_headers   : 生成请求头(自动填充 X-Request-Id)
  - send_query      : 发送单个查询请求并打印结果
  - save_baseline   : 把当前响应存为"优化前基线"
  - check_baseline  : 当前响应与基线逐字段比对(取数一致性验证的核心)
  - expect_error    : 校验是否返回了预期的错误码/文案
  - run_concurrent  : 并发调用工具
  - measure         : 多次调用取耗时(性能验证用)

各用例文件只需 import 这几个函数，专注于"拼请求体"即可。
"""
import concurrent.futures
import json
import os
import statistics
import sys
import threading
import time
import uuid

import requests

from common.config import AUTHORIZATION, BASELINE_DIR, COMMON_HEADERS

# Windows 控制台默认 GBK，服务端响应里的特殊字符会导致 UnicodeEncodeError 直接中断脚本。
# 这里保留控制台原编码(中文才能正常显示)，只把"编码不了的字符"降级为替换字符，不再抛异常。
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(errors="replace")
    except (AttributeError, ValueError):
        pass

# 打印锁: 并发时保证单个请求的多行输出不会互相交错
_print_lock = threading.Lock()


def build_headers(fixed_request_id: str = None, token: str = None,
                  lang: str = None, extra: dict = None) -> dict:
    """
    生成请求头。
    fixed_request_id: 若传入则使用固定的 X-Request-Id，否则每次自动生成 uuid。
    token:            指定登录 token(切换账号时用)，不传用默认。
    lang:             语言 1-简体 2-繁体 3-英文(多语言用例用)。
    extra:            需要额外覆盖/追加的头字段。
    """
    headers = COMMON_HEADERS.copy()
    headers["X-Request-Id"] = fixed_request_id or str(uuid.uuid4())
    headers["Authorization"] = token or AUTHORIZATION
    if lang:
        headers["X-Lang"] = lang
    if extra:
        headers.update(extra)
    return headers


def app_headers(fixed_request_id: str = None, token: str = None,
                lang: str = None, extra: dict = None) -> dict:
    """
    APP 网关请求头(png2 那三个接口用)。与 build_headers 的差别:
      - token 用 config.APP_AUTHORIZATION, **不回落到中台 AUTHORIZATION**
        (实测中台 token 打到 APP 网关会返回 107005「非法请求」, 是误导性的响应;
         留空反而会明确返回 107003「Token 不能为空」, 便于识别是缺 token)
      - X-Channel 固定为 2(app), 中台是 1
    参数与 build_headers 一致, 可直接替换。
    """
    from common.config import APP_AUTHORIZATION

    headers = build_headers(fixed_request_id=fixed_request_id,
                           token=token or APP_AUTHORIZATION,
                           lang=lang, extra=extra)
    headers["Authorization"] = token or APP_AUTHORIZATION or ""
    if not extra or "X-Channel" not in extra:
        headers["X-Channel"] = "2"

    if not headers["Authorization"] and not _APP_TOKEN_WARNED:
        _warn_app_token_missing()
    return headers


_APP_TOKEN_WARNED = False


def _warn_app_token_missing():
    global _APP_TOKEN_WARNED
    _APP_TOKEN_WARNED = True
    print("[提示] config.APP_AUTHORIZATION 未配置, APP 网关接口会返回 107003「Token 不能为空」。"
          "拿到 APP 网关 token 后填入即可。")


def send_query(name: str, url: str, body: dict, headers: dict = None, quiet: bool = False):
    """
    发送单个查询请求并打印结果。
    返回 dict: {"ok", "status", "json", "elapsed", "request_id"}
    """
    headers = headers or build_headers()
    start = time.time()
    try:
        resp = requests.post(url, headers=headers, json=body, timeout=30)
        elapsed = time.time() - start
        try:
            data = resp.json()
        except ValueError:
            data = None
        result = {
            "ok": True,
            "status": resp.status_code,
            "json": data,
            "text": resp.text,
            "elapsed": elapsed,
            "request_id": headers.get("X-Request-Id"),
        }
    except requests.RequestException as e:
        elapsed = time.time() - start
        result = {
            "ok": False,
            "status": None,
            "json": None,
            "text": str(e),
            "elapsed": elapsed,
            "request_id": headers.get("X-Request-Id"),
        }

    if not quiet:
        with _print_lock:
            print(f"\n===== {name} =====")
            print("request_id:", result["request_id"])
            print("URL       :", url)
            print("请求体    :", json.dumps(body, ensure_ascii=False))
            print("状态码    :", result["status"])
            print("耗时      : %.3fs" % result["elapsed"])
            print("响应内容  :", result["text"])
    return result


# ============================ 基线对比(取数一致性) ============================

def _baseline_path(case: str) -> str:
    return os.path.join(BASELINE_DIR, f"{case}.json")


def save_baseline(case: str, result: dict):
    """
    把当前响应保存为基线。
    用法: 在优化前的版本(master)上跑一遍用例并调用本函数，
         优化后再跑同一批用例用 check_baseline 比对。
    """
    os.makedirs(BASELINE_DIR, exist_ok=True)
    with open(_baseline_path(case), "w", encoding="utf-8") as f:
        json.dump(result.get("json"), f, ensure_ascii=False, indent=2)
    print(f"[基线] 已保存 {case} -> {_baseline_path(case)}")


def _diff(base, cur, path=""):
    """递归比对两个 JSON 结构，返回差异描述列表。"""
    diffs = []
    if isinstance(base, dict) and isinstance(cur, dict):
        for key in sorted(set(base) | set(cur)):
            diffs += _diff(base.get(key), cur.get(key), f"{path}.{key}")
    elif isinstance(base, list) and isinstance(cur, list):
        if len(base) != len(cur):
            diffs.append(f"{path}: 长度不一致 基线={len(base)} 当前={len(cur)}")
        else:
            for i, (b, c) in enumerate(zip(base, cur)):
                diffs += _diff(b, c, f"{path}[{i}]")
    elif base != cur:
        diffs.append(f"{path}: 基线={base!r} 当前={cur!r}")
    return diffs


def check_baseline(case: str, result: dict, ignore_keys=("msg", "error")):
    """
    当前响应与基线逐字段比对。ignore_keys 里的字段不参与比较。
    没有基线文件时只提示，不算失败。
    """
    path = _baseline_path(case)
    if not os.path.exists(path):
        print(f"[基线] {case} 无基线文件，跳过比对(先在优化前版本执行 save_baseline)")
        return None

    with open(path, encoding="utf-8") as f:
        base = json.load(f)

    def strip(obj):
        if isinstance(obj, dict):
            return {k: strip(v) for k, v in obj.items() if k not in ignore_keys}
        if isinstance(obj, list):
            return [strip(v) for v in obj]
        return obj

    diffs = _diff(strip(base), strip(result.get("json")))
    if diffs:
        print(f"[基线] {case} 与基线存在 {len(diffs)} 处差异:")
        for d in diffs:
            print("   -", d)
        return False
    print(f"[基线] {case} 与基线完全一致 [PASS]")
    return True


# ============================ 断言小工具 ============================

def expect_error(result: dict, keyword: str):
    """校验响应中包含预期的错误码/文案关键字(如 无对应交易权限)。"""
    text = result.get("text") or ""
    if keyword in text:
        print(f"[校验] 命中预期错误 '{keyword}' [PASS]")
        return True
    print(f"[校验] 未命中预期错误 '{keyword}' [FAIL]  实际: {text}")
    return False


def expect_code(result: dict, error_key: str):
    """
    按 config.ERROR_CODES 里的实测错误码校验(推荐用法)。
    error_key 例: "NO_CORRESPONDING_TRADE_PERMISSION"
    数字 code 与中文文案命中任一即算通过。
    """
    from common.config import ERROR_CODES

    if error_key not in ERROR_CODES:
        print(f"[校验] 未知错误码 key: {error_key}")
        return False

    expect_code_num, expect_msg = ERROR_CODES[error_key]
    body = result.get("json") or {}
    actual_code = body.get("code")
    actual_msg = body.get("msg") or ""

    hit_code = expect_code_num is not None and actual_code == expect_code_num
    hit_msg = bool(expect_msg) and expect_msg in actual_msg

    if hit_code or hit_msg:
        print(f"[校验] 命中预期错误 {error_key} (code={actual_code}, msg={actual_msg}) [PASS]")
        return True
    print(f"[校验] 未命中 {error_key} (期望 code={expect_code_num} / msg含'{expect_msg}') [FAIL]")
    print(f"       实际 code={actual_code}, msg={actual_msg}")
    return False


def is_no_permission(result: dict):
    """判断是否命中 110003「您无权限,请申请」——当前 token/账号无该接口权限。"""
    body = result.get("json") or {}
    if body.get("code") == 110003:
        print("[环境] 110003 无此接口权限, 跳过后续断言")
        return True
    return False


# 兼容旧名字
is_path_not_matched = is_no_permission
is_api_forbidden = is_no_permission


def expect_no_server_error(result: dict):
    """校验没有出现 500 / NPE 这类系统异常。"""
    text = (result.get("text") or "").upper()
    bad = result.get("status") == 500 or "NULLPOINTER" in text or "NPE" in text
    if bad:
        print("[校验] 出现系统异常(500/NPE) [FAIL]")
        return False
    print("[校验] 无系统异常 [PASS]")
    return True



def safe(task, *args, **kwargs):
    """
    执行一个用例；遇到"接口路径待确认/配置缺失/依赖未安装"时打印提示并跳过，
    不抛 traceback。用于 run_all() 里批量跑用例。
    """
    name = getattr(task, "__name__", str(task))
    try:
        return task(*args, **kwargs)
    except (ValueError, RuntimeError) as e:
        # ValueError  : 接口路径未配置 / 配置缺失
        # RuntimeError: 依赖未安装(如 redis / pika)
        print(f"\n[跳过] {name}: {e}")
        return None


def show_fields(result: dict, fields):
    """打印响应 data 中关注的字段，便于人工核对。"""
    data = (result.get("json") or {}).get("data") or {}
    print("[关注字段]", {k: data.get(k) for k in fields})
    return data


# ============================ 并发 & 性能工具 ============================

def run_concurrent(task, times: int = 10, max_workers: int = 10):
    """并发执行同一个无参查询函数 times 次，返回结果列表。"""
    name = getattr(task, "__name__", str(task))
    print(f"\n########## 开始并发: {name} x{times} (并发数={max_workers}) ##########")
    start = time.time()
    results = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = [executor.submit(task) for _ in range(times)]
        for f in concurrent.futures.as_completed(futures):
            try:
                results.append(f.result())
            except Exception as e:  # noqa: BLE001
                with _print_lock:
                    print("并发任务异常:", e)
    print(f"########## 并发结束, 耗时 {time.time() - start:.2f}s ##########")
    return results


def assert_same_results(results, ignore_keys=("msg", "error")):
    """校验一组并发响应结果彼此一致(用于高频并发一致性验证)。"""
    bodies = [r.get("json") for r in results if r and r.get("json") is not None]
    if not bodies:
        print("[并发一致性] 无有效响应 [FAIL]")
        return False

    def strip(obj):
        if isinstance(obj, dict):
            return {k: strip(v) for k, v in obj.items() if k not in ignore_keys}
        if isinstance(obj, list):
            return [strip(v) for v in obj]
        return obj

    first = strip(bodies[0])
    for i, b in enumerate(bodies[1:], start=1):
        diffs = _diff(first, strip(b))
        if diffs:
            print(f"[并发一致性] 第 {i} 条与第 0 条不一致 [FAIL]")
            for d in diffs:
                print("   -", d)
            return False
    print(f"[并发一致性] {len(bodies)} 条响应完全一致 [PASS]")
    return True


def measure(name: str, task, times: int = 10):
    """串行调用 times 次，统计耗时(avg/p50/max)，用于性能对比。"""
    costs = []
    for _ in range(times):
        r = task()
        if r:
            costs.append(r["elapsed"])
    if not costs:
        print(f"[性能] {name} 无有效样本")
        return None
    stat = {
        "次数": len(costs),
        "平均": round(statistics.mean(costs), 3),
        "p50": round(statistics.median(costs), 3),
        "最大": round(max(costs), 3),
        "最小": round(min(costs), 3),
    }
    print(f"[性能] {name} -> {stat}")
    return stat
