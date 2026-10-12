"""공공데이터포털에서 건축HUB 건축인허가정보 API 페이지를 받아 심의유형 · 트래픽 안내를 그대로 뽑는다(키 불필요)."""
import html, json, os, re, requests
S = requests.Session(); S.headers["User-Agent"] = "Mozilla/5.0"
out = {"search": [], "pages": {}}
def text(h):
    h = re.sub(r"<script.*?</script>|<style.*?</style>", " ", h, flags=re.S)
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", h)))
ids = {}
for kw in ["건축HUB 건축인허가정보", "건축인허가정보 서비스", "ArchPmsHubService"]:
    try:
        r = S.get("https://www.data.go.kr/tcs/dss/selectDataSetList.do", params={"keyword": kw, "dType": "API", "perPage": 40}, timeout=40)
        for m in re.finditer(r'/data/(\d{8})/openapi\.do', r.text):
            ids.setdefault(m.group(1), kw)
        out["search"].append({"kw": kw, "status": r.status_code, "n": len(re.findall(r'/data/(\d{8})/openapi\.do', r.text))})
    except Exception as e:
        out["search"].append({"kw": kw, "err": repr(e)[:200]})
for i in list(ids)[:30]:
    try:
        r = S.get(f"https://www.data.go.kr/data/{i}/openapi.do", timeout=40)
        t = text(r.text)
        title = (re.search(r"<title>(.*?)</title>", r.text, re.S) or [None, ""])[1].strip()
        if "건축" not in t[:20000]:
            continue
        snips = {}
        for key in ["심의유형", "심의여부", "자동승인", "개발계정", "운영계정", "트래픽", "ArchPmsHubService", "서비스URL", "이용허락범위"]:
            snips[key] = [t[max(0, m.start() - 120): m.start() + 220] for m in re.finditer(key, t)][:3]
        out["pages"][i] = {"title": title, "status": r.status_code, "snips": snips}
    except Exception as e:
        out["pages"][i] = {"err": repr(e)[:200]}
os.makedirs("probe/out", exist_ok=True)
json.dump(out, open("probe/out/page_probe.json", "w"), ensure_ascii=False, indent=1)
print(json.dumps(out["search"], ensure_ascii=False)); print(list(out["pages"]))
