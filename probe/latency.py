"""건축HUB 한 번에 받을 수 있는 행 수(numOfRows) 점검."""
import json, sys, time
import requests
sys.path.insert(0, "collector")
from common import DGK, scrub
URL = "https://apis.data.go.kr/1613000/ArchPmsHubService/getApBasisOulnInfo"
for n in (100, 500, 1000, 3000):
    p = {"serviceKey": DGK, "_type": "json", "numOfRows": n, "pageNo": 1, "sigunguCd": "27170", "bjdongCd": "10200", "startDate": "20200101", "endDate": "20261012"}
    t = time.time()
    try:
        g = requests.get(URL, params=p, timeout=(15, 240))
        j = g.json(); b = j["response"]["body"]; it = b.get("items") or {}; it = it.get("item", []) if isinstance(it, dict) else []
        print(n, g.status_code, f"{time.time()-t:.1f}s", "total", b.get("totalCount"), "got", len(it), len(g.text), flush=True)
    except Exception as e:
        print(n, "EXC", f"{time.time()-t:.1f}s", scrub(repr(e))[:200], scrub(getattr(locals().get('g'), 'text', '')[:200]), flush=True)
