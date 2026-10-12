"""OpenStreetMap(Overpass)에서 국내 변전소 · 발전소 위치(이름 있는 것)를 받아 저장한다. 1회성 · 가끔 갱신용.
결과: probe/out/osm_subs.json  — [{"nm","v","t","lon","lat"}] (© OpenStreetMap contributors, ODbL)"""
import json, os, time, urllib.request, urllib.parse
Q = """[out:json][timeout:240];
area["ISO3166-1"="KR"][admin_level=2]->.kr;
(nwr["power"="substation"]["name"](area.kr); nwr["power"="plant"]["name"](area.kr););
out center tags;"""
for url in ("https://overpass-api.de/api/interpreter", "https://overpass.kumi.systems/api/interpreter"):
    try:
        req = urllib.request.Request(url, data=urllib.parse.urlencode({"data": Q}).encode(), headers={"User-Agent": "dc-watch (public dashboard)"})
        j = json.load(urllib.request.urlopen(req, timeout=300)); break
    except Exception as e:
        print("fail", url, repr(e)[:200]); time.sleep(5)
out = []
for e in j["elements"]:
    t = e.get("tags", {}); c = e.get("center") or {"lon": e.get("lon"), "lat": e.get("lat")}
    if c.get("lon") is None: continue
    out.append({"nm": t.get("name:ko") or t.get("name"), "nm0": t.get("name"), "v": t.get("voltage", ""), "t": t.get("power"), "op": t.get("operator", ""), "lon": round(c["lon"], 5), "lat": round(c["lat"], 5)})
os.makedirs("probe/out", exist_ok=True)
json.dump(out, open("probe/out/osm_subs.json", "w", encoding="utf-8"), ensure_ascii=False)
print("osm features", len(out), "with 345k", sum(1 for x in out if "345000" in x["v"]))
