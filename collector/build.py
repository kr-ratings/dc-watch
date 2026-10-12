"""수집 원자료(data/*.json)를 화면용 요약(site/data/dash.json)으로 줄인다."""
import calendar, collections, datetime as dt, json, os, re, sys
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
    if c and c.get("noauto") and not (c.get("mw") or c.get("it")):   # 붙은 기사의 숫자가 다른 사업 것으로 확인된 대지
        return {"none": True, "note": c.get("note") or "공개 자료에서 확인되지 않음", "checked": c.get("checked")}
    if c and (c.get("mw") or c.get("it")):
        return {k: c.get(k) for k in ("mw", "it", "basis", "txt", "note", "conf", "checked")} | {"src": (c.get("src") or [])[:2]}
    auto = cap_from_titles(news)
    if auto:
        return auto
    if c:
        return {"none": True, "note": c.get("note") or "공개 자료에서 확인되지 않음", "checked": c.get("checked")}
    return None


class Geo:
    """법정동 · 리 대표점으로 사업장 위치를 잡는다(코드 → 같은 시 안 같은 동 이름 → 같은 시 · 도 안 같은 동 이름 → 시 · 군 · 구 평균)."""
    def __init__(self):
        self.p = load_json("data/geo_bjd_pts.json", {})
        self.byname = {}
        for k, v in self.p.items():
            if len(k) == 8:
                self.byname.setdefault(v[2], []).append(k)

    def find(self, h):
        sg, bj = str(h.get("sigunguCd") or ""), str(h.get("bjdongCd") or "")
        dong = ((h.get("dongNmAddr") or "").split() or [""])[-1]
        emd = ((h.get("dongNmAddr") or "").split() or [""])[0]
        if bj[3:] not in ("", "00") and sg + bj in self.p:
            return self.p[sg + bj][:2], "ri"
        if sg + bj[:3] in self.p:
            return self.p[sg + bj[:3]][:2], "dong"
        for pre in (sg[:4], sg[:2]):
            ks = [k for k in self.byname.get(emd, []) if k.startswith(pre)]
            if len(ks) == 1:
                return self.p[ks[0]][:2], "dong"
        for pre in (sg, sg[:4]):
            ks = [v for k, v in self.p.items() if len(k) == 8 and k.startswith(pre)]
            if ks:
                return [round(sum(v[0] for v in ks) / len(ks), 5), round(sum(v[1] for v in ks) / len(ks), 5)], "sgg"
        return None, None


class Headroom:
    """한전 '전력공급 여유지도': 시 · 군 · 구별 관할 345kV 변전소와 공급 여유용량(MW)."""
    def __init__(self):
        self.d = load_json("data/kepco_headroom.json", {})
        self.idx = {}
        for sd, gs in (self.d.get("sgg") or {}).items():
            for g, subs in gs.items():
                self.idx[(short(sd), re.sub(r"\s+", "", g))] = subs

    def find(self, sido, sgg):
        sd, g = short(sido), re.sub(r"\s+", "", sgg or "")
        subs = self.idx.get((sd, g))
        if subs is None and g:  # '고양시'처럼 구 없이 들어오면 그 시의 모든 구를 합친다
            subs = {}
            for (s2, g2), v in self.idx.items():
                if s2 == sd and g2.startswith(g.split("시")[0] + "시"):
                    subs.update(v)
            subs = subs or None
        if not subs:
            return None
        return {"subs": subs, "sum": sum(v or 0 for v in subs.values())}

    def summary(self):
        if not self.d:
            return None
        subs = self.d.get("subs", {})
        sido = {}
        for sd, names in (self.d.get("sido") or {}).items():
            k = short(sd)
            sido.setdefault(k, set()).update(names)
        return {"updated": self.d.get("updated"), "subs": subs, "sido": {k: sorted(v) for k, v in sido.items()}}


def permits():
    d = load_json("data/permits.json", {"items": []})
    hr = Headroom()
    geo = Geo()
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
        ll, prec = geo.find(h)
        rows.append({"id": h["mgmPmsrgstPk"], "sd": short(h.get("sido")), "sg": h.get("sggNm"), "dong": h.get("dongNmAddr"), "addr": addr,
                     "nm": nm, "kind": (h.get("archGbCdNm") or "").strip(), "area": round(float(h.get("totArea") or 0)),
                     "dcArea": round(float(h.get("dcFlrArea") or 0)), "plat": round(float(h.get("platArea") or 0)),
                     "vl": h.get("vlRat"), "pms": pms, "stc": stc, "sched": ymd(h.get("stcnsSchedDay")), "apr": apr, "stage": stage,
                     "zone": (h.get("jiyukCdNm") or "").strip(), "crtn": ymd(h.get("crtnDay")),
                     "news": news, "cap": capacity(h, news, cur), "ll": ll, "llp": prec,
                     "site": f"{h.get('sigunguCd')}-{h.get('bjdongCd')}-{h.get('bun')}-{h.get('ji')}",
                     "kc": [short(h.get("sido")), (h.get("sggNm") or "").split()[0] if h.get("sggNm") else ""],
                     "hr": hr.find(h.get("sido"), h.get("sggNm"))})
    rows.sort(key=lambda r: r["pms"] or "", reverse=True)
    tot = collections.Counter(short(u[0]) for u in units)
    done = collections.Counter()
    code2sd = {f"{u[1]}-{u[2]}": short(u[0]) for u in units}
    for k in st.get("done", []):
        done[code2sd.get(k, "?")] += 1
    cov = {sd: [done.get(sd, 0), n] for sd, n in tot.items()}
    uc = load_json("data/state/unit_counts.json", {})
    scanned = {k: uc.get(k) for k in ("since", "until", "total", "n", "units", "complete")} if uc.get("total") else None
    return {"headroom": hr.summary(), "rows": rows, "since": d.get("since"), "updated": d.get("updated"), "coverage": cov, "scanned": scanned, "n_bc": len(d["items"]),
            "pass": st.get("pass", 1), "complete": st.get("complete", False), "last_complete": st.get("last_complete")}


def hours(m):
    y, mo = map(int, m.split("-"))
    return calendar.monthrange(y, mo)[1] * 24


def decomp(k, ms, rows, ops, months_back=36):
    """수도권 최근 1년 증가분을 시 · 군 · 구로 나눠, 데이터센터가 새로 가동된 곳에서 얼마나 나왔는지 계산한다.
    - 대형 시설 신호: 증가 2MW 이상인데 고객 수 증가가 10% 미만(소수 대형 시설이 새로 돈 경우)
    - 데이터센터 확인: 인허가 목록의 준공(최근 36개월) 또는 data/curated/dc_operating.json
    - 행정구역 개편으로 지역 미상('XXX')이 된 곳은 따로 묶는다"""
    if len(ms) < 24:
        return None
    L = len(ms) - 1
    cur, prev = ms[L - 11:L + 1], ms[L - 23:L - 11]
    hc, hp = sum(hours(m) for m in cur), sum(hours(m) for m in prev)
    lim = ms[max(0, L - months_back)]
    agg = {}
    for m in cur + prev:
        for sd, city, kwh, cust in k["ind"][m]["sgg"]:
            sd = short(sd)
            if sd not in CAP:
                continue
            key = (sd, city.split()[0] if city else "")
            a = agg.setdefault(key, {"c": 0, "p": 0, "cn": 0, "pn": 0, "lk": 0, "pk": 0})
            a["c" if m in cur else "p"] += kwh
            if m == ms[L]:
                a["cn"] += cust; a["lk"] += kwh
            if m == ms[L - 12]:
                a["pn"] += cust; a["pk"] += kwh
    dcs = {}
    for r in sorted(rows, key=lambda r: r.get("apr") or ""):
        if r.get("apr") and r["apr"][:7] >= lim and r.get("kc"):
            c = r.get("cap") or {}
            e = dcs.setdefault(tuple(r["kc"]), {}).setdefault(r.get("site"), {"nm": "", "apr0": r["apr"][:7]})
            e.update(nm=e["nm"] or r.get("nm") or "", apr=r["apr"][:7], it=c.get("it"), dong=r.get("dong") or "")
    for v in dcs.values():
        for e in v.values():
            e["nm"] = e["nm"] or e.pop("dong", "")
            e.pop("dong", None)
    for o in ops:
        if o.get("apr", "") >= lim:
            dcs.setdefault((o["sd"], o["sg"]), {})[o["nm"]] = {"nm": o["nm"], "apr": o["apr"], "it": o.get("it"), "u": (o.get("src") or {}).get("u")}
    tot = sum(a["c"] / hc - a["p"] / hp for a in agg.values()) / 1e3
    A, B, C, cn = [], [], 0.0, []
    for key, a in agg.items():
        d = (a["c"] / hc - a["p"] / hp) / 1e3
        if key[1] in ("XXX", "") or a["cn"] == 0 or a["pn"] == 0 or a["lk"] < a["pk"] * 0.2:  # 행정구역 개편 등으로 끊긴 곳
            C += d
            if key[1] not in ("XXX", "") and abs(d) >= 0.5:
                cn.append(f"{key[0]} {key[1]}")
            continue
        cp = (a["cn"] / a["pn"] - 1) * 100
        if d >= 2 and cp < 10:
            x = {"sd": key[0], "sg": key[1], "d": round(d, 1), "cp": round(cp, 1), "now": round(a["c"] / hc / 1e3, 1),
                 "dcs": sorted(dcs.get(key, {}).values(), key=lambda v: v["apr"])}
            (A if x["dcs"] else B).append(x)
    A.sort(key=lambda x: -x["d"]); B.sort(key=lambda x: -x["d"])
    rest = tot - sum(x["d"] for x in A) - sum(x["d"] for x in B) - C
    return {"tot": round(tot, 1), "from": cur[0], "to": cur[-1], "a": A, "b": B, "c": round(C, 1), "cn": cn, "rest": round(rest, 1)}


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
            "price": price, "unit12": unit12, "ict_unit": ict_unit, "hours": [hours(m) for m in ms], "sale_year": {y: dict(v) for y, v in sale_year.items() if months_in_year[y] == 12},
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


def zones():
    z = load_json("data/curated/zones.json", {"items": []})
    pts = load_json("data/geo_bjd_pts.json", {})
    out = []
    for it in z.get("items", []):
        at = it.get("at") or {}
        cand = [v for k, v in pts.items() if len(k) == 8 and k.startswith(at.get("pre", "~")) and (at.get("nm") in ("*", v[2]))]
        if not cand:
            continue
        ll = [round(sum(c[0] for c in cand) / len(cand), 5), round(sum(c[1] for c in cand) / len(cand), 5)]
        out.append({k: it.get(k) for k in ("nm", "sd", "area", "type", "date", "desc", "dc", "src")} | {"ll": ll})
    return {"checked": z.get("checked"), "note": z.get("note"), "items": out}


def main():
    perm = permits()
    kep = kepco()
    raw = load_json("data/kepco.json", {"ind": {}})
    kep["decomp"] = decomp(raw, sorted(m for m, v in raw["ind"].items() if v.get("sido")), perm["rows"],
                           load_json("data/curated/dc_operating.json", {"items": []})["items"])
    out = {"built": dt.datetime.now(dt.timezone(dt.timedelta(hours=9))).strftime("%Y-%m-%d %H:%M"),
           "permits": perm, "kepco": kep, "power": power(kep), "policy": load_json("data/policy.json", {}),
           "timeline": load_json("data/curated/policy_timeline.json", {"items": []}), "zones": zones()}
    out["policy"]["news"] = out["policy"].get("news", [])[:60]
    out["policy"].pop("bills", None)
    save_json("site/data/dash.json", out)
    print("built", len(out["permits"]["rows"]), "dc rows; kepco", kep["latest"], "; self-suff", out["power"]["self_year"], len(out["power"]["self"]))


if __name__ == "__main__":
    main()
