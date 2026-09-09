# -*- coding: utf-8 -*-
"""09-07 16:28 那次 cancelFlag=1 的关闭, 抓批量撤单捞单 SQL, 看 is_stop_out 有没有被排除"""
import io, sys
from datetime import datetime
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.path.insert(0, r"d:\code-3\avs_option\hk_avs_sit")
from common import kibana

def dump(kw, start, end, filters=None, size=800):
    try:
        rows = kibana.search(kw, index=kibana.INDEX_SIT,
                             start=datetime.strptime(start, "%Y-%m-%d %H:%M:%S"),
                             end=datetime.strptime(end, "%Y-%m-%d %H:%M:%S"),
                             size=size, order="asc")
    except Exception as e:
        print("[%s] 失败 %s" % (kw, str(e)[:80])); return
    hits = []
    for r in rows:
        m = r["message"]
        if filters and not any(f in m for f in filters):
            continue
        hits.append(m.strip())
    print("[%s] 命中 %d / 过滤后 %d" % (kw, len(rows), len(hits)))
    with open(r"d:\code-3\_log2.txt", "a", encoding="utf-8") as f:
        for h in hits:
            f.write("=" * 90 + "\n" + h[:2200] + "\n")

open(r"d:\code-3\_log2.txt", "w", encoding="utf-8").close()
# 09-07 16:28 关闭(cancelFlag=1); 找捞需撤销盘前单的 SQL
dump("session_type", "2026-09-07 16:27:00", "2026-09-07 16:30:00",
     filters=["session_type", "internal_status"])
dump("PreMarketSwitchOrderCancel", "2026-09-07 16:27:00", "2026-09-07 16:30:00")
dump("is_stop_out", "2026-09-07 16:27:00", "2026-09-07 16:30:00")
dump("premarket-switch-review", "2026-09-07 16:27:00", "2026-09-07 16:30:00")
print("done")
