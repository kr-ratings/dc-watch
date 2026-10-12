"""수집 원자료(data/*.json)를 화면용 요약(site/data/dash.json)으로 줄인다."""
import collections, datetime as dt, json, os, re, sys
sys.path.insert(0, os.path.dirname(__file__))
from common import load_json, save_json

SHORT = [("서울", "서울"), ("부산", "부산"), ("대구", "대구"), ("인천", "인천"), ("광주", "전남광주"), ("전남광주", "전남광주"), ("전라남", "전남광주"), ("전남", "전남광주"),
         ("대전", "대전"), ("울산", "울산"), ("세종", "세종"), ("경기", "경기"), ("강원", "강원"), ("충청북", "충북"), ("충청남", "충남"),
         ("전라북", "전북"), ("전북", "전북"), ("경상북", "경북"), ("경상남", "경남"), ("제주", "제주")]
CAP = {"서울", "인천", "경기"}


def short(s):
    s = str(s or "")
    for a, b in SHORT:
        if s.startswith(a):
            return b
    return s


def ymd(s):
    s = str(s or "").strip()
    return f"{s[:4]}-{s[4:6]}-{s[6:8]}" if re.fullmatch(r"\d{8}", s) else None


MWRE = re.compile(r"(IT\s*(?:로드|load|부하|용량)?\s*)?(\d+(?:\.\d+)?)\s*(MW|㎿|메가와트|GW|기가와트)", re.I)


def cap_from_titles(news):
    """큐레이션 값이 없는 건은 연결된 기사 제목에 나온 MW 숫자를 쓴다(기준 미표기로 표시)."""
    for a in news:
        for m in MWRE.finditer(a.get("t", "")):
            v = float(m.group(2)) * (1000 if m.group(3).upper() in ("GW", "기가와트") else 1)
            if not 0 < v <= 5000:
                continue
            it = bool(m.group(1))
            return {"mw": None if it else v, "it": v if it else None, "basis": "IT" if it else "미표기", "auto": True,
                    "note": "연결된 기사 제목에서 자동으로 읽은 값", "src": [{"t": a["t"], "u": a["u"], "d": a["d"], "o": a.get("src", "")}]}
    return None


def capacity(h, news, cur):
    c = cur.get(f"{h.get('sigunguCd')}-{h.get('bjdongCd')}-{h.get('bun')}-{h.get('ji')}")
    if c and (c.get("mw") or c.get("it")):
        return {k: c.get(k) for k in ("mw", "it", "basis", "txt", "note", "conf", "checked")} | {"src": (c.get("src") or [])[:2]}
    auto = cap_from_titles(news)
    if auto:
        return auto
    if c:
        return {"none": True, "note": c.get("note") or "공개 자료에서 확인되지 않음", "checked": c.get("checked")}
    return None


def permits():
    d = load_json("data/permits.json", {"items": []})
    cur = load_json("data/curated/capacity.json", {})
    st = load_json("data/state/permit_scan.json", {})
    units = load_json("data/bjd_units.json", None) or load_json("data/bjd_units_seed.json", [])
    pn = load_json("data/permit_news.json", {})
    rows = []
    for h in d["items"]:
        if not h.get("dc"):
            continue
        nm = (h.get("bldNm") or "").strip()
        if re.fullmatch(r"[\d\-\s번지]+", nm or "") or nm in ("", "-"):
            nm = ""
        pms, stc, apr = ymd(h.get("archPmsDay")), ymd(h.get("realStcnsDay")), ymd(h.get("useAprDay"))
        stage = "준공" if apr else ("공사 중" if stc else "착공 전")
        addr = re.sub(r"\s+", " ", (h.get("platPlc") or "").replace("번지", "")).strip()
        news = [{k: a[k] for k in ("t", "src", "d", "u")} for a in (pn.get(str(h["mgmPmsrgstPk"]), {}).get("items") or [])]
        rows.append({"id": h["mgmPmsrgstPk"], "sd": short(h.get("sido")), "sg": h.get("sggNm"), "dong": h.get("dongNmAddr"), "addr": addr,
                     "nm": nm, "kind": (h.get("archGbCdNm") or "").strip(), "area": round(float(h.get("totArea") or 0)),
                     "dcArea": round(float(h.get("dcFlrArea") or 0)), "plat": round(float(h.get("platArea") or 0)),
                     "vl": h.get("vlRat"), "pms": pms, "stc": stc, "sched": ymd(h.get("stcnsSchedDay")), "apr": apr, "stage": stage,
                     "zone": (h.get("jiyukCdNm") or "").strip(), "crtn": ymd(h.get("crtnDay")),
                     "news": news, "cap": capacity(h, news, cur)})
    rows.sort(key=lambda r: r["pms"] or "", reverse=True)
    tot = collections.Counter(short(u[0]) for u in units)
    done = collections.Counter()
    code2sd = {f"{u[1]}-{u[2]}": short(u[0]) for u in units}
    for k in st.get("done", []):
        done[code2sd.get(k, "?")] += 1
    cov = {sd: [done.get(sd, 0), n] for sd, n in tot.items()}
    return {"rows": rows, "since": d.get("since"), "updated": d.get("updated"), "coverage": cov,
            "pass": st.get("pass", 1), "complete": st.get("complete", False), "last_complete": st.get("last_complete")}


def kepco():
    k = load_json("data/kepco.json", {"ind": {}, "cntr": {}})
    ms = sorted(m for m, v in k["ind"].items() if v.get("sido"))
    sido_series = {}
    for m in ms:
        for sd, v in k["ind"][m]["sido"].items():
            sido_series.setdefault(short(sd), {})[m] = v
    nat = {m: sum(k["ind"][m]["sido"].values()) for m in ms}
    last12, prev12 = ms[-12:], ms[-24:-12]
    agg = collections.defaultdict(lambda: [0, 0, 0])
    for i, m in enumerate(ms[-24:]):
        for sd, city, kwh, cust in k["ind"][m]["sgg"]:
            if city in ("XXX", "", "전체"):
                continue
            key = (short(sd), city.split()[0])
            agg[key][0 if m in last12 else 1] += kwh
            if m == ms[-1]:
                agg[key][2] += cust
    lastm = collections.Counter()
    for sd, city, kwh, cust in (k["ind"][ms[-1]]["sgg"] if ms else []):
        lastm[(short(sd), city.split()[0])] += kwh
    sgg = []
    for (a, b), v in agg.items():
        if v[0] <= 0:
            continue
        gap = lastm.get((a, b), 0) < v[0] / 12 * 0.05  # 최근 달 값이 비정상적으로 작으면(행정구역 개편 등) 자료 공백 표시
        sgg.append({"sd": a, "sg": b, "k12": v[0], "p12": v[1], "cust": v[2], "gap": gap})
    sgg.sort(key=lambda x: -x["k12"])
    cm = sorted(k["cntr"])
    price = {m: {c: k["cntr"][m]["nat"].get(c, {}).get("unit") for c in ("일반용", "산업용", "주택용")} for m in cm}

    def shift(m, k):
        y, mo = map(int, m.split("-"))
        t = y * 12 + mo - 1 - k
        return f"{t // 12}-{t % 12 + 1:02d}"

    def u12(c, back=0):  # 12개월 가중평균 판매단가(요금 합 ÷ 사용량 합), back개월 전 같은 구간
        if not cm:
            return None
        w = [shift(cm[-1], back + i) for i in range(11, -1, -1)]
        have = [m for m in w if m in k["cntr"]]
        if len(have) < 10:
            return None
        kwh = sum(k["cntr"][m]["nat"].get(c, {}).get("kwh", 0) for m in have)
        won = sum(k["cntr"][m]["nat"].get(c, {}).get("won", 0) for m in have)
        return {"v": round(won / kwh, 1) if kwh else None, "from": w[0], "to": w[-1]}
    unit12 = {c: {"cur": u12(c), "y3": u12(c, 36), "y5": u12(c, 60)} for c in ("일반용", "산업용")}
    ict_unit = None  # 정보통신업 자체 요금 자료가 들어오면 실제 평균 단가
    jw = [(k["ind"][m].get("won", 0), sum(k["ind"][m]["sido"].values()), m) for m in ms[-12:] if k["ind"][m].get("won")]
    if jw:
        ict_unit = {"v": round(sum(w for w, _, _ in jw) / sum(v for _, v, _ in jw), 1), "from": jw[0][2], "to": jw[-1][2], "n": len(jw)}
    sale_year = collections.defaultdict(lambda: collections.Counter())
    for m in cm:
        for sd, v in k["cntr"][m].get("sido_sale", {}).items():
            sale_year[m[:4]][short(sd)] += v
    months_in_year = collections.Counter(m[:4] for m in cm)
    return {"months": ms, "nat": [nat[m] for m in ms], "sido": {sd: [s.get(m) for m in ms] for sd, s in sido_series.items()},
            "price": price, "unit12": unit12, "ict_unit": ict_unit, "sale_year": {y: dict(v) for y, v in sale_year.items() if months_in_year[y] == 12},
            "latest": ms[-1] if ms else None, "updated": k.get("updated")}


def power(kep):
    p = load_json("data/power_open.json", {})
    gen = {y: {short(s): v for s, v in row.items()} for y, row in p.get("gen_sido_mwh", {}).items()}
    # 광주·전남 합산
    for y, row in gen.items():
        if "전남광주" not in row:
            pass
    gen2 = {}
    for y, row in p.get("gen_sido_mwh", {}).items():
        r = collections.Counter()
        for s, v in row.items():
            r[short(s)] += v
        gen2[y] = dict(r)
    self_suf = {}
    years = sorted(set(gen2) & set(kep["sale_year"]))
    if years:
        y = years[-1]
        for sd, sale_kwh in kep["sale_year"][y].items():
            g = gen2[y].get(sd)
            if g and sale_kwh:
                self_suf[sd] = round(g * 1000 / sale_kwh * 100, 1)
    return {"smp": p.get("smp", {}), "gen": gen2, "self": self_suf, "self_year": years[-1] if years else None, "updated": p.get("updated")}


def main():
    kep = kepco()
    out = {"built": dt.datetime.now(dt.timezone(dt.timedelta(hours=9))).strftime("%Y-%m-%d %H:%M"),
           "permits": permits(), "kepco": kep, "power": power(kep), "policy": load_json("data/policy.json", {}),
           "timeline": load_json("data/curated/policy_timeline.json", {"items": []})}
    out["policy"]["news"] = out["policy"].get("news", [])[:60]
    out["policy"].pop("bills", None)
    save_json("site/data/dash.json", out)
    print("built", len(out["permits"]["rows"]), "dc rows; kepco", kep["latest"], "; self-suff", out["power"]["self_year"], len(out["power"]["self"]))


if __name__ == "__main__":
    main()
