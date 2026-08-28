"""
公共请求客户端
==============
封装查询类用例共用的能力:
  build_headers        生成请求头(自动填充 X-Request-Id)
  app_headers          APP 网关请求头
  send_query           发送请求并输出结果
  save_baseline        将当前响应存为基线
  check_baseline       当前响应与基线逐字段比对
  expect_code          按 config.ERROR_CODES 校验错误码
  expect_no_server_error  校验未出现系统级异常
  run_concurrent       并发调用
  measure              多次调用取耗时统计

用例文件只需拼请求体并调用上述函数。
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

# Windows 控制台默认 GBK, 响应中的特殊字符会触发 UnicodeEncodeError 中断脚本。
# 保留控制台原编码以正常显示中文, 仅将无法编码的字符降级为替换字符。
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(errors="replace")
    except (AttributeError, ValueError):
        pass

# 并发场景下保证单个请求的多行输出不交错
_print_lock = threading.Lock()

# 置 True 时输出完整请求体与响应体, 用于排查
VERBOSE = False

REQUEST_TIMEOUT = 30


def build_headers(fixed_request_id: str = None, token: str = None,
                  lang: str = None, extra: dict = None) -> dict:
    """
    生成请求头。
    fixed_request_id  指定固定 X-Request-Id, 不传则每次生成 uuid
    token             指定登录 token, 不传使用默认
    lang              语言类型 1-简体 2-繁体 3-英文
    extra             需要覆盖或追加的头字段
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
    APP 网关请求头。与 build_headers 的差异:
      token 取 config.APP_AUTHORIZATION, 不回落到中台 token
      X-Channel 固定为 2(app), 中台为 1
    """
    from common.config import APP_AUTHORIZATION

    headers = build_headers(fixed_request_id=fixed_request_id,
                           token=token or APP_AUTHORIZATION,
                           lang=lang, extra=extra)
    headers["Authorization"] = token or APP_AUTHORIZATION or ""
    if not extra or "X-Channel" not in extra:
        headers["X-Channel"] = "2"
    return headers


def send_query(name: str, url: str, body: dict, headers: dict = None, quiet: bool = False):
    """
    发送查询请求。
    返回 dict: {ok, status, json, text, elapsed, request_id}
    ok 仅表示取得了 HTTP 响应, 不代表 HTTP 2xx 或业务成功。
    """
    headers = headers or build_headers()
    start = time.time()
    try:
        resp = requests.post(url, headers=headers, json=body, timeout=REQUEST_TIMEOUT)
        elapsed = time.time() - start
        try:
            data = resp.json()
        except ValueError:
            data = None
        result = {"ok": True, "status": resp.status_code, "json": data, "text": resp.text,
                  "elapsed": elapsed, "request_id": headers.get("X-Request-Id")}
    except requests.RequestException as exc:
        result = {"ok": False, "status": None, "json": None, "text": str(exc),
                  "elapsed": time.time() - start, "request_id": headers.get("X-Request-Id")}

    if not quiet:
        body_json = result["json"] or {}
        code = body_json.get("code")
        with _print_lock:
            print("%-40s HTTP=%-5s %6.3fs code=%-8s %s" % (
                name, result["status"], result["elapsed"], code, body_json.get("msg") or ""))
            if VERBOSE or (code not in (0, None) and not result["ok"]):
                print("    request_id : %s" % result["request_id"])
                print("    request    : %s" % json.dumps(body, ensure_ascii=False))
                print("    response   : %s" % result["text"])
    return result


# ============================ 基线比对(取数一致性) ============================

def _baseline_path(case: str) -> str:
    return os.path.join(BASELINE_DIR, "%s.json" % case)


def save_baseline(case: str, result: dict):
    """
    将当前响应保存为基线。
    在优化前版本执行一次, 优化后用 check_baseline 逐字段比对。
    """
    os.makedirs(BASELINE_DIR, exist_ok=True)
    with open(_baseline_path(case), "w", encoding="utf-8") as fp:
        json.dump(result.get("json"), fp, ensure_ascii=False, indent=2)
    print("基线已保存: %s" % _baseline_path(case))


def _diff(base, cur, path=""):
    """递归比对两个 JSON 结构, 返回差异描述列表。"""
    diffs = []
    if isinstance(base, dict) and isinstance(cur, dict):
        for key in sorted(set(base) | set(cur)):
            diffs += _diff(base.get(key), cur.get(key), "%s.%s" % (path, key))
    elif isinstance(base, list) and isinstance(cur, list):
        if len(base) != len(cur):
            diffs.append("%s: 长度不一致 基线=%d 当前=%d" % (path, len(base), len(cur)))
        else:
            for idx, (bval, cval) in enumerate(zip(base, cur)):
                diffs += _diff(bval, cval, "%s[%d]" % (path, idx))
    elif base != cur:
        diffs.append("%s: 基线=%r 当前=%r" % (path, base, cur))
    return diffs


def _strip(obj, ignore_keys):
    if isinstance(obj, dict):
        return {k: _strip(v, ignore_keys) for k, v in obj.items() if k not in ignore_keys}
    if isinstance(obj, list):
        return [_strip(v, ignore_keys) for v in obj]
    return obj


def check_baseline(case: str, result: dict, ignore_keys=("msg", "error")):
    """
    当前响应与基线逐字段比对, ignore_keys 中的字段不参与比较。
    无基线文件时返回 None 并跳过。
    """
    path = _baseline_path(case)
    if not os.path.exists(path):
        print("    基线缺失, 跳过比对: %s" % case)
        return None

    with open(path, encoding="utf-8") as fp:
        base = json.load(fp)

    diffs = _diff(_strip(base, ignore_keys), _strip(result.get("json"), ignore_keys))
    if diffs:
        print("    基线比对 %s: 存在 %d 处差异" % (case, len(diffs)))
        for item in diffs:
            print("      %s" % item)
        return False
    print("    基线比对 %s: 一致" % case)
    return True


# ============================ 断言 ============================

def expect_error(result: dict, keyword: str):
    """校验响应文本中包含预期的错误关键字。"""
    text = result.get("text") or ""
    hit = keyword in text
    print("    校验 命中错误 %r: %s" % (keyword, "PASS" if hit else "FAIL"))
    return hit


def expect_code(result: dict, error_key: str):
    """
    按 config.ERROR_CODES 校验错误码, 数字 code 与文案命中任一即通过。
    error_key 例: NO_CORRESPONDING_TRADE_PERMISSION
    """
    from common.config import ERROR_CODES

    if error_key not in ERROR_CODES:
        print("    校验 未知错误码 key: %s" % error_key)
        return False

    expect_num, expect_msg = ERROR_CODES[error_key]
    body = result.get("json") or {}
    actual_code = body.get("code")
    actual_msg = body.get("msg") or ""

    hit = (expect_num is not None and actual_code == expect_num) or \
          (bool(expect_msg) and expect_msg in actual_msg)
    print("    校验 %s: %s (code=%s msg=%s)" % (
        error_key, "PASS" if hit else "FAIL", actual_code, actual_msg))
    return hit


def is_no_permission(result: dict):
    """判断是否为接口无调用权限。"""
    return (result.get("json") or {}).get("code") == 110003


def expect_no_server_error(result: dict):
    """校验未出现 HTTP 500 或空指针类系统异常。"""
    text = (result.get("text") or "").upper()
    bad = result.get("status") == 500 or "NULLPOINTER" in text or "NPE" in text
    print("    校验 无系统异常: %s" % ("FAIL" if bad else "PASS"))
    return not bad


def safe(task, *args, **kwargs):
    """
    执行单个用例。遇到配置缺失或依赖未安装时输出原因并跳过, 不中断批量执行。
    """
    name = getattr(task, "__name__", str(task))
    try:
        return task(*args, **kwargs)
    except (ValueError, RuntimeError) as exc:
        print("跳过 %s: %s" % (name, exc))
        return None


def show_fields(result: dict, fields):
    """输出响应 data 中的关注字段。"""
    data = (result.get("json") or {}).get("data") or {}
    print("    字段 %s" % {k: data.get(k) for k in fields})
    return data


# ============================ 并发与性能 ============================

def run_concurrent(task, times: int = 10, max_workers: int = 10):
    """并发执行同一个无参函数 times 次, 返回结果列表。"""
    print("并发执行 %s x%d (并发数=%d)" % (getattr(task, "__name__", task), times, max_workers))
    start = time.time()
    results = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = [executor.submit(task) for _ in range(times)]
        for future in concurrent.futures.as_completed(futures):
            try:
                results.append(future.result())
            except Exception as exc:  # noqa: BLE001
                with _print_lock:
                    print("    并发任务异常: %s" % exc)
    print("并发完成, 耗时 %.2fs" % (time.time() - start))
    return results


def assert_same_results(results, ignore_keys=("msg", "error")):
    """校验一组并发响应彼此一致。"""
    bodies = [r.get("json") for r in results if r and r.get("json") is not None]
    if not bodies:
        print("    并发一致性: FAIL (无有效响应)")
        return False

    first = _strip(bodies[0], ignore_keys)
    for idx, body in enumerate(bodies[1:], start=1):
        diffs = _diff(first, _strip(body, ignore_keys))
        if diffs:
            print("    并发一致性: FAIL (第 %d 条与第 0 条不一致)" % idx)
            for item in diffs:
                print("      %s" % item)
            return False
    print("    并发一致性: PASS (%d 条响应一致)" % len(bodies))
    return True


def measure(name: str, task, times: int = 10):
    """串行调用 times 次并统计耗时。"""
    costs = [r["elapsed"] for r in (task() for _ in range(times)) if r]
    if not costs:
        print("    耗时统计 %s: 无有效样本" % name)
        return None
    stat = {"次数": len(costs), "平均": round(statistics.mean(costs), 3),
            "p50": round(statistics.median(costs), 3),
            "最大": round(max(costs), 3), "最小": round(min(costs), 3)}
    print("    耗时统计 %s: %s" % (name, stat))
    return stat
