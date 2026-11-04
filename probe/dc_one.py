"""건축HUB 기본개요 한 단위(군산 비응도동) 그대로 보기 — 수집기와 같은 호출 함수 사용. 키 · 주소는 출력하지 않음."""
import json, pathlib, sys
sys.path.insert(0, "collector")
from common import Quota
from permits import call
q = Quota(50); out = {}
for tag, extra in (("전체", {}), ("2026-08-21~", {"startDate": "20260821", "endDate": "20261105"})):
    try:
        tot, items = call(q, "getApBasisOulnInfo", sigunguCd="52130", bjdongCd="14800", **extra)
        out[tag] = {"total": tot, "items": [{k: it.get(k) for k in ("mgmPmsrgstPk", "platPlc", "bldNm", "mainPurpsCdNm", "archGbCdNm", "totArea", "archPmsDay", "stcnsSchedDay", "stcnsDelayDay", "realStcnsDay", "useAprDay", "crtnDay")} for it in items]}
    except Exception as e:  # noqa
        out[tag] = {"error": type(e).__name__}
    print(tag, out[tag].get("total"), flush=True)
pathlib.Path("probe/out").mkdir(parents=True, exist_ok=True)
pathlib.Path("probe/out/dc_one.json").write_text(json.dumps(out, ensure_ascii=False, indent=1))
