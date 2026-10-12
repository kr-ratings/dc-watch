"""국내에 닿는 국제 해저케이블 경로와 육양국 — TeleGeography Submarine Cable Map 공개 API.
데이터 라이선스: CC BY-NC-SA 3.0 (TeleGeography). 지도 범위(한반도 주변)만 잘라 저장한다.
결과: data/cables.json"""
import datetime as dt, json, math, os, sys
sys.path.insert(0, os.path.dirname(__file__))
from common import get, save_json

API = "https://www.submarinecablemap.com/api/v3"
BOX = (121.5, 30.5, 133.5, 40.0)          # lon0, lat0, lon1, lat1
KO = {"busan-south-korea": "부산", "geoje-south-korea": "거제", "shindu-ri-south-korea": "태안 신두리", "gunsan-south-korea": "군산(새만금)",
      "hosan-ri-south-korea": "삼척 호산", "ulleung-south-korea": "울릉", "goseong-ri-south-korea": "제주 고성", "mijo-myeon-south-korea": "남해 미조",
      "goheung-south-korea": "고흥", "udo-south-korea": "우도"}


CN = {"Japan": "일본", "China": "중국", "Taiwan": "대만", "United States": "미국", "Philippines": "필리핀", "Malaysia": "말레이시아", "Singapore": "싱가포르",
      "Vietnam": "베트남", "Thailand": "태국", "Indonesia": "인도네시아", "Hong Kong": "홍콩", "Brunei": "브루나이", "Guam": "괌"}


def inside(p):
    return BOX[0] <= p[0] <= BOX[2] and BOX[1] <= p[1] <= BOX[3]


def clip(line):
    runs, cur = [], []
    for i, p in enumerate(line):
        if inside(p):
            if not cur and i > 0:
                cur.append(line[i - 1])
            cur.append(p)
        elif cur:
            cur.append(p); runs.append(cur); cur = []
    if cur:
        runs.append(cur)
    out = []
    for r in runs:      # 0.02도보다 가까운 점은 줄인다
        s = [r[0]]
        for p in r[1:-1]:
            if math.hypot(p[0] - s[-1][0], p[1] - s[-1][1]) >= 0.02:
                s.append(p)
        s.append(r[-1])
        out.append([[round(x, 3), round(y, 3)] for x, y in s])
    return out


def main():
    lp = get(API + "/landing-point/landing-point-geo.json", {}).json()
    kr = {f["properties"]["id"]: f["geometry"]["coordinates"] for f in lp["features"] if f["properties"]["id"].endswith("-south-korea")}
    cab = {}
    for lid in kr:
        for c in get(f"{API}/landing-point/{lid}.json", {}).json().get("cables", []):
            cab[c["id"]] = c
    intl = {k: v for k, v in cab.items() if any(not x.endswith("-south-korea") for x in v.get("landing_points", []))}
    geo = get(API + "/cable/cable-geo.json", {}).json()
    paths = {}
    for f in geo["features"]:
        cid = f["properties"]["id"]
        if cid in intl:
            g = f["geometry"]; lines = g["coordinates"] if g["type"] == "MultiLineString" else [g["coordinates"]]
            for ln in lines:
                paths.setdefault(cid, []).extend(clip(ln))
    cables = []
    for cid, c in sorted(intl.items(), key=lambda kv: (kv[1].get("rfs_year") or 9999)):
        d = get(f"{API}/cable/{cid}.json", {}).json()
        cables.append({"id": cid, "nm": c["name"], "rfs": c.get("rfs_year"), "planned": bool(c.get("is_planned")),
                       "owners": d.get("owners") or "", "len": d.get("length") or "",
                       "kr": [x for x in c.get("landing_points", []) if x.endswith("-south-korea")],
                       "to": sorted({CN.get(x.get("country"), x.get("country")) for x in d.get("landing_points", []) if x.get("country") and x.get("country") != "South Korea"}),
                       "paths": paths.get(cid, [])})
    lands = []
    for lid, ll in kr.items():
        cs = [c["id"] for c in cables if lid in c["kr"]]
        if cs:
            lands.append({"id": lid, "nm": KO.get(lid, lid), "ll": [round(ll[0], 4), round(ll[1], 4)], "cables": cs})
    save_json("data/cables.json", {"updated": dt.date.today().isoformat(), "src": "TeleGeography Submarine Cable Map (CC BY-NC-SA 3.0)",
                                   "cables": cables, "landings": lands})
    print("cables", len(cables), "landings", [(l["nm"], len(l["cables"])) for l in lands])


if __name__ == "__main__":
    main()
