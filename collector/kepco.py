"""한전 전력데이터 개방포털: 정보통신업 전력사용량(시·군·구, 월) · 계약종별 평균판매단가(월)."""
import datetime as dt, json, time
from common import KEPCO, get, load_json, save_json

KB = "https://bigdata.kepco.co.kr/openapi/v1/"
OUT = "data/kepco.json"


def multi_json(text):
    """응답이 {"totData":[...]}{"data":[...]} 처럼 두 덩어리로 붙어 오는 경우가 있어 모두 합친다."""
    dec, i, out = json.JSONDecoder(strict=False), 0, {}
    text = text.strip()
    while i < len(text):
        obj, j = dec.raw_decode(text, i)
        if isinstance(obj, dict):
            for k, v in obj.items():
                out.setdefault(k, v)
        i = j
        while i < len(text) and text[i] in " \r\n\t":
            i += 1
    return out


def kcall(path, **p):
    q = {"apiKey": KEPCO, "returnType": "json"}
    q.update(p)
    r = get(KB + path, q)
    if r.status_code == 404:
        return None
    return multi_json(r.text)


def metro_norm(m):
    m = str(m or "")
    if m.startswith(("광주", "전라남", "전남")):
        return "전남광주"
    for a, b in [("서울", "서울"), ("부산", "부산"), ("대구", "대구"), ("인천", "인천"), ("대전", "대전"), ("울산", "울산"), ("세종", "세종"),
                 ("경기", "경기"), ("강원", "강원"), ("충청북", "충북"), ("충청남", "충남"), ("전라북", "전북"), ("전북", "전북"),
                 ("경상북", "경북"), ("경상남", "경남"), ("제주", "제주")]:
        if m.startswith(a):
            return b
    return m


def months(start="2016-01"):
    y, m = map(int, start.split("-"))
    today = dt.date.today()
    while (y, m) <= (today.year, today.month):
        yield f"{y}-{m:02d}"
        m += 1
        if m == 13:
            y, m = y + 1, 1


def collect():
    if not KEPCO:
        print("KEPCO_API_KEY 없음"); return
    d = load_json(OUT, {"ind": {}, "cntr": {}})
    ms = list(months())
    have = sorted(d["ind"].keys())
    recent = set(ms[-4:])  # 최근 몇 달은 다시 확인
    calls = 0
    for ym in ms:
        if ym in d["ind"] and d["ind"][ym].get("sido") and ym not in recent:
            continue
        y, m = ym.split("-")
        j = kcall("powerUsage/industryType.do", year=y, month=m, bizCd="J")
        calls += 1
        if not j or not j.get("data"):
            continue
        sido, sgg = {}, []
        for x in j["data"]:
            bz = str(x.get("biz", "")).replace(" ", "")
            if not ("정보통신" in bz or ("방송통신" in bz and "정보서비스" in bz)):
                continue
            mt, kwh, cust = metro_norm(x.get("metro")), int(x.get("powerUsage") or 0), int(x.get("custCnt") or 0)
            sido[mt] = sido.get(mt, 0) + kwh
            sgg.append([mt, str(x.get("city", "")).strip(), kwh, cust])
        nat = {str(x.get("biz", "")).strip(): int(x.get("powerUsage") or 0) for x in (j.get("totData") or [])}
        d["ind"][ym] = {"sido": sido, "sgg": sgg, "nat": nat}
        c = kcall("powerUsage/contractType.do", year=y, month=m)
        calls += 1
        if c:
            tot = {str(x.get("cntr", "")).replace(" ", ""): {"kwh": int(x.get("powerUsage") or 0), "won": int(x.get("bill") or 0), "unit": x.get("unitCost"), "kw": x.get("cntrPwr")}
                   for x in (c.get("totData") or [])}
            sale = {}
            for x in (c.get("data") or []):
                mt = metro_norm(x.get("metro"))
                sale[mt] = sale.get(mt, 0) + int(x.get("powerUsage") or 0)
            d["cntr"][ym] = {"nat": tot, "sido_sale": sale}
        time.sleep(0.3)
    d["updated"] = dt.date.today().isoformat()
    d["latest"] = max(d["ind"]) if d["ind"] else None
    save_json(OUT, d)
    print("kepco calls", calls, "latest", d["latest"], "months", len(d["ind"]))


if __name__ == "__main__":
    collect()
