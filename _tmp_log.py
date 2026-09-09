# -*- coding: utf-8 -*-
"""抓订单 1150144597180882944 下单链路: 接口入参 sessionType / 盘前校验 / 落库"""
import io, sys
from datetime import datetime
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.path.insert(0, r"d:\code-3\avs_option\hk_avs_sit")
from common import kibana

OID = "1150144597180882944"
NO = "1150144597180882945"

def dump(kw, start, end, filters=None, size=500):
    try:
        rows = kibana.search(kw, index=kibana.INDEX_SIT,
                             start=datetime.strptime(start, "%Y-%m-%d %H:%M:%S"),
                             end=datetime.strptime(end, "%Y-%m-%d %H:%M:%S"),
                             size=size, order="asc")
    except Exception as e:
        print("[%s] 失败 %s" % (kw, str(e)[:80])); return
    hits = [r["message"].strip() for r in rows
            if not filters or any(f in r["message"] for f in filters)]
    print("[%s] 命中 %d / 过滤 %d" % (kw, len(rows), len(hits)))
    with open(r"d:\code-3\_log.txt", "a", encoding="utf-8") as f:
        for h in hits:
            f.write("=" * 90 + "\n" + h[:2500] + "\n")

open(r"d:\code-3\_log.txt", "w", encoding="utf-8").close()
# 下单 19:04:01 前后
dump(OID, "2026-09-09 19:03:55", "2026-09-09 19:04:30")
print("done")
