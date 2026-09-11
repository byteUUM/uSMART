"""
HK 期权 APP 端 —— 请求客户端
============================
封装请求头生成、发请求、并发压测。业务脚本只管拼 body。
"""
import concurrent.futures
import threading
import time
import uuid

import requests

from common.config import COMMON_HEADERS

_print_lock = threading.Lock()


def new_request_id() -> str:
    return str(uuid.uuid4())


def build_headers(fixed_request_id: str = None, extra: dict = None) -> dict:
    headers = COMMON_HEADERS.copy()
    headers["X-Request-Id"] = fixed_request_id or str(uuid.uuid4())
    if extra:
        headers.update(extra)
    return headers


def send(name: str, url: str, body: dict, headers: dict = None, silent: bool = False,
         timeout: int = 30):
    """发送单个请求。返回 requests.Response(失败返回 None)。"""
    headers = headers or build_headers()
    if not silent:
        print(f"\n===== {name} =====")
        print("X-Request-Id:", headers.get("X-Request-Id"))
        print("URL         :", url)
        print("请求体      :", body)
    try:
        resp = requests.post(url, headers=headers, json=body, timeout=timeout)
        if not silent:
            print("状态码      :", resp.status_code)
            print("响应内容    :", resp.text)
        return resp
    except requests.RequestException as e:
        if not silent:
            print("请求异常    :", e)
        return None


def resp_json(resp):
    if resp is None:
        return None
    try:
        return resp.json()
    except ValueError:
        return None


def is_ok(resp) -> bool:
    """业务成功: HTTP 200 且 body.code == 0。"""
    data = resp_json(resp)
    return bool(data) and data.get("code") == 0


def data_of(resp):
    data = resp_json(resp)
    return data.get("data") if data else None


# ---- 计时 ----
def timed(name, func, *args, **kw):
    """执行 func 并打印耗时(ms)，返回 (结果, 耗时ms)。用于性能对比。"""
    t0 = time.time()
    r = func(*args, **kw)
    ms = (time.time() - t0) * 1000
    print(f"[计时] {name}: {ms:.1f} ms")
    return r, ms


# ---- 并发 ----
def run_concurrent(task, times: int = 10, max_workers: int = 10):
    name = getattr(task, "__name__", str(task))
    print(f"\n########## 并发 {name} x{times} (workers={max_workers}) ##########")
    start = time.time()
    results = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as ex:
        futs = [ex.submit(task) for _ in range(times)]
        for f in concurrent.futures.as_completed(futs):
            try:
                results.append(f.result())
            except Exception as e:  # noqa: BLE001
                with _print_lock:
                    print("并发任务异常:", e)
    print(f"########## 并发结束, 耗时 {time.time() - start:.2f}s ##########")
    return results
