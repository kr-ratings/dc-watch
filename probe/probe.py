"""수집 가능 여부 시험(임시). 결과는 probe/out/result.json 에 저장한다. 키 값은 결과·로그에 남기지 않는다."""
import json, os, re, time, traceback
import requests

K = os.environ.get("DATA_GO_KR_KEY", "").strip()
KE = os.environ.get("KEPCO_API_KEY", "").strip()
S = requests.Session()
S.headers["User-Agent"] = "Mozilla/5.0 (dc-watch probe)"
OUT = {"keys": {"data_go_kr": bool(K), "kepco": bool(KE)}}


def scrub(s):
    s = str(s)
    for k in (K, KE):
        if k:
            s = s.replace(k, "***")
    return re.sub(r"(serviceKey|apiKey)=[^&\s']+", r"\1=***", s)


def rec(name, fn):
    t = time.time()
    try:
        OUT[name] = {"ok": True, "res": fn()}
    except Exception as e:  # noqa
        OUT[name] = {"ok": False, "err": scrub(repr(e))[:600], "tb": scrub(traceback.format_exc())[-800:]}
    OUT[name]["sec"] = round(time.time() - t, 2)
    print(name, OUT[name]["ok"], OUT[name]["sec"], flush=True)


# ── 건축HUB ──
HUB = "https://apis.data.go.kr/1613000/ArchPmsHubService/"
BR = "https://apis.data.go.kr/1613000/BldRgstHubService/"


def dgk(base, op, **p):
    q = {"serviceKey": K, "_type": "json", "numOfRows": 100, "pageNo": 1}
    q.update(p)
    r = None
    for i in range(4):
        try:
            r = S.get(base + op, params=q, timeout=(20, 90))
            break
        except requests.exceptions.RequestException:
            if i == 3:
                raise
            time.sleep(5 * (i + 1))
    txt = r.text
    try:
        j = r.json()
    except Exception:
        return {"status": r.status_code, "raw": scrub(txt[:400])}
    body = (j.get("response") or {}).get("body") or {}
    head = (j.get("response") or {}).get("header") or j.get("OpenAPI_ServiceResponse") or {}
    items = (body.get("items") or {})
    items = items.get("item", []) if isinstance(items, dict) else []
    if isinstance(items, dict):
        items = [items]
    return {"status": r.status_code, "head": head, "total": body.get("totalCount"), "n": len(items), "items": items}


KEEP = ["platPlc", "bldNm", "mainPurpsCd", "mainPurpsCdNm", "etcPurps", "archGbCdNm", "totArea", "platArea",
        "archPmsDay", "stcnsSchedDay", "realStcnsDay", "useAprDay", "crtnDay", "dongNm", "flrNoNm", "flrGbCdNm", "pmsDay", "stcnsDay"]


def slim(items, n=8):
    return [{k: it.get(k) for k in KEEP if k in it} for it in items[:n]]


SITES = [  # 공개 보도된 데이터센터 소재지(시험용)
    ("하남 풍산동 607-2", "41450", "11000", "0607", "0002"),
    ("구로 개봉동 166-2", "11530", "10700", "0166", "0002"),
    ("안산 단원구 성곡동 670-4", "41273", "10400", "0670", "0004"),
    ("금천 가산동 319-19", "11545", "10100", "0319", "0019"),
]


def t_sites():
    res = {}
    for nm, sg, bd, bun, ji in SITES:
        a = dgk(HUB, "getApBasisOulnInfo", sigunguCd=sg, bjdongCd=bd, bun=bun, ji=ji)
        d = dgk(HUB, "getApDongOulnInfo", sigunguCd=sg, bjdongCd=bd, bun=bun, ji=ji)
        f = dgk(HUB, "getApFlrOulnInfo", sigunguCd=sg, bjdongCd=bd, bun=bun, ji=ji)
        b = dgk(BR, "getBrTitleInfo", sigunguCd=sg, bjdongCd=bd, bun=bun, ji=ji)
        res[nm] = {
            "basis": {"head": a.get("head"), "total": a.get("total"), "items": slim(a.get("items", [])), "raw": a.get("raw")},
            "dong": {"total": d.get("total"), "items": slim(d.get("items", []))},
            "flr": {"total": f.get("total"), "items": slim(f.get("items", []), 6)},
            "title": {"head": b.get("head"), "total": b.get("total"), "items": slim(b.get("items", [])), "raw": b.get("raw")},
        }
    return res


def t_scan_cost():
    res = {}
    for nm, sg, bd in [("하남 풍산동", "41450", "11000"), ("안산 성곡동", "41273", "10400"), ("서울 역삼동", "11680", "10100")]:
        a = dgk(HUB, "getApBasisOulnInfo", sigunguCd=sg, bjdongCd=bd, numOfRows=1)
        big = dgk(HUB, "getApBasisOulnInfo", sigunguCd=sg, bjdongCd=bd, numOfRows=1000)
        dt = dgk(HUB, "getApBasisOulnInfo", sigunguCd=sg, bjdongCd=bd, numOfRows=1, startDate="20250101", endDate="20261012")
        res[nm] = {"total": a.get("total"), "rows_when_1000": big.get("n"), "head": a.get("head"),
                   "total_with_startDate": dt.get("total"), "head_dt": dt.get("head")}
    return res


def t_dong_filter():
    """동 하나를 끝까지 받아 방송통신시설 건을 골라 본다."""
    res = {}
    for nm, sg, bd in [("하남 풍산동", "41450", "11000"), ("안산 성곡동", "41273", "10400")]:
        allit, page = [], 1
        while page <= 30:
            a = dgk(HUB, "getApBasisOulnInfo", sigunguCd=sg, bjdongCd=bd, numOfRows=1000, pageNo=page)
            its = a.get("items", [])
            allit += its
            if not its or len(allit) >= (a.get("total") or 0):
                break
            page += 1
        hit = [it for it in allit if "방송" in str(it.get("mainPurpsCdNm")) or "데이터" in str(it.get("bldNm"))]
        purp = {}
        for it in allit:
            purp[str(it.get("mainPurpsCdNm"))] = purp.get(str(it.get("mainPurpsCdNm")), 0) + 1
        res[nm] = {"pages": page, "n": len(allit), "hits": slim(hit, 20), "purp_top": sorted(purp.items(), key=lambda x: -x[1])[:12]}
    return res


# ── 한전 ──
KB = "https://bigdata.kepco.co.kr/openapi/v1/"


def kep(path, **p):
    q = {"apiKey": KE, "returnType": "json"}
    q.update(p)
    r = S.get(KB + path, params=q, timeout=(20, 90))
    try:
        return r.status_code, json.loads(r.text, strict=False)
    except Exception:
        return r.status_code, {"raw": scrub(r.text[:400])}


def t_kepco():
    res = {"latest": None}
    for y, m in [(2026, 9), (2026, 8), (2026, 7), (2026, 6), (2026, 5), (2026, 4), (2026, 3)]:
        st, j = kep("powerUsage/industryType.do", year=str(y), month=f"{m:02d}", metroCd="41", bizCd="J")
        data = j.get("data") or j.get("totData") or []
        res.setdefault("tries", []).append({"ym": f"{y}-{m:02d}", "status": st, "n": len(data) if isinstance(data, list) else 0,
                                            "err": {k: v for k, v in j.items() if k not in ("data", "totData")} if isinstance(j, dict) else None})
        if data:
            res["latest"] = f"{y}-{m:02d}"
            res["gg_J_sample"] = data[:6]
            break
    if res["latest"]:
        y, m = res["latest"].split("-")
        st, j = kep("powerUsage/industryType.do", year=y, month=m, bizCd="J")
        res["all_J"] = {"status": st, "keys": list(j.keys()), "tot": (j.get("totData") or [])[:20], "n_data": len(j.get("data") or [])}
        st, j = kep("change/custNum/industryType.do", year=y, month=m, metroCd="41", bizCd="J")
        res["cust_gg_J"] = {"status": st, "data": (j.get("data") or [])[:8], "other": {k: v for k, v in j.items() if k != "data"}}
        st, j = kep("powerUsage/contractType.do", year=y, month=m)
        res["contract_all"] = {"status": st, "tot": (j.get("totData") or [])[:15], "other": {k: v for k, v in j.items() if k not in ("totData", "data")}}
    return res


# ── 키 없는 원자료 ──
def t_open():
    res = {}

    def safe(name, fn):
        try:
            res[name] = fn()
        except Exception as e:
            res[name] = {"err": scrub(repr(e))[:300]}

    def kpx():
        r = S.get("https://new.kpx.or.kr/smpMonthly.es?mid=a10606080300&device=pc", timeout=(20, 60))
        i = r.text.find("2026")
        return {"status": r.status_code, "len": len(r.text), "sample": re.sub(r"\s+", " ", r.text[i:i + 300]) if i > 0 else None}

    def epsis():
        r = S.get("https://epsis.kpx.or.kr/epsisnew/selectEkgeGepGbaChart.do?menuId=060104", timeout=(20, 60))
        i = r.text.find("gridData")
        j = r.text.find("강원")
        return {"status": r.status_code, "len": len(r.text), "grid": re.sub(r"\s+", " ", r.text[i:i + 600]) if i > 0 else None,
                "snip": re.sub(r"\s+", " ", r.text[j - 300:j + 300]) if j > 0 else None,
                "ajax": re.findall(r"url\s*:\s*[\"']([^\"']+)", r.text)[:10]}

    def assembly():
        r = S.get("https://open.assembly.go.kr/portal/openapi/nzmimeepazxkubdpn", params={"Type": "json", "pIndex": 1, "pSize": 20, "AGE": 22, "BILL_NAME": "데이터센터"}, timeout=(20, 60))
        j = r.json()["nzmimeepazxkubdpn"]
        return {"status": r.status_code, "count": j[0]["head"][0]["list_total_count"], "names": [x["BILL_NAME"] + " / " + str(x["PROC_RESULT"]) for x in j[1]["row"]]}

    def gnews():
        r = S.get("https://news.google.com/rss/search", params={"q": "데이터센터 PF OR 착공 OR 인수 OR 매각", "hl": "ko", "gl": "KR", "ceid": "KR:ko"}, timeout=(20, 60))
        return {"status": r.status_code, "items": r.text.count("<item>"), "titles": re.findall(r"<title>(.*?)</title>", r.text)[1:6]}

    for nm, fn in [("kpx_smp", kpx), ("epsis_region_gen", epsis), ("assembly", assembly), ("gnews", gnews)]:
        safe(nm, fn)
    return res


if __name__ == "__main__":
    if os.environ.get("PROBE_MODE") == "reach":
        rec("reach", t_reach)
        os.makedirs("probe/out", exist_ok=True)
        with open("probe/out/result.json", "w", encoding="utf-8") as f:
            f.write(scrub(json.dumps(OUT, ensure_ascii=False, indent=1)))
        raise SystemExit(0)
    if K:
        rec("hub_sites", t_sites)
        rec("hub_scan_cost", t_scan_cost)
        rec("hub_dong_filter", t_dong_filter)
    if KE:
        rec("kepco", t_kepco)
    rec("open_sources", t_open)
    os.makedirs("probe/out", exist_ok=True)
    with open("probe/out/result.json", "w", encoding="utf-8") as f:
        f.write(scrub(json.dumps(OUT, ensure_ascii=False, indent=1)))
    print("done")
