"""국회 의안(열린국회정보) · 언론 기사(구글 뉴스 RSS)."""
import datetime as dt, email.utils, html, re
from common import get, load_json, save_json

OUT = "data/policy.json"
BILL_KW = ["데이터센터", "분산에너지", "전력계통", "전력망"]
NEWS_Q = ["데이터센터 PF", "데이터센터 착공", "데이터센터 인수 OR 매각", "데이터센터 건축허가 OR 인허가", "데이터센터 전력 OR 수전", "AI 데이터센터 투자"]


def bills():
    out = {}
    for kw in BILL_KW:
        r = get("https://open.assembly.go.kr/portal/openapi/nzmimeepazxkubdpn", {"Type": "json", "pIndex": 1, "pSize": 100, "AGE": 22, "BILL_NAME": kw})
        j = r.json().get("nzmimeepazxkubdpn") or []
        rows = j[1]["row"] if len(j) > 1 else []
        for x in rows:
            out[x["BILL_ID"]] = {k: x.get(k) for k in ["BILL_NO", "BILL_NAME", "COMMITTEE", "PROPOSE_DT", "PROPOSER", "PROC_RESULT", "CMT_PRESENT_DT", "CMT_PROC_DT",
                                                        "CMT_PROC_RESULT_CD", "LAW_PROC_DT", "LAW_PROC_RESULT_CD", "PROC_DT", "DETAIL_LINK"]} | {"kw": kw}
    return sorted(out.values(), key=lambda x: x["PROPOSE_DT"] or "", reverse=True)


def news():
    seen, items = set(), []
    cutoff = dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=90)
    for q in NEWS_Q:
        r = get("https://news.google.com/rss/search", {"q": q + " when:90d", "hl": "ko", "gl": "KR", "ceid": "KR:ko"})
        for it in re.findall(r"<item>(.*?)</item>", r.text, re.S):
            g = lambda t: html.unescape((re.search(rf"<{t}[^>]*>(.*?)</{t}>", it, re.S) or [None, ""])[1]).strip()
            title, link, src = g("title"), g("link"), g("source")
            try:
                pub = email.utils.parsedate_to_datetime(g("pubDate"))
            except Exception:
                continue
            if pub < cutoff:
                continue
            base = re.sub(r"\s+-\s+[^-]+$", "", title)
            key = re.sub(r"\W", "", base)[:40]
            if key in seen or "데이터센터" not in base and "데이터 센터" not in base:
                continue
            seen.add(key)
            items.append({"t": base, "src": src, "u": link, "d": pub.astimezone(dt.timezone(dt.timedelta(hours=9))).strftime("%Y-%m-%d %H:%M"), "q": q})
    return sorted(items, key=lambda x: x["d"], reverse=True)[:120]


def collect():
    d = load_json(OUT, {})
    for nm, fn in (("bills", bills), ("news", news)):
        try:
            d[nm] = fn()
        except Exception as e:
            d.setdefault("errors", {})[nm] = repr(e)[:200]
    d["updated"] = dt.date.today().isoformat()
    save_json(OUT, d)
    print("bills", len(d.get("bills", [])), "news", len(d.get("news", [])))


if __name__ == "__main__":
    collect()
