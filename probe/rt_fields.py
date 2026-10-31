"""실거래가 상세 API 응답 항목 · 채워진 비율 점검(동 aptDong, 직거래 dealingGbn 등). 키 · 주소는 출력하지 않음."""
import json, os, pathlib, re, urllib.parse, collections
import xml.etree.ElementTree as ET
import requests
KEY = os.environ.get("DATA_GO_KR_KEY", "").strip()
EP = "https://apis.data.go.kr/1613000/RTMSDataSvcAptTradeDev/getRTMSDataSvcAptTradeDev"
out = {}
for code in ("11680", "50110"):
    for ym in ("200806", "201506", "202006", "202106", "202206", "202306", "202406", "202509"):
        try:
            r = requests.get(EP, params={"serviceKey": KEY, "LAWD_CD": code, "DEAL_YMD": ym, "pageNo": 1, "numOfRows": 1000}, timeout=(15, 60))
            items = [{c.tag: (c.text or "").strip() for c in it} for it in ET.fromstring(r.content).findall(".//item")]
        except Exception as e:  # noqa
            out[f"{code}-{ym}"] = {"error": type(e).__name__}; continue
        n = len(items); keys = collections.Counter(k for it in items for k in it)
        fill = {k: round(sum(1 for it in items if it.get(k)) / n, 2) for k in keys} if n else {}
        ex = {k: collections.Counter(it.get(k, "") for it in items).most_common(4) for k in ("aptDong", "dealingGbn", "slerGbn", "buyerGbn", "cdealType", "landLeaseholdGbn") if k in keys}
        out[f"{code}-{ym}"] = {"n": n, "fields": sorted(keys), "fill": fill, "examples": ex}
        print(code, ym, n, "aptDong 채움", fill.get("aptDong"), flush=True)
pathlib.Path("probe/out").mkdir(parents=True, exist_ok=True)
pathlib.Path("probe/out/rt_fields.json").write_text(json.dumps(out, ensure_ascii=False, indent=1))
