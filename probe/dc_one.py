"""건축HUB 기본개요를 지번(bun · ji)으로 바로 조회되는지 확인 — 군산 비응도동 36-33, 날짜 조건 없이."""
import json, pathlib, sys
sys.path.insert(0, "collector")
from common import Quota
from permits import call
q = Quota(20); out = {}
for tag, p in (("지번", {"bun": "0036", "ji": "0033"}), ("지번+platGbCd0", {"platGbCd": "0", "bun": "0036", "ji": "0033"})):
    try:
        tot, items = call(q, "getApBasisOulnInfo", sigunguCd="52130", bjdongCd="14800", **p)
        out[tag] = {"total": tot, "items": [{k: it.get(k) for k in ("mgmPmsrgstPk", "platPlc", "mainPurpsCdNm", "archPmsDay", "stcnsSchedDay", "realStcnsDay", "useAprDay", "crtnDay")} for it in items]}
    except Exception as e:  # noqa
        out[tag] = {"error": repr(e)[:200]}
    print(tag, out[tag].get("total"), flush=True)
pathlib.Path("probe/out").mkdir(parents=True, exist_ok=True)
pathlib.Path("probe/out/dc_one.json").write_text(json.dumps(out, ensure_ascii=False, indent=1))
print("calls", q.used)
