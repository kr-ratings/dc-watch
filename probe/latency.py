"""건축HUB 응답 지연 점검: 다음 차례 단위 몇 개를 한 건씩 보내 걸린 시간 · 응답 앞부분을 찍는다."""
import json, os, sys, time, socket
import requests
sys.path.insert(0, "collector")
from common import DGK, scrub

URL = "https://apis.data.go.kr/1613000/ArchPmsHubService/getApBasisOulnInfo"
units = json.load(open("data/bjd_units.json", encoding="utf-8"))
done = set(json.load(open("data/state/permit_scan.json", encoding="utf-8"))["done"])
todo = [u for u in units if f"{u[1]}-{u[2]}" not in done][:6]
t = time.time()
try:
    socket.create_connection(("apis.data.go.kr", 443), timeout=15).close(); print("tcp443", round(time.time() - t, 2))
except Exception as e:
    print("tcp443 fail", repr(e)[:120])

def one(url, u, ua=None, ses=None):
    p = {"serviceKey": DGK, "_type": "json", "numOfRows": 100, "pageNo": 1, "sigunguCd": u[1], "bjdongCd": u[2], "startDate": "20200101", "endDate": "20261012"}
    t = time.time()
    try:
        g = (ses or requests).get(url, params=p, timeout=(15, 240), headers={"User-Agent": ua} if ua else None)
        print(url.split(":")[0], u[1], u[2], g.status_code, f"{time.time() - t:.1f}s", len(g.text), scrub(g.text[:160]).replace("\n", " "), flush=True)
    except Exception as e:
        print(url.split(":")[0], u[1], u[2], "EXC", f"{time.time() - t:.1f}s", scrub(repr(e))[:160], flush=True)

print("== https, 기본 UA"); [one(URL, u) for u in todo[:3]]
print("== https, 수집기 UA"); [one(URL, u, "Mozilla/5.0 (dc-watch collector)") for u in todo[3:5]]
print("== http"); [one(URL.replace("https", "http"), u) for u in todo[5:6]]
print("== 이미 받은 단위(가벼운 곳) 재요청"); [one(URL, u) for u in [x for x in units if f"{x[1]}-{x[2]}" in done][:2]]
