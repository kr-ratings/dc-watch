"""국토교통부 아파트 매매 실거래가 API 접근 점검(키는 출력하지 않음)."""
import json, os, pathlib, xml.etree.ElementTree as ET
import requests
KEY = os.environ.get("DATA_GO_KR_KEY", "").strip()
OUT = pathlib.Path("probe/out"); OUT.mkdir(parents=True, exist_ok=True)
res = {}
for name, url in [("trade", "https://apis.data.go.kr/1613000/RTMSDataSvcAptTrade/getRTMSDataSvcAptTrade"),
                  ("trade_dev", "https://apis.data.go.kr/1613000/RTMSDataSvcAptTradeDev/getRTMSDataSvcAptTradeDev")]:
    for ymd in ["202609", "201109"]:
        try:
            r = requests.get(url, params={"serviceKey": KEY, "LAWD_CD": "11680", "DEAL_YMD": ymd, "pageNo": 1, "numOfRows": 5}, timeout=40)
            t = r.text
            info = {"status": r.status_code, "len": len(t)}
            try:
                root = ET.fromstring(t)
                info["resultCode"] = (root.findtext(".//resultCode") or "").strip()
                info["resultMsg"] = (root.findtext(".//resultMsg") or "").strip()
                info["totalCount"] = (root.findtext(".//totalCount") or "").strip()
                it = root.find(".//item")
                if it is not None:
                    info["fields"] = {c.tag: (c.text or "").strip() for c in it}
            except Exception as e:  # noqa
                info["head"] = t[:300].replace(KEY, "***")
            res[f"{name}_{ymd}"] = info
        except Exception as e:  # noqa
            res[f"{name}_{ymd}"] = {"error": str(e)[:200]}
(OUT / "rt_test.json").write_text(json.dumps(res, ensure_ascii=False, indent=1))
print(json.dumps(res, ensure_ascii=False, indent=1)[:3000])
