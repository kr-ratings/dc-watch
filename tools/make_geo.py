"""지도용 정적 자료를 만든다(경계는 거의 바뀌지 않아 행정구역 개편 때만 다시 실행).

입력(공개 자료):
  1) 행정동 경계  : github.com/vuski/admdongkor  HangJeongDong_verYYYYMMDD.geojson (통계청 SGIS 공공누리 1유형 · CC BY 4.0)
  2) 북한 윤곽    : npm world-atlas@2 countries-50m.json (Natural Earth, 퍼블릭 도메인)
  3) 법정동 · 리 경계: gisdeveloper.co.kr 행정구역 SHP(도로명주소 DB 행정구역도 기반) emd_YYYYMMDD · li_YYYYMMDD (EPSG:5179)
출력:
  site/data/geo.json      시 · 도 / 수도권 시 · 군 · 구 경계(투영 좌표 경로), 북한 윤곽, 울릉도 · 독도, 지명 위치
  data/geo_bjd_pts.json   법정동(8자리) · 리(10자리) 코드별 대표점 [경도, 위도, 이름]
사용: python3 tools/make_geo.py <admdongkor.geojson> <countries-50m.json> <emd·li SHP 폴더(emd/emd.shp, li/li.shp)>
"""
import json, math, re, sys
from shapely.geometry import shape, Polygon, MultiPolygon, box, mapping
from shapely.ops import unary_union, transform

LON0, LAT0, KX = 124.0, 39.0, math.cos(math.radians(36.5)) * 1000


def proj(lon, lat):
    return ((lon - LON0) * KX, (LAT0 - lat) * 1000)


def P(g):
    return transform(lambda x, y, z=None: proj(x, y), g)  # noqa (shapely 2: ops.transform 경고는 무시)


def polys(g):
    return list(g.geoms) if isinstance(g, MultiPolygon) else [g] if isinstance(g, Polygon) else [p for x in getattr(g, "geoms", []) for p in polys(x)]


def path(g, tol, min_area):
    out = []
    for p in polys(g):
        if p.area < min_area:
            continue
        p = p.simplify(tol, preserve_topology=True)
        for ring in [p.exterior] + ([] if min_area > 300 else list(p.interiors)):
            pts = [(round(x), round(y)) for x, y in ring.coords]
            ded = [pts[0]] + [q for a, q in zip(pts, pts[1:]) if q != a]
            if len(ded) < 4:
                continue
            s = f"M{ded[0][0]} {ded[0][1]}l" + " ".join(f"{b[0]-a[0]} {b[1]-a[1]}" for a, b in zip(ded, ded[1:-1])) + "z"
            out.append(s)
    return "".join(out)


SHORT = {"서울특별시": "서울", "부산광역시": "부산", "대구광역시": "대구", "인천광역시": "인천", "대전광역시": "대전", "울산광역시": "울산",
         "세종특별자치시": "세종", "경기도": "경기", "강원특별자치도": "강원", "충청북도": "충북", "충청남도": "충남", "전북특별자치도": "전북",
         "전남광주통합특별시": "전남광주", "광주광역시": "광주", "전라남도": "전남", "경상북도": "경북", "경상남도": "경남", "제주특별자치도": "제주"}


def main(adm, wa, shp):
    feats = json.load(open(adm, encoding="utf-8"))["features"]
    by_sido, by_sgg, ul = {}, {}, []
    for f in feats:
        p, g = f["properties"], shape(f["geometry"]).buffer(0)
        if p["sggnm"] == "울릉군":
            ul.append(g); continue
        by_sido.setdefault(p["sidonm"], []).append(g)
        if p["sido"] in ("11", "28", "41"):
            by_sgg.setdefault((p["sidonm"], p["sggnm"]), []).append(g)
    out = {"proj": {"lon0": LON0, "lat0": LAT0, "kx": KX}, "sido": [], "sgg": [], "lab": [], "src": adm.split("/")[-1]}
    for nm, gs in by_sido.items():
        u = P(unary_union(gs))
        lp = max(polys(u), key=lambda q: q.area).representative_point()
        out["sido"].append({"n": SHORT.get(nm, nm), "d": path(u, 5, 250), "x": round(lp.x), "y": round(lp.y)})
    # 수도권 시 · 군 · 구(구가 있는 시는 시로 합침) — 확대 지도용
    city = {}
    for (sd, sg), gs in by_sgg.items():
        u = P(unary_union(gs))
        out["sgg"].append({"n": sg, "d": path(u, 1.2, 25)})
        c = re.sub(r"(시).+구$", r"\1", sg) if sd == "경기도" else ("서울" if sd == "서울특별시" else sg if sg in ("강화군", "옹진군") else "인천")
        city.setdefault((sd, c), []).append(u)
    for (sd, c), us in city.items():
        u = unary_union(us)
        lp = max(polys(u), key=lambda q: q.area).representative_point()
        lab = c if c in ("서울", "인천") else re.sub(r"(시|군|구)$", "", c) if len(c) > 2 else c
        out["lab"].append({"n": lab, "x": round(lp.x), "y": round(lp.y), "k": 2 if c in ("서울", "인천") else 1, "a": round(u.area)})
    # 울릉도 · 독도(별도 상자에 넣을 원래 좌표)
    u = P(unary_union(ul))
    out["ul"] = {"d": path(u, 1, 0.5), "b": [round(v) for v in u.bounds]}
    # 북한 윤곽(위도 39.6도 이남만)
    topo = json.load(open(wa))
    sc, tr = topo["transform"]["scale"], topo["transform"]["translate"]
    arcs = []
    for a in topo["arcs"]:
        x = y = 0; pts = []
        for dx, dy in a:
            x += dx; y += dy; pts.append((x * sc[0] + tr[0], y * sc[1] + tr[1]))
        arcs.append(pts)

    def ring(ix):
        pts = []
        for i in ix:
            seg = arcs[i] if i >= 0 else arcs[~i][::-1]
            pts += seg if not pts else seg[1:]
        return pts
    for g in topo["objects"]["countries"]["geometries"]:
        if g.get("properties", {}).get("name") in ("North Korea", "Dem. Rep. Korea"):
            arr = g["arcs"] if g["type"] == "MultiPolygon" else [g["arcs"]]
            nk = MultiPolygon([Polygon(ring(p[0]), [ring(h) for h in p[1:]]) for p in arr]).buffer(0)
            nk = nk.intersection(box(123, 37.5, 132, 39.6))
            out["nk"] = path(P(nk), 5, 250)
    json.dump(out, open("site/data/geo.json", "w", encoding="utf-8"), ensure_ascii=False, separators=(",", ":"))
    print("geo.json", len(json.dumps(out, ensure_ascii=False)), "bytes")

    # 법정동 · 리 대표점
    import shapefile
    from pyproj import Transformer
    t = Transformer.from_crs(5179, 4326, always_xy=True)
    pts = {}
    for kind, key in (("emd", "EMD_CD"), ("li", "LI_CD")):
        r = shapefile.Reader(f"{shp}/{kind}/{kind}", encoding="cp949")
        flds = [f[0] for f in r.fields[1:]]
        for s in r.iterShapeRecords():
            rec = dict(zip(flds, s.record))
            g = shape(s.shape.__geo_interface__)
            if g.is_empty:
                continue
            q = g.representative_point()
            lon, lat = t.transform(q.x, q.y)
            pts[str(rec[key])] = [round(lon, 5), round(lat, 5), rec.get("EMD_KOR_NM") or rec.get("LI_KOR_NM")]
    json.dump(pts, open("data/geo_bjd_pts.json", "w", encoding="utf-8"), ensure_ascii=False, separators=(",", ":"))
    print("bjd pts", len(pts))


if __name__ == "__main__":
    main(*sys.argv[1:4])
