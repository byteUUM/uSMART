"""
公共请求客户端模块
==================
封装所有业务脚本共用的能力:
  - build_headers : 生成请求头(自动填充 X-Request-Id)
  - send_order    : 发送单个下单/改单/撤单请求并打印结果
  - run_concurrent / run_concurrent_mix : 并发压测工具

各业务文件只需 import 这几个函数，专注于"拼请求体"即可。
"""
import concurrent.futures
import threading
import time
import uuid

import requests

# 通过 sys.path 引导(见各业务文件顶部)，这里用绝对包路径引用配置
from common.config import COMMON_HEADERS

# 打印锁: 并发时保证单个请求的多行输出不会互相交错
_print_lock = threading.Lock()


def build_headers(fixed_request_id: str = None, extra: dict = None) -> dict:
    """
    生成请求头。
    fixed_request_id: 若传入则使用固定的 X-Request-Id(便于复现/幂等测试)，
                      否则每次自动生成新的 uuid。
    extra:            需要额外覆盖/追加的头字段。
    """
    headers = COMMON_HEADERS.copy()
    headers["X-Request-Id"] = fixed_request_id or str(uuid.uuid4())
    if extra:
        headers.update(extra)
    return headers


def send_order(name: str, url: str, body: dict, headers: dict = None):
    """发送单个请求并打印结果。headers 不传则自动生成。"""
    headers = headers or build_headers()
    print(f"\n===== {name} =====")
    print("request_id:", headers.get("X-Request-Id"))
    print("URL       :", url)
    print("请求体    :", body)
    try:
        resp = requests.post(url, headers=headers, json=body, timeout=30)
        print("状态码    :", resp.status_code)
        print("响应内容  :", resp.text)
        return resp
    except requests.RequestException as e:
        print("请求异常  :", e)
        return None


# ============================ 并发工具 ============================

def _send_concurrent(name, url, body, index=None):
    """并发场景的单次请求，输出加锁避免日志交错，并返回结果便于统计。"""
    headers = build_headers()
    tag = f"{name}#{index}" if index is not None else name
    try:
        resp = requests.post(url, headers=headers, json=body, timeout=30)
        with _print_lock:
            print(f"\n===== {tag} =====")
            print("状态码  :", resp.status_code)
            print("响应内容:", resp.text)
        return {"tag": tag, "ok": True, "status": resp.status_code, "text": resp.text}
    except requests.RequestException as e:
        with _print_lock:
            print(f"\n===== {tag} 请求异常 =====")
            print(e)
        return {"tag": tag, "ok": False, "status": None, "text": str(e)}


def run_concurrent(task, times: int = 10, max_workers: int = 10):
    """
    并发执行同一个无参下单函数 times 次。
    task:        无参函数(如各业务文件里的 create/cancel 包装函数)。
    times:       总请求次数。
    max_workers: 最大并发线程数。
    """
    name = getattr(task, "__name__", str(task))
    print(f"\n########## 开始并发: {name} x{times} (并发数={max_workers}) ##########")
    start = time.time()
    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = [executor.submit(task) for _ in range(times)]
        for f in concurrent.futures.as_completed(futures):
            try:
                f.result()
            except Exception as e:  # noqa: BLE001
                with _print_lock:
                    print("并发任务异常:", e)
    print(f"########## 并发结束, 耗时 {time.time() - start:.2f}s ##########")


def run_concurrent_mix(tasks, max_workers: int = 10):
    """
    并发执行一组不同的无参下单函数。
    tasks: 无参函数列表, 如 [stock_buy, cfd_buy, odd_buy]。
    """
    print(f"\n########## 开始混合并发: {len(tasks)} 个任务 (并发数={max_workers}) ##########")
    start = time.time()
    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = [executor.submit(t) for t in tasks]
        for f in concurrent.futures.as_completed(futures):
            try:
                f.result()
            except Exception as e:  # noqa: BLE001
                with _print_lock:
                    print("并发任务异常:", e)
    print(f"########## 混合并发结束, 耗时 {time.time() - start:.2f}s ##########")
