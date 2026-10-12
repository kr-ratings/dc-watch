"""행정안전부 법정동코드(현존)로 건축HUB 조회 단위(시군구코드+법정동코드) 목록을 만든다."""
import datetime as dt, os
from common import DGK, get, load_json, save_json

OUT = "data/bjd_units.json"


def collect(force=False):
    cur = load_json(OUT, None)
    meta = load_json("data/state/regions.json", {})
    if cur and not force and meta.get("updated", "") >= (dt.date.today() - dt.timedelta(days=27)).isoformat():
        print("regions fresh", meta.get("updated")); return
    rows, page = [], 1
    while True:
        r = get("https://apis.data.go.kr/1741000/StanReginCd/getStanReginCdList",
                {"ServiceKey": DGK, "type": "json", "pageNo": page, "numOfRows": 1000, "flag": "Y"})
        j = r.json().get("StanReginCd") or []
        part = j[1]["row"] if len(j) > 1 else []
        total = int(j[0]["head"][0]["totalCount"]) if j else 0
        rows += part
        if not part or len(rows) >= total:
            break
        page += 1
    has_ri = {r["region_cd"][:8] for r in rows if r.get("ri_cd") not in ("00", None, "")}
    units = []
    for r in rows:
        rc = r["region_cd"]
        if r.get("umd_cd") in ("000", None, ""):
            continue  # 시도·시군구 단위
        if r.get("ri_cd") in ("00", None, "") and rc[:8] in has_ri:
            continue  # 리가 있는 읍·면 자체는 건너뜀
        toks = r["locatadd_nm"].split()
        if r.get("ri_cd") not in ("00", None, ""):
            umd, ri, sgg = toks[-2], toks[-1], " ".join(toks[1:-2])
        else:
            umd, ri, sgg = toks[-1], "", " ".join(toks[1:-1])
        units.append([toks[0], rc[:5], rc[5:10], sgg, umd, ri])
    if len(units) > 15000:  # 비정상 응답이면 기존 목록 유지
        save_json(OUT, units)
        save_json("data/state/regions.json", {"updated": dt.date.today().isoformat(), "rows": len(rows), "units": len(units)})
    print("regions rows", len(rows), "units", len(units))


if __name__ == "__main__":
    collect(force=bool(os.environ.get("FORCE")))
