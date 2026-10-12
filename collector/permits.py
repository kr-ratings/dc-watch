"""건축HUB 건축인허가(기본개요 → 층별개요)에서 데이터센터 건을 모은다.

- 기본개요(getApBasisOulnInfo)는 시군구+법정동 단위로만 조회되므로 전국 법정동을 순서대로 훑는다.
- startDate/endDate는 대장 생성·변경일(crtnDay) 기준이라, 착공·사용승인 같은 단계 변화도 다시 잡힌다.
- 주용도 방송통신시설(24000) 건만 층별개요를 받아 세부용도 '데이터센터'(24005)가 있는지 확인한다.
- 하루 호출 한도를 넘지 않도록 상한을 두고, 다 못 돌면 상태 파일에 이어서 돌 위치를 남긴다.
"""
import argparse, datetime as dt, json, os, re, sys, threading, time
from concurrent.futures import ThreadPoolExecutor
from common import DGK, Quota, QuotaExceeded, get, load_json, save_json, scrub

HUB = "https://apis.data.go.kr/1613000/ArchPmsHubService/"
STATE = "data/state/permit_scan.json"
OUT = "data/permits.json"
KEEP = ["mgmPmsrgstPk", "platPlc", "sigunguCd", "bjdongCd", "bun", "ji", "bldNm", "mainPurpsCd", "mainPurpsCdNm", "archGbCdNm",
        "totArea", "platArea", "archArea", "vlRat", "bcRat", "archPmsDay", "stcnsSchedDay", "stcnsDelayDay", "realStcnsDay", "useAprDay", "crtnDay",
        "jiyukCdNm", "jiguCdNm"]


def call(q, op, **p):
    params = {"serviceKey": DGK, "_type": "json", "numOfRows": 100, "pageNo": 1}
    params.update(p)
    j = None
    for i in range(3):
        q.take()
        r = get(HUB + op, params, tries=3, timeout=(10, 60))
        try:
            j = r.json()
            break
        except ValueError:
            time.sleep(3 * (i + 1))  # 순간 과부하로 빈 응답이 오는 경우가 있어 잠시 쉬고 다시
    if j is None:
        raise RuntimeError(f"빈 응답 {r.status_code} {scrub(r.text[:80])}")
    body = (j.get("response") or {}).get("body") or {}
    head = (j.get("response") or {}).get("header") or {}
    if head and head.get("resultCode") not in ("00", None):
        raise RuntimeError(f"{op} {head}")
    if not body and j.get("OpenAPI_ServiceResponse"):
        if "LIMITED_NUMBER_OF_SERVICE_REQUESTS" in json.dumps(j):
            raise QuotaExceeded()  # 포털 일일 한도에 걸리면 바로 멈추고 다음 실행에 이어서
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
                h = {k: clean(it.get(k)) for k in KEEP}
                h["mgmPmsrgstPk"] = str(it.get("mgmPmsrgstPk"))
                hits.append(h)
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
    ap.add_argument("--only", default="")         # 쉼표로 구분한 '시군구-법정동' 단위만 받기
    ap.add_argument("--max-seconds", type=int, default=0)  # 이 시간이 지나면 다음 묶음을 시작하지 않고 저장 후 끝낸다
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
    until = (dt.datetime.utcnow() + dt.timedelta(hours=9)).strftime("%Y%m%d")   # 한국 날짜 기준
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
    # 지난번에 오류가 난 단위는 맨 뒤에서 다시 받는다(무거운 단위가 앞을 막지 않게)
    errs = set(st.get("errors", {}))
    todo.sort(key=lambda u: 1 if f"{u[1]}-{u[2]}" in errs else 0)
    if a.only:
        only = set(x.strip() for x in a.only.split(","))
        todo = [u for u in todo if f"{u[1]}-{u[2]}" in only]
    print(f"units {len(units)}, todo {len(todo)}", flush=True)
    found = {h["mgmPmsrgstPk"]: h for h in load_json(OUT, {"items": []}).get("items", [])}
    q = Quota(a.limit)
    t0 = time.time()

    lock = threading.Lock()
    conn = {"fail": 0}
    CONN_MAX = 12   # 연결 자체가 연달아 이만큼 실패하면 이 실행 환경에서 서버에 닿지 않는 것으로 보고 멈춘다

    def work(u):
        if conn["fail"] >= CONN_MAX:
            return u, None, "conn"
        try:
            res = u, scan_unit(q, u, a.since, until), None
            with lock:
                conn["fail"] = 0
            return res
        except QuotaExceeded:
            return u, None, "quota"
        except Exception as e:
            msg = scrub(repr(e))[:200]
            if re.search(r"ConnectTimeout|ConnectionError|Max retries|NewConnectionError", msg):
                with lock:
                    conn["fail"] += 1
                return u, None, msg
        # 대장이 너무 많아 서버가 빈 응답을 주는 단위(가산 · 죽전 등)는 연도별로 나눠 다시 받는다
        try:
            got = {}
            for y in range(int(a.since[:4]), int(until[:4]) + 1):
                s_, e_ = max(a.since, f"{y}0101"), min(until, f"{y}1231")
                for h in scan_unit(q, u, s_, e_):
                    got[h["mgmPmsrgstPk"]] = h
            with lock:
                conn["fail"] = 0
            return u, list(got.values()), None
        except QuotaExceeded:
            return u, None, "quota"
        except Exception as e2:
            return u, None, "연도별 재시도 실패: " + scrub(repr(e2))[:180]

    reason = "pass"
    deadline = t0 + a.max_seconds if a.max_seconds else None
    with ThreadPoolExecutor(a.workers) as ex:
        for i in range(0, len(todo), 40):
            if reason != "pass":
                break
            if deadline and time.time() > deadline:
                reason = "time"
                break
            for u, hits, err in ex.map(work, todo[i:i + 40]):
                key = f"{u[1]}-{u[2]}"
                if err == "quota":
                    reason = "limit" if q.used >= a.limit else "quota"
                    continue
                if err == "conn":
                    reason = "conn"
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
    if reason == "pass" and conn["fail"] >= CONN_MAX:
        reason = "conn"
    st["complete"] = len(done) >= len(units)
    st["stop"] = "done" if st["complete"] else reason   # done · pass(남은 건 오류 단위뿐) · limit · time · quota(포털 한도) · conn(서버 연결 안 됨)
    st["calls_last_run"] = q.used
    save_json(STATE, st)
    print("stop", st["stop"], "calls", q.used, "done", len(done), "/", len(units), "errors", len(st["errors"]))


if __name__ == "__main__":
    sys.path.insert(0, os.path.dirname(__file__))
    main()
