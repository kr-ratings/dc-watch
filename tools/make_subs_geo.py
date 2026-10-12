"""한전 345kV 변전소(공급 여유정보의 변전소 이름)마다 지도 위치를 정한다.
1) OpenStreetMap 변전소 · 발전소 위치(data/osm_subs.json, tools/osm_substations.py로 받음, © OpenStreetMap contributors · ODbL)
2) OSM에 없으면 그 변전소가 맡는 시 · 군 · 구 중 이름이 맞는 곳의 중심(대략 위치로 표시)
결과: data/geo_subs.json  {변전소 묶음 이름: {"ll":[lon,lat], "approx":bool, "members":[{"nm","ll","how"}]}}"""
import json, re, statistics as st

osm = json.load(open("data/osm_subs.json", encoding="utf-8"))
hr = json.load(open("data/kepco_headroom.json", encoding="utf-8"))
units = json.load(open("data/bjd_units.json", encoding="utf-8"))
pts = json.load(open("data/geo_bjd_pts.json", encoding="utf-8"))

def norm(s):
    s = (s or "").replace(" ", "")
    return re.sub(r"(변전소|개폐소|변환소|S/S|\(.*?\))$", "", s)

idx = {}
for o in osm:
    for nm in {o.get("nm"), o.get("nm0")}:
        if nm:
            idx.setdefault(norm(nm), []).append(o)

# 한전 이름 → OSM 이름(발전소 구내 변전소 · 번호 붙은 변전소 · 이름이 다른 곳)
OSM_NAME = {"평택T/P": "평택화력발전소", "태안T/P": "태안화력발전소", "여수T/P": "여수화력발전소", "울산T/P": "울산화력발전소",
            "삼척G/P": "삼척그린파워발전소", "인천C/C": "인천복합화력발전소", "안동C/C": "안동복합화력발전소",
            "서서울1": "서서울", "서서울2": "서서울", "신성남1": "신성남", "신성남2": "신성남", "신시흥1": "신시흥", "신시흥2": "신시흥",
            "신문래": "문래", "신경서": "경서", "제주동부": "동제주", "제주서부": "서제주"}
# OSM에 없을 때 쓸 시 · 군 · 구(관할 목록 중 동 이름이 들어 있는 곳)
SGG = {"갈산": ("인천광역시", "부평구"), "신대연": ("부산광역시", "남구"), "북대구": ("대구광역시", "북구"), "신가좌": ("인천광역시", "서해구"),
       "남청주": ("충청북도", "청주시 서원구"), "중부": ("서울특별시", "중구"), "제주남부": ("제주특별자치도", "서귀포시"), "제주북부": ("제주특별자치도", "제주시")}

DONG = {"신가좌": ("28", "가좌동")}   # 행정구역 개편으로 시 · 군 · 구 코드가 바뀐 곳은 동 이름으로


def dong_pt(pre, nm):
    c = [v for k, v in pts.items() if len(k) == 8 and k.startswith(pre) and v[2] == nm]
    return [round(c[0][0], 5), round(c[0][1], 5)] if c else None


def sgg_center(sd, sg):
    codes = {u[1] for u in units if u[0] == sd and (u[3] or "").replace(" ", "") == sg.replace(" ", "")}
    xs = [v for k, v in pts.items() if len(k) == 8 and k[:5] in codes]
    return [round(st.mean(p[0] for p in xs), 5), round(st.mean(p[1] for p in xs), 5)] if xs else None

out, miss = {}, []
for grp in hr["subs"]:
    mem = []
    for p in [x.strip() for x in grp.split(",")]:
        q = OSM_NAME.get(p, p)
        c = idx.get(norm(q), [])
        best = [o for o in c if re.search(r"345000|765000", o.get("v") or "")] or [o for o in c if o["t"] == "substation"] or c
        if best:
            mem.append({"nm": p, "ll": [best[0]["lon"], best[0]["lat"]], "how": "osm" if p not in ("신문래", "신경서") else "osm-near"})
        elif p in DONG and dong_pt(*DONG[p]):
            mem.append({"nm": p, "ll": dong_pt(*DONG[p]), "how": "dong"})
        elif p in SGG and sgg_center(*SGG[p]):
            mem.append({"nm": p, "ll": sgg_center(*SGG[p]), "how": "sgg"})
        else:
            miss.append(p)
    if mem:
        out[grp] = {"ll": [round(st.mean(m["ll"][0] for m in mem), 5), round(st.mean(m["ll"][1] for m in mem), 5)],
                    "approx": any(m["how"] != "osm" for m in mem), "members": mem}
json.dump(out, open("data/geo_subs.json", "w", encoding="utf-8"), ensure_ascii=False, indent=0)
print("placed", len(out), "/", len(hr["subs"]), "approx", sum(v["approx"] for v in out.values()), "missing", miss)
