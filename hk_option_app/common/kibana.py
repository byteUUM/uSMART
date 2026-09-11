"""
Kibana 日志查询(按 config 的环境自动选 Kibana 地址与索引)
========================================================
用于下单/改单后到 option-order-server 日志里核对：
  - 接口是否命中(请求地址 + 请求参数)
  - 下单落库来源 order_origin、缓存命中等
时区：ES 存 UTC，本模块参数传北京时间，内部自动转。
"""
import json
from datetime import datetime, timedelta

import requests

from common.config import KIBANA_BASE, ES_INDEX

SEARCH_PATH = "/elasticsearch/_msearch?rest_total_hits_as_int=true&ignore_throttled=true"
KBN_VERSION = "7.1.0"
BJ_TO_UTC = timedelta(hours=8)

HEADERS = {
    "Content-Type": "application/x-ndjson",
    "kbn-version": KBN_VERSION,
    "Accept": "application/json, text/plain, */*",
    "Origin": KIBANA_BASE,
    "Referer": KIBANA_BASE + "/app/kibana",
    "User-Agent": "Mozilla/5.0",
}


def _to_utc_str(bj_dt):
    return (bj_dt - BJ_TO_UTC).strftime("%Y-%m-%dT%H:%M:%S.000Z")


def search(keyword, index=None, start=None, end=None, size=200, order="asc"):
    """按关键词 phrase 检索日志，返回 list[dict]。"""
    index = index or ES_INDEX
    now = datetime.now()
    end = end or now
    start = start or (end - timedelta(hours=24))

    header = {"index": index, "ignore_unavailable": True,
              "preference": int(now.timestamp() * 1000)}
    body = {
        "version": True,
        "size": size,
        "sort": [{"@timestamp": {"order": order, "unmapped_type": "boolean"}}],
        "_source": {"excludes": []},
        "stored_fields": ["*"],
        "docvalue_fields": [{"field": "@timestamp", "format": "date_time"}],
        "query": {"bool": {
            "must": [{"range": {"@timestamp": {
                "format": "strict_date_optional_time",
                "gte": _to_utc_str(start),
                "lte": _to_utc_str(end),
            }}}],
            "filter": [{"multi_match": {"type": "phrase", "query": str(keyword),
                                        "lenient": True}}],
            "should": [], "must_not": [],
        }},
        "timeout": "30000ms",
    }
    payload = (json.dumps(header, ensure_ascii=False) + "\n" +
               json.dumps(body, ensure_ascii=False) + "\n")

    resp = requests.post(KIBANA_BASE + SEARCH_PATH, headers=HEADERS,
                         data=payload.encode("utf-8"), timeout=60)
    resp.raise_for_status()
    responses = resp.json().get("responses") or []
    if not responses:
        return []
    r0 = responses[0]
    if r0.get("error"):
        raise RuntimeError("ES 错误: " + json.dumps(r0["error"], ensure_ascii=False)[:300])
    out = []
    for hit in (r0.get("hits", {}) or {}).get("hits", []) or []:
        s = hit.get("_source", {}) or {}
        out.append({
            "time": s.get("@timestamp"),
            "level": s.get("level_info") or s.get("level"),
            "message": s.get("message") or "",
        })
    return out


def find_request(keyword, minutes=10):
    """查最近 minutes 分钟内包含 keyword 的日志(便于下单后立即核对)。"""
    end = datetime.now()
    start = end - timedelta(minutes=minutes)
    return search(keyword, start=start, end=end, order="desc")
