"""인허가 목록의 각 데이터센터 건에 관련 기사를 붙인다(구글 뉴스 RSS).

- 건물명에 사업자 · 브랜드가 드러나면 그 이름으로, 아니면 '시 · 군 + 동 + 데이터센터'로 검색한다.
- 제목에 데이터센터(IDC)가 들어가고, 브랜드 · 동 이름 · 시군 이름이 맞는 기사만 남겨 점수순으로 3건까지 붙인다.
- 새로 잡힌 건은 바로, 기존 건은 7일마다 다시 찾는다.
"""
import datetime as dt, email.utils, html, re, sys, time, os
sys.path.insert(0, os.path.dirname(__file__))
from common import get, load_json, save_json

OUT = "data/permit_news.json"
NOISE = r"(신축공사|신축|증축|공사|용도변경|대수선|리모델링|방송통신시설|데이터\s*센터|데이터센타|DATA\s*CENTER|IDC|센터|PFV|프로젝트|사업|\(가칭\)|㈜|\(주\)|주식회사|및|외\s*\d+필지|[\(\)\[\]·,]|\d+[-\d]*번지|\d+-\d+|\d+)"
FOREIGN = re.compile(r"美|日|中|英|獨|미국|일본|중국|유럽|인도|베트남|말레이|싱가포르|대만|호주|태국|인니|인도네시아|사우디|UAE|텍사스|버지니아")
DCWORD = re.compile(r"데이터\s?센터|IDC|AI\s?센터|AIDC|AI\s?DC", re.I)


def city_short(sgg):
    s = (sgg or "").split()[0] if sgg else ""
    return re.sub(r"(특별자치시|특별시|광역시|시|군|구)$", "", s) or s


def dong_short(dong):
    d = (dong or "").split()[-1] if dong else ""
    d = re.sub(r"\d+가$", "", d)
    s = re.sub(r"(\d+동|동|리|읍|면)$", "", d)
    return s if len(s) >= 2 else d  # '내동'처럼 한 글자가 되면 원래 이름을 쓴다


def brand_tokens(name, dong, city):
    s = re.sub(NOISE, " ", name or "", flags=re.I)
    toks = [t for t in s.split() if len(t) >= 2]
    skip = {dong, dong_short(dong), city, city + "시", city + "군", city + "구", "AI", "ai", "서울", "부산", "대구", "인천", "광주", "대전", "울산",
            "세종", "경기", "강원", "충북", "충남", "전북", "전남", "경북", "경남", "제주", "디지털"}
    return [t for t in toks if t not in skip and not re.fullmatch(r"[가-힣]+(동|리|가|구|시|군)\d*가?", t)]


def search(q):
    r = get("https://news.google.com/rss/search", {"q": q, "hl": "ko", "gl": "KR", "ceid": "KR:ko"})
    out = []
    for it in re.findall(r"<item>(.*?)</item>", r.text, re.S):
        g = lambda t: html.unescape((re.search(rf"<{t}[^>]*>(.*?)</{t}>", it, re.S) or [None, ""])[1]).strip()
        title, link, src = g("title"), g("link"), g("source")
        try:
            pub = email.utils.parsedate_to_datetime(g("pubDate")).astimezone(dt.timezone(dt.timedelta(hours=9)))
        except Exception:
            continue
        out.append({"t": re.sub(r"\s+-\s+[^-]+$", "", title), "src": src, "u": link, "d": pub.strftime("%Y-%m-%d")})
    return out


CONV = re.compile(r"용도\s?변경|전환|리모델링|개조")


def _dates(h):
    out = []
    for k in ("archPmsDay", "realStcnsDay", "useAprDay"):
        v = str(h.get(k) or "").strip()
        if re.fullmatch(r"\d{8}", v):
            out.append(dt.date(int(v[:4]), int(v[4:6]), int(v[6:])))
    return out


def _gap(h, d):
    ds = _dates(h)
    return min(abs((x - d).days) for x in ds) if ds else 99999


def find(row, siblings=()):
    ambiguous = bool(siblings)
    dong = (row.get("dongNmAddr") or "").split()[0] if row.get("dongNmAddr") else ""
    city = city_short(row.get("sggNm"))
    ds = dong_short(dong)
    brands = brand_tokens(row.get("bldNm"), dong, city)
    conv = (row.get("archGbCdNm") or "") in ("대수선", "용도변경") or "용도변경" in (row.get("bldNm") or "")
    qs = []
    if brands:
        qs.append(" ".join(brands[:3]) + " 데이터센터")
    dong_q = re.sub(r"\d+가$", "", dong)
    qs.append(f"{city} {dong_q} 데이터센터")
    cand = {}
    for q in qs:
        for a in search(q):
            t = a["t"]
            if not DCWORD.search(t) or FOREIGN.search(t):
                continue
            b_hit = bool(brands) and any(b.lower() in t.lower() for b in brands)
            d_hit = bool(ds) and ds in t
            c_hit = bool(city) and city in t
            ok = b_hit and (c_hit or d_hit)          # 이름 + 지역이 함께 맞는 기사
            if not ok and d_hit and c_hit:           # 동 + 시군이 맞는 기사
                if not ambiguous:
                    ok = True
                else:                                # 같은 동에 데이터센터가 여럿이면 신축/전환 성격이 맞고,
                    ad = dt.date.fromisoformat(a["d"])  # 기사 날짜가 이 건의 허가·착공·준공일과 가장 가까울 때만
                    mine = _gap(row, ad)
                    ok = bool(CONV.search(t)) == conv and mine <= 400 and all(mine <= _gap(o, ad) for o in siblings)
            if not ok:
                continue
            sc = 3 * b_hit + 2 * d_hit + c_hit
            key = re.sub(r"\W", "", t)[:40]
            if key not in cand or cand[key]["sc"] < sc:
                cand[key] = dict(a, sc=sc)
        time.sleep(1.0)
    items = sorted(cand.values(), key=lambda a: (a["sc"], a["d"]), reverse=True)[:3]
    return {"q": qs, "items": items}


def collect(max_refresh=60):
    rows = [h for h in load_json("data/permits.json", {"items": []})["items"] if h.get("dc")]
    db = load_json(OUT, {})
    today = dt.date.today()
    todo = [h for h in rows if h["mgmPmsrgstPk"] not in db]
    stale = sorted((h for h in rows if h["mgmPmsrgstPk"] in db and db[h["mgmPmsrgstPk"]].get("checked", "") <= (today - dt.timedelta(days=7)).isoformat()),
                   key=lambda h: db[h["mgmPmsrgstPk"]].get("checked", ""))
    dongs = {}
    for h in rows:
        dongs.setdefault((h.get("sigunguCd"), h.get("bjdongCd")), []).append(h)
    if os.environ.get("FORCE"):
        todo, stale = rows, []
    n = 0
    for h in todo + stale[:max_refresh]:
        try:
            sib = [o for o in dongs.get((h.get("sigunguCd"), h.get("bjdongCd")), []) if (o.get("bun"), o.get("ji")) != (h.get("bun"), h.get("ji"))]
            res = find(h, siblings=sib)
        except Exception as e:
            print("err", h.get("bldNm"), repr(e)[:120]); continue
        res["checked"] = today.isoformat()
        db[h["mgmPmsrgstPk"]] = res
        n += 1
    save_json(OUT, db)
    print("permit news", n, "rows checked;", sum(1 for v in db.values() if v.get("items")), "with articles /", len(db))


if __name__ == "__main__":
    collect()
