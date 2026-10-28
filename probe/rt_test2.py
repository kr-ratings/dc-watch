"""아파트 매매 실거래가 API 점검 2 — 키 · 요청 주소는 어떤 출력에도 남기지 않는다."""
import json, os, pathlib, re, time, urllib.parse, xml.etree.ElementTree as ET
import requests
KEY = os.environ.get("DATA_GO_KR_KEY", "").strip()
ENC = urllib.parse.quote(KEY, safe="")
OUT = pathlib.Path("probe/out"); OUT.mkdir(parents=True, exist_ok=True)


def clean(s):
    s = str(s)
    for k in (KEY, ENC, urllib.parse.quote_plus(KEY)):
        if k:
            s = s.replace(k, "***")
    s = re.sub(r"serviceKey=[^&\s'\")]+", "serviceKey=***", s)
    s = re.sub(r"https?://\S+", "<url>", s)
    return s


def call(base, lawd, ymd, rows=10, page=1):
    t0 = time.time()
    try:
        r = requests.get(base, params={"serviceKey": KEY, "LAWD_CD": lawd, "DEAL_YMD": ymd, "pageNo": page, "numOfRows": rows}, timeout=(15, 60))
        info = {"status": r.status_code, "sec": round(time.time() - t0, 1)}
        try:
            root = ET.fromstring(r.content)
            for tag in ("resultCode", "resultMsg", "totalCount", "errMsg", "returnAuthMsg", "returnReasonCode"):
                v = root.findtext(f".//{tag}")
                if v is not None:
                    info[tag] = v.strip()
            items = root.findall(".//item")
            info["items"] = len(items)
            if items:
                info["fields"] = {c.tag: (c.text or "").strip() for c in items[0]}
        except Exception as e:  # noqa
            info["parse"] = type(e).__name__; info["head"] = clean(r.text[:200])
        return info
    except Exception as e:  # noqa
        return {"error": type(e).__name__, "cause": clean(repr(getattr(e, "args", [""])[0]))[:300], "sec": round(time.time() - t0, 1)}


res = {}
for nm, base in (("dev", "https://apis.data.go.kr/1613000/RTMSDataSvcAptTradeDev/getRTMSDataSvcAptTradeDev"),
                 ("basic", "https://apis.data.go.kr/1613000/RTMSDataSvcAptTrade/getRTMSDataSvcAptTrade")):
    res[f"{nm}_gangnam_202609"] = call(base, "11680", "202609")
    if res[f"{nm}_gangnam_202609"].get("status") == 200 and not res[f"{nm}_gangnam_202609"].get("errMsg"):
        for lawd, ymd in [("11680", "201109"), ("51110", "201109"), ("42110", "201109"), ("36110", "201109"), ("44730", "201109"),
                          ("28260", "202509"), ("28260", "202608"), ("28275", "202608"), ("12300", "202608"), ("29170", "202608"), ("29170", "202509"), ("41590", "202109")]:
            res[f"{nm}_{lawd}_{ymd}"] = call(base, lawd, ymd, rows=1000 if lawd == "41590" else 10)
txt = clean(json.dumps(res, ensure_ascii=False, indent=1))
(OUT / "rt_test2.json").write_text(txt)
print(txt[:4000])
