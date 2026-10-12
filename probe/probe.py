"""시험: 언론으로 확인된 데이터센터가 있는 법정동에서, 2018년 이후 대장의 주용도와 층별 용도를 확인한다.
데이터센터가 '방송통신시설' 말고 다른 주용도(업무시설 · 공장 등)로도 허가되는지 보기 위한 1회성 점검.
결과: probe/out/use_check.json (키 값은 남기지 않는다)"""
import json, os, re, sys, time
sys.path.insert(0, "collector")
from common import Quota  # noqa
import permits as P  # noqa

DONGS = [("금천구 가산동", "11545", "10100"), ("용인 수지구 죽전동", "41465", "10200"), ("부평구 청천동", "28237", "10400"),
         ("안산 상록구 사동", "41271", "10300"), ("마포구 상암동", "11440", "12700"), ("세종 집현동", "36110", "11800"),
         ("화성 동탄구 석우동", "41597", "10300"), ("구로구 구로동", "11530", "10200"), ("성남 분당구 삼평동", "41135", "10900")]
KW = re.compile(r"데이터|데이타|IDC|DATA|전산|센터|서버|클라우드|AI", re.I)
q = Quota(1500)
out = {"dongs": []}
for nm, sg, bj in DONGS:
    d = {"dong": nm, "n": 0, "items": []}
    try:
        items, page = [], 1
        while True:
            tot, its = P.call(q, "getApBasisOulnInfo", sigunguCd=sg, bjdongCd=bj, pageNo=page, startDate="20180101", endDate="20261231")
            items += its
            if page * 100 >= tot or not its or page >= 15:
                break
            page += 1
        d["n"] = len(items)
        cand = [it for it in items if float(it.get("totArea") or 0) >= 8000 or KW.search(str(it.get("bldNm") or ""))
                or str(it.get("mainPurpsCd", "")).strip() == "24000"]
        seen = {}
        for it in cand:
            key = (it.get("bun"), it.get("ji"))
            if key not in seen:
                flr, pg = [], 1
                while True:
                    tot, fs = P.call(q, "getApFlrOulnInfo", sigunguCd=sg, bjdongCd=bj, bun=key[0], ji=key[1], pageNo=pg)
                    flr += fs
                    if pg * 100 >= tot or not fs or pg >= 3:
                        break
                    pg += 1
                seen[key] = flr
            fl = [f for f in seen[key] if str(f.get("mgmPmsrgstPk")) == str(it.get("mgmPmsrgstPk"))] or seen[key]
            purps = sorted({f"{(f.get('mainPurpsCdNm') or '').strip()}|{(f.get('etcPurps') or '').strip()}"[:60] for f in fl})
            dcf = any(str(f.get("mainPurpsCd", "")).strip() == "24005" or "데이터" in str(f.get("mainPurpsCdNm", "")) + str(f.get("etcPurps", ""))
                      or "IDC" in str(f.get("etcPurps", "")).upper() or "전산" in str(f.get("etcPurps", "")) for f in fl)
            d["items"].append({"nm": (it.get("bldNm") or "").strip(), "main": (it.get("mainPurpsCdNm") or "").strip(), "mainCd": str(it.get("mainPurpsCd", "")).strip(),
                               "area": it.get("totArea"), "pms": it.get("archPmsDay"), "apr": it.get("useAprDay"), "gb": it.get("archGbCdNm"),
                               "plat": (it.get("platPlc") or "").strip(), "dc_floor": dcf, "floor_uses": purps[:12]})
    except Exception as e:  # noqa
        d["err"] = P.scrub(repr(e))[:300]
    out["dongs"].append(d)
    print(nm, d["n"], len(d["items"]), "calls", q.used, flush=True)
os.makedirs("probe/out", exist_ok=True)
json.dump(out, open("probe/out/use_check.json", "w"), ensure_ascii=False, indent=1)
