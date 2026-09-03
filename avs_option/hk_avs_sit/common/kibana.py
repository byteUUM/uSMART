"""
Kibana / Elasticsearch 日志查询客户端
=====================================
走 Kibana 的 _msearch 代理接口查 ES 日志, 免去手工在界面上翻页。

接口信息(抓包得到):
  POST http://10.60.6.68:5601/elasticsearch/_msearch?rest_total_hits_as_int=true&ignore_throttled=true
  Content-Type: application/x-ndjson      (ndjson: 一行 header + 一行 query, 末尾要换行)
  kbn-version: 7.1.0                      (Kibana 必需, 不带会被拒)

索引命名:
  option-order-server-sit*    HK_SIT 的期权订单服务
  option-order-server-uat*    HK_UAT
  其它服务把 option-order-server 换成对应服务名即可

时区注意:
  ES 里 @timestamp 存 UTC, 查询区间要用 UTC。北京时间 - 8 小时 = UTC。
  本模块的时间参数统一传"北京时间", 内部自动转 UTC。
"""
import json
from datetime import datetime, timedelta

import requests

# ============================ 配置 ============================
KIBANA_BASE = "http://10.60.6.68:5601"
SEARCH_PATH = "/elasticsearch/_msearch?rest_total_hits_as_int=true&ignore_throttled=true"
KBN_VERSION = "7.1.0"

# 常用索引
INDEX_SIT = "option-order-server-sit*"
INDEX_UAT = "option-order-server-uat*"

BJ_TO_UTC = timedelta(hours=8)   # 北京 - 8h = UTC

HEADERS = {
    "Content-Type": "application/x-ndjson",
    "kbn-version": KBN_VERSION,
    "Accept": "application/json, text/plain, */*",
    "Origin": KIBANA_BASE,
    "Referer": KIBANA_BASE + "/app/kibana",
    "User-Agent": "Mozilla/5.0",
}


def _to_utc_str(bj_dt):
    """北京时间 datetime -> ES 需要的 UTC ISO 字符串"""
    return (bj_dt - BJ_TO_UTC).strftime("%Y-%m-%dT%H:%M:%S.000Z")


def search(keyword, index=INDEX_SIT, start=None, end=None, size=500, order="asc"):
    """
    按关键词做 phrase 检索(和 Kibana 搜索框里输入关键词等价)。

    keyword : 检索词, 如 requestId / orderId / traceId
    index   : 索引名, 默认 SIT
    start   : 起始时间(北京时间 datetime), 默认 24 小时前
    end     : 结束时间(北京时间 datetime), 默认现在
    order   : asc 按时间正序(便于顺读调用链) / desc 倒序
    返回    : list[dict], 每条含 time/level/service/message 等
    """
    now = datetime.now()
    if end is None:
        end = now
    if start is None:
        start = end - timedelta(hours=24)

    header = {"index": index, "ignore_unavailable": True,
              "preference": int(now.timestamp() * 1000)}
    body = {
        "version": True,
        "size": size,
        "sort": [{"@timestamp": {"order": order, "unmapped_type": "boolean"}}],
        "_source": {"excludes": []},
        "stored_fields": ["*"],
        "script_fields": {},
        "docvalue_fields": [{"field": "@timestamp", "format": "date_time"}],
        "query": {"bool": {
            "must": [{"range": {"@timestamp": {
                "format": "strict_date_optional_time",
                "gte": _to_utc_str(start),
                "lte": _to_utc_str(end),
            }}}],
            "filter": [{"multi_match": {"type": "phrase", "query": str(keyword),
                                        "lenient": True}}],
            "should": [],
            "must_not": [],
        }},
        "timeout": "30000ms",
    }
    payload = json.dumps(header, ensure_ascii=False) + "\n" + \
              json.dumps(body, ensure_ascii=False) + "\n"

    resp = requests.post(KIBANA_BASE + SEARCH_PATH, headers=HEADERS,
                         data=payload.encode("utf-8"), timeout=60)
    resp.raise_for_status()
    data = resp.json()
    responses = data.get("responses") or []
    if not responses:
        return []
    r0 = responses[0]
    if r0.get("error"):
        raise RuntimeError("ES 返回错误: %s" % json.dumps(r0["error"], ensure_ascii=False)[:300])

    out = []
    for hit in (r0.get("hits", {}) or {}).get("hits", []) or []:
        s = hit.get("_source", {}) or {}
        out.append({
            "time": s.get("@timestamp"),
            "level": s.get("level_info") or s.get("level"),
            "service": s.get("service_name"),
            "message": s.get("message") or "",
            "host": (s.get("beat") or {}).get("hostname") if isinstance(s.get("beat"), dict)
                    else s.get("beat.hostname"),
            "file": s.get("source") or s.get("log.file.path"),
            "_id": hit.get("_id"),
        })
    return out


def total_hits(keyword, index=INDEX_SIT, start=None, end=None):
    """只要命中条数"""
    return len(search(keyword, index=index, start=start, end=end, size=1))


def extract_trace_ids(rows):
    """从日志 message 里抽取 traceId(格式 |xxxxxxxxxxxxxxxx| 的16位十六进制)"""
    import re
    ids = []
    for r in rows:
        for m in re.findall(r"\|([0-9a-f]{16})\|", r["message"]):
            if m not in ids:
                ids.append(m)
    return ids
