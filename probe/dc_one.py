"""건축HUB 기본개요 한 단위(군산 비응도동) 그대로 보기 — 날짜 조건 없이 / 최근 변경일 조건으로. 키 · 주소는 출력하지 않음."""
import json, os, pathlib, requests
KEY = os.environ.get("DATA_GO_KR_KEY", "").strip()
HUB = "https://apis.data.go.kr/1613000/ArchPmsHubService/"
out = {}
for tag, extra in (("전체", {}), ("2026-08-21~", {"startDate": "20260821", "endDate": "20261105"})):
    p = {"serviceKey": KEY, "_type": "json", "numOfRows": 100, "pageNo": 1, "sigunguCd": "52130", "bjdongCd": "14800", **extra}
    j = requests.get(HUB + "getApBasisOulnInfo", params=p, timeout=(15, 60)).json()
    items = ((j.get("response") or {}).get("body") or {}).get("items") or {}
    items = items.get("item", []) if isinstance(items, dict) else []
    items = [items] if isinstance(items, dict) else items
    keep = [{k: it.get(k) for k in ("mgmPmsrgstPk", "platPlc", "bldNm", "mainPurpsCdNm", "archGbCdNm", "totArea", "archPmsDay", "stcnsSchedDay", "stcnsDelayDay", "realStcnsDay", "useAprDay", "crtnDay")} for it in items]
    out[tag] = {"total": ((j.get("response") or {}).get("body") or {}).get("totalCount"), "items": keep}
    print(tag, out[tag]["total"], flush=True)
for op in ("getApDongOulnInfo",):
    p = {"serviceKey": KEY, "_type": "json", "numOfRows": 100, "pageNo": 1, "sigunguCd": "52130", "bjdongCd": "14800", "bun": "0036", "ji": "0033"}
    try:
        j = requests.get(HUB + op, params=p, timeout=(15, 60)).json(); items = ((j.get("response") or {}).get("body") or {}).get("items") or {}
        out[op] = items
    except Exception as e:
        out[op] = type(e).__name__
pathlib.Path("probe/out").mkdir(parents=True, exist_ok=True)
pathlib.Path("probe/out/dc_one.json").write_text(json.dumps(out, ensure_ascii=False, indent=1))
