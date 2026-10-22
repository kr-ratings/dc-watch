"""점검: 건축HUB 인허가 API에 최근 몇 월까지 자료가 들어와 있는지 본다.
전국에서 인허가가 많은 동 · 리 40곳에서 대장 생성 · 변경일(crtnDay) 월별 건수를 센다.
결과: probe/out/recent.json (키 값은 남기지 않는다)"""
import json, os, sys
sys.path.insert(0, "collector")
from common import Quota, load_json  # noqa
import permits as P  # noqa

uc = load_json("data/state/unit_counts.json", {})
top = sorted(uc.get("counts", {}).items(), key=lambda x: -x[1])[:40]
MON = [("2026-06", "20260601", "20260630"), ("2026-07", "20260701", "20260731"), ("2026-08", "20260801", "20260831"),
       ("2026-09", "20260901", "20260930"), ("2026-10", "20261001", "20261031")]
q = Quota(2000)
out = {"units": [], "sum": {m: 0 for m, _, _ in MON}, "latest": ""}
for k, n in top:
    sg, bj = k.split("-")
    row = {"unit": k, "since2020": n}
    for m, a, b in MON:
        try:
            tot, its = P.call(q, "getApBasisOulnInfo", sigunguCd=sg, bjdongCd=bj, numOfRows=100, pageNo=1, startDate=a, endDate=b)
            row[m] = tot
            out["sum"][m] += tot or 0
            for it in its:
                c = str(it.get("crtnDay") or "")
                if c > out["latest"]:
                    out["latest"] = c
        except Exception as e:  # noqa: BLE001
            row[m] = f"err {str(e)[:60]}"
    out["units"].append(row)
os.makedirs("probe/out", exist_ok=True)
json.dump(out, open("probe/out/recent.json", "w"), ensure_ascii=False, indent=1)
print(json.dumps(out["sum"]), "latest crtnDay", out["latest"])
