"""국토교통부 아파트 매매 실거래가 → 시 · 도 / 시 · 군 · 구 / 법정동별 전용 3.3㎡당 가격과 기간별 변동률(시안용).

- 키 · 요청 주소는 어떤 출력에도 남기지 않는다(clean()).
- 기간: 1 · 3 · 6개월, 1 · 3 · 5 · 10 · 15년. 1개월은 1개월 창끼리, 나머지는 3개월 창끼리 비교한다.
- 변동률: 같은 단지(aptSeq)가 두 창에 모두 거래된 경우만 단지별 중위 평당가 비율을 구하고,
  거래 건수(둘 중 적은 쪽) 가중 기하평균으로 지역 변동률을 낸다(단지 구성 변화의 영향을 줄임).
- 평당가: 최근 3개월 창의 거래 평당가 중위값, 만원. p = 공급면적 기준(전용면적을 공급면적으로 환산), pe = 전용면적 기준.
  실거래 자료에는 전용면적만 있어, 청약홈 분양 주택형의 공급면적 ÷ 전용면적 중위값(전용 크기별)으로 환산한다.
- NOW_ONLY=1 이면 최근 3개월만 받아 평당가만 다시 낸다(변동률은 이전 결과를 쓴다).
- anchor: 달별 · 시도별 거래 건수 · 거래금액 합 · 전용면적 합(아파트 시가총액 추정의 기준 가격용).
"""
import concurrent.futures as cf, datetime as dt, json, math, os, pathlib, re, statistics as st, threading, time, urllib.parse
import xml.etree.ElementTree as ET
import requests

KEY = os.environ.get("DATA_GO_KR_KEY", "").strip()
ENC = urllib.parse.quote(KEY, safe="")
OUT = pathlib.Path("probe/out"); OUT.mkdir(parents=True, exist_ok=True)
EPS = ["https://apis.data.go.kr/1613000/RTMSDataSvcAptTradeDev/getRTMSDataSvcAptTradeDev",
       "https://apis.data.go.kr/1613000/RTMSDataSvcAptTrade/getRTMSDataSvcAptTrade"]
PERIODS = [1, 3, 6, 12, 36, 60, 120, 180]
LOG = []
NOW_ONLY = os.environ.get("NOW_ONLY") == "1"
# 공급면적 ÷ 전용면적: 청약홈 2025~26년 분양 주택형 2,077개의 전용 크기별 중위값(점 사이는 직선으로 잇는다)
SUP_R = [(40, 1.413), (59, 1.385), (74, 1.352), (84, 1.324), (105, 1.306), (135, 1.327)]


def sup_ratio(ar):
    if ar <= SUP_R[0][0]:
        return SUP_R[0][1]
    for (a0, r0), (a1, r1) in zip(SUP_R, SUP_R[1:]):
        if ar <= a1:
            return r0 + (r1 - r0) * (ar - a0) / (a1 - a0)
    return SUP_R[-1][1]


def clean(s):
    s = str(s)
    for k in (KEY, ENC, urllib.parse.quote_plus(KEY)):
        if k:
            s = s.replace(k, "***")
    s = re.sub(r"serviceKey=[^&\s'\")]+", "serviceKey=***", s)
    return re.sub(r"https?://\S+", "<url>", s)


def log(*a):
    m = clean(" ".join(str(x) for x in a)); LOG.append(m); print(m, flush=True)


# ── 지역 코드: 현재 코드(dc-watch data/bjd_units.json) + 예전 코드 ──
SHORT = {"서울특별시": "서울", "부산광역시": "부산", "대구광역시": "대구", "인천광역시": "인천", "대전광역시": "대전", "울산광역시": "울산",
         "세종특별자치시": "세종", "경기도": "경기", "강원특별자치도": "강원", "충청북도": "충북", "충청남도": "충남", "전북특별자치도": "전북",
         "경상북도": "경북", "경상남도": "경남", "제주특별자치도": "제주"}
units = json.load(open("data/bjd_units.json", encoding="utf-8"))
CODE = {}      # 5자리 → (시도 짧은 이름, 시군구 지도 이름)
DONG2 = {}     # (시도, 동명) → 시군구(인천 · 부천 같은 분할 지역 배정용)
for sd, c5, umd, sgg, dong, ri in units:
    if sd.startswith("전남광주"):
        s = "광주" if re.search(r"구$", sgg) else "전남"
    else:
        s = SHORT.get(sd, sd)
    g = "세종시" if s == "세종" else re.sub(r"^(.+?시)\s.+구$", r"\1", sgg)
    CODE[c5] = (s, g)
    DONG2.setdefault((s, dong), g)
OLD = {"28110": ("인천", "*인천중구"), "28140": ("인천", "제물포구"), "28170": ("인천", "미추홀구"), "28260": ("인천", "*인천서구"),
       "41590": ("경기", "화성시"), "41190": ("경기", "부천시"), "41730": ("경기", "여주시"), "44800": ("충남", "당진시"),
       "47720": ("대구", "군위군"), "44730": ("세종", "세종시"), "43710": ("충북", "청주시"), "43110": ("충북", "청주시")}
for c5, v in list(CODE.items()):
    if c5.startswith("51"):
        OLD["42" + c5[2:]] = v
    if c5.startswith("52"):
        OLD["45" + c5[2:]] = v
GJ = {"29110": "동구", "29140": "서구", "29155": "남구", "29170": "북구", "29200": "광산구"}
for k, v in GJ.items():
    OLD[k] = ("광주", v)
JN = {"46110": "목포시", "46130": "여수시", "46150": "순천시", "46170": "나주시", "46230": "광양시", "46710": "담양군", "46720": "곡성군",
      "46730": "구례군", "46770": "고흥군", "46780": "보성군", "46790": "화순군", "46800": "장흥군", "46810": "강진군", "46820": "해남군",
      "46830": "영암군", "46840": "무안군", "46860": "함평군", "46870": "영광군", "46880": "장성군", "46890": "완도군", "46900": "진도군", "46910": "신안군"}
for k, v in JN.items():
    OLD[k] = ("전남", v)
# 점검(18): API는 예전 기간 거래도 지금 지역 코드로 돌려주고, 예전 코드는 0건 → 지금 코드만 부른다(호출 수 절약)
ALL = dict(CODE)
YJ = re.compile(r"운서|운남|운북|중산|을왕|남북동|덕교|무의|용유")
GD = re.compile(r"당하|마전|원당|불로|대곡|오류|왕길|금곡|백석|아라")


def sgg_of(code, dong):
    s, g = ALL[code]
    if g == "*인천중구":
        g = "영종구" if YJ.search(dong) else "제물포구"
    elif g == "*인천서구":
        g = "검단구" if GD.search(dong) else "서해구"
    return s, g


# ── 기간별로 필요한 달 ──
today = dt.date.today()
t0 = (today.replace(day=1) - dt.timedelta(days=1)).replace(day=1)   # 지난달(신고 기한 30일 → 대부분 들어옴)


def mo(k):
    y, m = divmod(t0.year * 12 + t0.month - 1 - k, 12)
    return f"{y}{m + 1:02d}"


WIN = {"now3": [0, 1, 2], "now1": [0]}
for p in ([] if NOW_ONLY else PERIODS):
    WIN[f"b{p}"] = [p] if p == 1 else [p, p + 1, p + 2]
NEED = sorted({k for v in WIN.values() for k in v})
log("기준월", mo(0), "필요한 달", len(NEED), "코드", len(ALL))

# ── 수집 ──
sess = requests.Session(); lock = threading.Lock(); EP = [None]; STOP = [False]; CALLS = [0]


def fetch(code, ymd):
    rows, page = [], 1
    while True:
        if STOP[0]:
            return None
        for att in range(4):
            try:
                r = sess.get(EP[0], params={"serviceKey": KEY, "LAWD_CD": code, "DEAL_YMD": ymd, "pageNo": page, "numOfRows": 1000}, timeout=(15, 60))
                with lock:
                    CALLS[0] += 1
                root = ET.fromstring(r.content)
                err = (root.findtext(".//errMsg") or root.findtext(".//returnAuthMsg") or "").strip()
                rc = (root.findtext(".//resultCode") or "").strip()
                if "LIMITED" in err or "EXCEEDS" in err or rc in ("22",):
                    STOP[0] = True; log("호출 한도 초과 → 중단"); return None
                if err:
                    raise RuntimeError(err)
                its = root.findall(".//item")
                for it in its:
                    rows.append({c.tag: (c.text or "").strip() for c in it})
                tot = int((root.findtext(".//totalCount") or "0").strip() or 0)
                break
            except Exception as e:  # noqa
                if att == 3:
                    log("실패", code, ymd, type(e).__name__, clean(e)[:120]); return rows
                time.sleep(2 + att * 3)
        if page * 1000 >= tot:
            return rows
        page += 1


# 엔드포인트 고르기(상세 → 기본)
for ep in EPS:
    EP[0] = ep
    try:
        r = sess.get(ep, params={"serviceKey": KEY, "LAWD_CD": "11680", "DEAL_YMD": mo(0), "pageNo": 1, "numOfRows": 1}, timeout=30)
        root = ET.fromstring(r.content)
        err = (root.findtext(".//errMsg") or "").strip()
        log("엔드포인트", "상세" if "Dev" in ep else "기본", r.status_code, err or "OK", (root.findtext(".//totalCount") or "").strip())
        if not err and r.status_code == 200:
            break
    except Exception as e:  # noqa
        log("엔드포인트 오류", type(e).__name__)
else:
    (OUT / "rt_log.json").write_text(json.dumps(LOG, ensure_ascii=False, indent=1)); raise SystemExit("사용할 수 있는 엔드포인트 없음")

jobs = [(c, mo(k)) for k in NEED for c in ALL]
RAW = {}   # ymd → list of (sido, sgg, dong, apt, ppy)
ANC = {}   # ymd → 시도(광주 · 전남 따로) → [건수, 거래금액 합(만원), 전용면적 합(㎡)]
SEEN = set()   # 예전 코드와 새 코드가 같은 거래를 함께 돌려줄 때 두 번 세지 않게
t_start = time.time()
with cf.ThreadPoolExecutor(6) as ex:
    futs = {ex.submit(fetch, c, y): (c, y) for c, y in jobs}
    for i, f in enumerate(cf.as_completed(futs)):
        c, y = futs[f]; rows = f.result() or []
        for x in rows:
            if (x.get("cdealType") or "").strip() in ("O", "o"):
                continue   # 해제 거래 제외
            try:
                amt = float((x.get("dealAmount") or "0").replace(",", "")); ar = float(x.get("excluUseAr") or 0)
            except ValueError:
                continue
            if amt <= 0 or ar < 10:
                continue
            dong = (x.get("umdNm") or "").strip()
            sig = (x.get("aptSeq") or x.get("aptNm"), dong, x.get("dealYear"), x.get("dealMonth"), x.get("dealDay"), x.get("dealAmount"), x.get("floor"), x.get("excluUseAr"))
            if sig in SEEN:
                continue
            SEEN.add(sig)
            s, g = sgg_of(c, dong)
            apt = x.get("aptSeq") or f"{c}|{dong}|{x.get('jibun','')}|{x.get('aptNm','')}"
            RAW.setdefault(y, []).append((s, g, dong, apt, round(amt / ar * 3.3058, 1), round(amt / (ar * sup_ratio(ar)) * 3.3058, 1)))
            ag = ANC.setdefault(y, {}).setdefault(s, [0, 0.0, 0.0])   # 시가총액 기준 가격용: 건수 · 금액 합 · 면적 합
            ag[0] += 1; ag[1] += amt; ag[2] += ar
        if i % 500 == 0:
            log("진행", i, "/", len(jobs), "호출", CALLS[0], f"{time.time() - t_start:.0f}s")
log("수집 끝 호출", CALLS[0], "거래", sum(len(v) for v in RAW.values()), f"{time.time() - t_start:.0f}s", "중단" if STOP[0] else "")

# ── 집계 ──
SIDO_OF = lambda s: "전남광주" if s in ("광주", "전남") else s   # 지도 시 · 도 이름(통합)


def keys(s, g, d):
    return [("all", "전국"), ("sido", SIDO_OF(s)), ("sgg", f"{s}|{g}"), ("dong", f"{s}|{g}|{d}")]


win_rows = {w: {} for w in WIN}   # w → level → key → apt → [전용 평당가]
sup_now = {}                       # level → key → [공급 평당가] (최근 3개월)
for w, ks in WIN.items():
    for k in ks:
        for (s, g, d, apt, ppy, pps) in RAW.get(mo(k), []):
            for lv, key in keys(s, g, d):
                win_rows[w].setdefault(lv, {}).setdefault(key, {}).setdefault(apt, []).append(ppy)
                if w == "now3":
                    sup_now.setdefault(lv, {}).setdefault(key, []).append(pps)
MINC = {"all": 20, "sido": 8, "sgg": 5, "dong": 3}
out = {"asof": f"{mo(0)[:4]}-{mo(0)[4:]}", "periods": PERIODS, "generated": today.isoformat(), "method": "same-complex", "area": "supply-converted", "sup_ratio": SUP_R, "now_only": NOW_ONLY, "levels": {}}
out["anchor"] = {f"{y[:4]}-{y[4:]}": {k: [v[0], round(v[1]), round(v[2], 1)] for k, v in d.items()} for y, d in sorted(ANC.items())}
for lv in ("all", "sido", "sgg", "dong"):
    res = {}
    now3 = win_rows["now3"].get(lv, {})
    for key, apts in now3.items():
        allp = [p for v in apts.values() for p in v]
        e = {"p": round(st.median(sup_now[lv][key])), "pe": round(st.median(allp)), "n": len(allp), "c": {}}
        for p in ([] if NOW_ONLY else PERIODS):
            A = win_rows["now1" if p == 1 else "now3"].get(lv, {}).get(key, {})
            B = win_rows[f"b{p}"].get(lv, {}).get(key, {})
            num = den = 0.0; m = 0
            for apt, a in A.items():
                b = B.get(apt)
                if not b:
                    continue
                wgt = min(len(a), len(b)); num += wgt * math.log(st.median(a) / st.median(b)); den += wgt; m += 1
            e["c"][str(p)] = round((math.exp(num / den) - 1) * 100, 2) if m >= MINC[lv] and den else None
            e.setdefault("m", {})[str(p)] = m
        res[key] = e
    out["levels"][lv] = res
    log(lv, len(res))
(OUT / "rt_agg.json").write_text(json.dumps(out, ensure_ascii=False, separators=(",", ":")))
(OUT / "rt_log.json").write_text(json.dumps(LOG, ensure_ascii=False, indent=1))
log("저장", (OUT / "rt_agg.json").stat().st_size, "bytes")
