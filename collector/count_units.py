"""전국 동 · 리별 건축 인허가 건수(대장 생성 · 변경일이 since 이후인 건)를 센다.
한 동에 한 번만, 1건짜리 페이지로 조회해 totalCount만 받는다(전국 약 1만 9천 번 호출).
결과: data/state/unit_counts.json — 동 · 리별 건수와 전국 합계. 중간에 끊겨도 이어서 센다.
이번 회차에 아직 못 센(서버 503 등) 동 · 리는 직전 회차 값(base)으로 채워 합계를 낸다.
그러지 않으면 몇 개 동만 빠져도 전국 합계가 줄어든 것처럼 보인다(10/20: 6개 동 503 → 2,228건 적게 표시)."""
import argparse, calendar, datetime as dt, os, re, sys, threading, time
from concurrent.futures import ThreadPoolExecutor
sys.path.insert(0, os.path.dirname(__file__))
from common import DGK, Quota, QuotaExceeded, load_json, save_json, scrub
from permits import call

OUT = "data/state/unit_counts.json"


def src_latest(q, counts, today):
    """원자료(건축HUB)에 들어와 있는 가장 최근 대장 생성 · 변경일을 찾는다.
    국토부가 한 달에 한 번 몰아서 올려 전국 건수가 며칠씩 그대로일 수 있으므로, 원자료가 어디까지인지 화면에 함께 적는다.
    인허가가 많은 동 · 리 20곳에서 이번 달부터 거슬러 올라가며 건이 있는 첫 달을 찾고, 그 달 자료의 최신 날짜를 쓴다."""
    top = [k for k, _ in sorted(counts.items(), key=lambda x: -x[1])[:20]]
    y, m = today.year, today.month
    for _ in range(4):
        a, b = f"{y}{m:02d}01", f"{y}{m:02d}{calendar.monthrange(y, m)[1]:02d}"
        latest = ""
        for k in top:
            sg, bj = k.split("-")
            try:
                n, items = call(q, "getApBasisOulnInfo", sigunguCd=sg, bjdongCd=bj, numOfRows=100, pageNo=1, startDate=a, endDate=b)
            except Exception:  # noqa: BLE001
                continue
            for it in items or []:
                c = str(it.get("crtnDay") or "")
                if a <= c <= b and c > latest:
                    latest = c
        if latest:
            return latest
        m -= 1
        if m == 0:
            y, m = y - 1, 12
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--since", default="20200101")
    ap.add_argument("--workers", type=int, default=3)
    ap.add_argument("--limit", type=int, default=25000)
    ap.add_argument("--src-only", action="store_true", help="원자료 최신 날짜만 다시 확인")
    a = ap.parse_args()
    if not DGK:
        print("DATA_GO_KR_KEY 없음"); return
    units = load_json("data/bjd_units.json", [])
    until = (dt.datetime.utcnow() + dt.timedelta(hours=9)).strftime("%Y%m%d")   # 한국 날짜 기준
    st = load_json(OUT, {})
    if a.src_only:
        v = src_latest(Quota(200), {**st.get("base", {}), **st.get("counts", {})}, dt.date(int(until[:4]), int(until[4:6]), int(until[6:])))
        if v:
            st["src_latest"] = v
            save_json(OUT, st)
        print("원자료 최신", v); return
    if st.get("since") != a.since or st.get("complete"):
        base = {**st.get("base", {}), **st.get("counts", {})} if st.get("since") == a.since else {}
        st = {"since": a.since, "until": until, "counts": {}, "errors": {}, "base": base,
              **({"src_latest": st["src_latest"]} if st.get("src_latest") else {})}
    st.setdefault("base", {})
    todo = [u for u in units if f"{u[1]}-{u[2]}" not in st["counts"]]
    print(f"units {len(units)}, todo {len(todo)}", flush=True)
    q, lock, conn = Quota(a.limit), threading.Lock(), {"fail": 0}

    def work(u):
        if conn["fail"] >= 12:
            return u, None, "conn"
        try:
            n, _ = call(q, "getApBasisOulnInfo", sigunguCd=u[1], bjdongCd=u[2], numOfRows=1, pageNo=1, startDate=st["since"], endDate=until)
            with lock:
                conn["fail"] = 0
            return u, n, None
        except QuotaExceeded:
            return u, None, "quota"
        except Exception as e:
            msg = scrub(repr(e))[:160]
            if re.search(r"ConnectTimeout|ConnectionError|Max retries", msg):
                with lock:
                    conn["fail"] += 1
            return u, None, msg

    keys = [f"{u[1]}-{u[2]}" for u in units]

    def tally():
        st["total"] = sum(st["counts"].get(k, st["base"].get(k, 0)) for k in keys)
        st["n"], st["units"] = len(st["counts"]), len(units)
        st["carried"] = sum(1 for k in keys if k not in st["counts"] and k in st["base"])

    reason, t0 = "done", time.time()
    with ThreadPoolExecutor(a.workers) as ex:
        for i in range(0, len(todo), 200):
            for u, n, err in ex.map(work, todo[i:i + 200]):
                k = f"{u[1]}-{u[2]}"
                if err in ("quota", "conn"):
                    reason = err
                elif err:
                    st["errors"][k] = err
                else:
                    st["counts"][k] = n
                    st["errors"].pop(k, None)
            tally()
            save_json(OUT, st)
            print(f"{min(i + 200, len(todo))}/{len(todo)} counted {st['n']} total {st['total']:,} {int(time.time() - t0)}s", flush=True)
            if reason != "done":
                break
    # 일시 오류(HTTP 503 등)로 빠진 동 · 리는 잠시 쉬었다가 두 번까지 다시 센다
    for _ in range(2):
        left = [u for u in units if f"{u[1]}-{u[2]}" in st["errors"]]
        if not left or reason != "done":
            break
        time.sleep(30)
        for u in left:
            u, n, err = work(u)
            k = f"{u[1]}-{u[2]}"
            if err in ("quota", "conn"):
                reason = err; break
            if not err:
                st["counts"][k] = n; st["errors"].pop(k, None)
        print("다시 센 뒤 남은 오류", len(st["errors"]), flush=True)
    tally()
    try:
        v = src_latest(q, {**st["base"], **st["counts"]}, dt.date(int(until[:4]), int(until[4:6]), int(until[6:])))
        if v:
            st["src_latest"] = v
    except Exception as e:  # noqa: BLE001
        print("원자료 최신 날짜 확인 실패", scrub(repr(e))[:120])
    st["complete"] = st["n"] >= len(units)
    st["stop"] = "done" if st["complete"] else reason if reason != "done" else "partial"
    save_json(OUT, st)
    print("stop", st["stop"], "counted", st["n"], "/", len(units), "total", f"{st['total']:,}", "errors", len(st["errors"]), "직전 값으로 채움", st["carried"])


if __name__ == "__main__":
    main()
