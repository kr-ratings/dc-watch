"""건축HUB 건축인허가(기본개요 → 층별개요)에서 데이터센터 건을 모은다.

- 기본개요(getApBasisOulnInfo)는 시군구+법정동 단위로만 조회되므로 전국 법정동을 순서대로 훑는다.
- startDate/endDate는 대장 생성·변경일(crtnDay) 기준이라, 착공·사용승인 같은 단계 변화도 다시 잡힌다.
- 주용도 방송통신시설(24000) 건만 층별개요를 받아 세부용도 '데이터센터'(24005)가 있는지 확인한다.
- 하루 호출 한도를 넘지 않도록 상한을 두고, 다 못 돌면 상태 파일에 이어서 돌 위치를 남긴다.
"""
import argparse, datetime as dt, json, os, sys, time
from concurrent.futures import ThreadPoolExecutor
from common import DGK, Quota, QuotaExceeded, get, load_json, save_json, scrub

HUB = "https://apis.data.go.kr/1613000/ArchPmsHubService/"
STATE = "data/state/permit_scan.json"
OUT = "data/permits.json"
KEEP = ["mgmPmsrgstPk", "platPlc", "sigunguCd", "bjdongCd", "bun", "ji", "bldNm", "mainPurpsCd", "mainPurpsCdNm", "archGbCdNm",
        "totArea", "platArea", "archArea", "vlRat", "bcRat", "archPmsDay", "stcnsSchedDay", "stcnsDelayDay", "realStcnsDay", "useAprDay", "crtnDay",
        "jiyukCdNm", "jiguCdNm"]


def call(q, op, **p):
    q.take()
    params = {"serviceKey": DGK, "_type": "json", "numOfRows": 100, "pageNo": 1}
    params.update(p)
    r = get(HUB + op, params)
    j = r.json()
    body = (j.get("response") or {}).get("body") or {}
    head = (j.get("response") or {}).get("header") or {}
    if head and head.get("resultCode") not in ("00", None):
        raise RuntimeError(f"{op} {head}")
    if not body and j.get("OpenAPI_ServiceResponse"):
        raise RuntimeError(scrub(json.dumps(j)[:300]))
    items = (body.get("items") or {})
    items = items.get("item", []) if isinstance(items, dict) else []
    if isinstance(items, dict):
        items = [items]
    return int(body.get("totalCount") or 0), items


def clean(v):
    return v.strip() if isinstance(v, str) else v


def scan_unit(q, unit, since, until):
    sido, sgg, bjd = unit[0], unit[1], unit[2]
    hits, page = [], 1
    while True:
        total, items = call(q, "getApBasisOulnInfo", sigunguCd=sgg, bjdongCd=bjd, pageNo=page, startDate=since, endDate=until)
        for it in items:
            if str(it.get("mainPurpsCd", "")).strip() == "24000" or "방송통신" in str(it.get("mainPurpsCdNm", "")):
                hits.append({k: clean(it.get(k)) for k in KEEP})
        if page * 100 >= total or not items:
            break
        page += 1
    # 층별개요로 세부용도 확인(같은 지번은 한 번만)
    seen = {}
    for h in hits:
        key = (h["bun"], h["ji"])
        if key not in seen:
            flr = []
            pg = 1
            while True:
                tot, its = call(q, "getApFlrOulnInfo", sigunguCd=sgg, bjdongCd=bjd, bun=h["bun"], ji=h["ji"], pageNo=pg)
                flr += its
                if pg * 100 >= tot or not its or pg >= 5:
                    break
                pg += 1
            seen[key] = flr
        flr = [f for f in seen[key] if str(f.get("mgmPmsrgstPk")) == str(h["mgmPmsrgstPk"])] or seen[key]
        dc = [f for f in flr if str(f.get("mainPurpsCd", "")).strip() == "24005" or "데이터센터" in str(f.get("mainPurpsCdNm", ""))]
        h["dc"] = bool(dc)
        h["dcFlrArea"] = round(sum(float(f.get("flrArea") or 0) for f in dc), 2) if dc else 0
        h["flrPurps"] = sorted({str(f.get("mainPurpsCdNm", "")).strip() for f in flr if str(f.get("mainPurpsCdNm", "")).strip()})[:6]
        h["dongNm"] = sorted({str(f.get("bldNm", "")).strip() for f in dc if str(f.get("bldNm", "")).strip()})[:4]
        h["sido"], h["sggNm"], h["dongNmAddr"] = sido, unit[3], " ".join(x for x in unit[4:6] if x and str(x) != "nan")
    return hits


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--units", default="data/bjd_units.json")
    ap.add_argument("--sido", default="")          # 쉼표로 구분한 시도명(비우면 전체)
    ap.add_argument("--exclude-sgg", default="")   # 제외할 시군구코드 접두
    ap.add_argument("--since", default="20200101")
    ap.add_argument("--limit", type=int, default=9000)
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--restart", action="store_true")
    a = ap.parse_args()
    if not DGK:
        print("DATA_GO_KR_KEY 없음"); return
    units = load_json(a.units, None) or load_json("data/bjd_units_seed.json", [])
    if a.sido:
        want = set(s.strip() for s in a.sido.split(","))
        units = [u for u in units if u[0] in want]
    if a.exclude_sgg:
        ex = tuple(x.strip() for x in a.exclude_sgg.split(","))
        units = [u for u in units if not str(u[1]).startswith(ex)]
    until = dt.date.today().strftime("%Y%m%d")
    st = load_json(STATE, {})
    if a.restart or not st:
        st = {"since": a.since, "done": [], "errors": {}, "started": until, "pass": 1}
    elif st.get("complete"):
        # 한 바퀴를 다 돌았으면 직전 회차 시작일(7일 겹침)부터 바뀐 대장만 다시 훑는다
        prev = dt.datetime.strptime(st["started"], "%Y%m%d").date() - dt.timedelta(days=7)
        st = {"since": prev.strftime("%Y%m%d"), "done": [], "errors": {}, "started": until, "pass": st.get("pass", 1) + 1,
              "last_complete": st["started"]}
    a.since = st["since"]
    done = set(st["done"])
    todo = [u for u in units if f"{u[1]}-{u[2]}" not in done]
    print(f"units {len(units)}, todo {len(todo)}", flush=True)
    found = {h["mgmPmsrgstPk"]: h for h in load_json(OUT, {"items": []}).get("items", [])}
    q = Quota(a.limit)
    t0 = time.time()

    def work(u):
        try:
            return u, scan_unit(q, u, a.since, until), None
        except QuotaExceeded:
            return u, None, "quota"
        except Exception as e:
            return u, None, scrub(repr(e))[:200]

    stop = False
    with ThreadPoolExecutor(a.workers) as ex:
        for i in range(0, len(todo), 40):
            if stop:
                break
            for u, hits, err in ex.map(work, todo[i:i + 40]):
                key = f"{u[1]}-{u[2]}"
                if err == "quota":
                    stop = True
                    continue
                if err:
                    st["errors"][key] = err
                    continue
                st["errors"].pop(key, None)
                done.add(key)
                for h in hits:
                    found[h["mgmPmsrgstPk"]] = h
            st["done"] = sorted(done)
            st["calls_last_run"] = q.used
            save_json(STATE, st)
            save_json(OUT, {"updated": until, "since": a.since, "items": sorted(found.values(), key=lambda h: (h.get("archPmsDay") or ""), reverse=True)})
            print(f"{min(i + 40, len(todo))}/{len(todo)} calls {q.used} hits {len(found)} dc {sum(1 for h in found.values() if h.get('dc'))} {int(time.time() - t0)}s", flush=True)
    st["complete"] = len(done) >= len(units)
    save_json(STATE, st)
    print("complete" if st["complete"] else "partial", q.used)


if __name__ == "__main__":
    sys.path.insert(0, os.path.dirname(__file__))
    main()
