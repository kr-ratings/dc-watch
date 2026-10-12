"""전국 동 · 리별 건축 인허가 건수(대장 생성 · 변경일이 since 이후인 건)를 센다.
한 동에 한 번만, 1건짜리 페이지로 조회해 totalCount만 받는다(전국 약 1만 9천 번 호출).
결과: data/state/unit_counts.json — 동 · 리별 건수와 전국 합계. 중간에 끊겨도 이어서 센다."""
import argparse, datetime as dt, os, re, sys, threading, time
from concurrent.futures import ThreadPoolExecutor
sys.path.insert(0, os.path.dirname(__file__))
from common import DGK, Quota, QuotaExceeded, load_json, save_json, scrub
from permits import call

OUT = "data/state/unit_counts.json"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--since", default="20200101")
    ap.add_argument("--workers", type=int, default=3)
    ap.add_argument("--limit", type=int, default=25000)
    a = ap.parse_args()
    if not DGK:
        print("DATA_GO_KR_KEY 없음"); return
    units = load_json("data/bjd_units.json", [])
    until = dt.date.today().strftime("%Y%m%d")
    st = load_json(OUT, {})
    if st.get("since") != a.since or st.get("complete"):
        st = {"since": a.since, "until": until, "counts": {}, "errors": {}}
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
            st["total"] = sum(st["counts"].values())
            st["n"], st["units"] = len(st["counts"]), len(units)
            save_json(OUT, st)
            print(f"{min(i + 200, len(todo))}/{len(todo)} counted {st['n']} total {st['total']:,} {int(time.time() - t0)}s", flush=True)
            if reason != "done":
                break
    st["complete"] = st["n"] >= len(units)
    st["stop"] = "done" if st["complete"] else reason if reason != "done" else "partial"
    save_json(OUT, st)
    print("stop", st["stop"], "counted", st["n"], "/", len(units), "total", f"{st['total']:,}", "errors", len(st["errors"]))


if __name__ == "__main__":
    main()
