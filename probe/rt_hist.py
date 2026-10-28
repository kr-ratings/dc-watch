"""국토교통부 아파트 매매 실거래가 → 달별 원자료 요약(지도 기간 직접 지정용, 시안).

- 키 · 요청 주소는 어떤 출력에도 남기지 않는다(clean()).
- 달마다 probe/out/hist/YYYYMM.json.gz 를 따로 저장해, 호출 한도로 중간에 멈춰도 받은 달은 남는다.
- 받을 달: probe/hist_todo.txt(한 줄에 YYYYMM) — 없으면 2011-07 ~ 지난달 전체.
- 한 달 파일: {"ym", "apt": {aptSeq: [시도|시군구|동, 전용 평당가 중위(만원), 건수]},
               "dong": {시도|시군구|동: [건수, 거래금액 합(만원), 전용면적 합, 공급면적(환산) 합]}}
"""
import concurrent.futures as cf, datetime as dt, gzip, json, os, pathlib, re, statistics as st, threading, time, urllib.parse
import xml.etree.ElementTree as ET
import requests

KEY = os.environ.get("DATA_GO_KR_KEY", "").strip()
ENC = urllib.parse.quote(KEY, safe="")
OUT = pathlib.Path("probe/out/hist"); OUT.mkdir(parents=True, exist_ok=True)
EP = "https://apis.data.go.kr/1613000/RTMSDataSvcAptTradeDev/getRTMSDataSvcAptTradeDev"
LOG = []
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


SHORT = {"서울특별시": "서울", "부산광역시": "부산", "대구광역시": "대구", "인천광역시": "인천", "대전광역시": "대전", "울산광역시": "울산",
         "세종특별자치시": "세종", "경기도": "경기", "강원특별자치도": "강원", "충청북도": "충북", "충청남도": "충남", "전북특별자치도": "전북",
         "경상북도": "경북", "경상남도": "경남", "제주특별자치도": "제주"}
CODE = {}
for sd, c5, umd, sgg, dong, ri in json.load(open("data/bjd_units.json", encoding="utf-8")):
    s = ("광주" if re.search(r"구$", sgg) else "전남") if sd.startswith("전남광주") else SHORT.get(sd, sd)
    CODE[c5] = (s, "세종시" if s == "세종" else re.sub(r"^(.+?시)\s.+구$", r"\1", sgg))

today = dt.date.today()
t0 = (today.replace(day=1) - dt.timedelta(days=1)).replace(day=1)
todo_f = pathlib.Path("probe/hist_todo.txt")
if todo_f.exists():
    MONTHS = [x.strip() for x in todo_f.read_text().split() if re.fullmatch(r"\d{6}", x.strip())]
else:
    MONTHS, y, m = [], 2011, 7
    while (y, m) <= (t0.year, t0.month):
        MONTHS.append(f"{y}{m:02d}"); y, m = (y + (m == 12), m % 12 + 1)
MONTHS = sorted(set(MONTHS), reverse=True)   # 최근 달부터(중간에 멈춰도 최근 자료가 먼저 남게)
log("달", len(MONTHS), MONTHS[:2], "…", MONTHS[-2:], "코드", len(CODE))

sess = requests.Session(); lock = threading.Lock(); STOP = [False]; CALLS = [0]


def fetch(code, ymd):
    rows, page = [], 1
    while True:
        if STOP[0]:
            return None
        for att in range(4):
            try:
                r = sess.get(EP, params={"serviceKey": KEY, "LAWD_CD": code, "DEAL_YMD": ymd, "pageNo": page, "numOfRows": 1000}, timeout=(15, 60))
                with lock:
                    CALLS[0] += 1
                root = ET.fromstring(r.content)
                err = (root.findtext(".//errMsg") or root.findtext(".//returnAuthMsg") or "").strip()
                rc = (root.findtext(".//resultCode") or "").strip()
                if "LIMITED" in err or "EXCEEDS" in err or rc == "22":
                    STOP[0] = True; log("호출 한도 초과 → 중단", "호출", CALLS[0]); return None
                if err:
                    raise RuntimeError(err)
                rows += [{c.tag: (c.text or "").strip() for c in it} for it in root.findall(".//item")]
                tot = int((root.findtext(".//totalCount") or "0").strip() or 0)
                break
            except Exception as e:  # noqa
                if att == 3:
                    log("실패", code, ymd, type(e).__name__, clean(e)[:120]); return None
                time.sleep(2 + att * 3)
        if page * 1000 >= tot:
            return rows
        page += 1


t_start = time.time(); done = []
for ym in MONTHS:
    if STOP[0]:
        break
    with cf.ThreadPoolExecutor(8) as ex:
        res = list(ex.map(lambda c: (c, fetch(c, ym)), list(CODE)))
    if STOP[0] or any(v is None for _, v in res):
        log("미완료 달 저장 안 함", ym, "빠진 코드", sum(v is None for _, v in res)); 
        if STOP[0]:
            break
        continue
    seen, apt, dong = set(), {}, {}
    for c, rows in res:
        for x in rows:
            if (x.get("cdealType") or "").strip() in ("O", "o"):
                continue
            try:
                amt = float((x.get("dealAmount") or "0").replace(",", "")); ar = float(x.get("excluUseAr") or 0)
            except ValueError:
                continue
            if amt <= 0 or ar < 10:
                continue
            d = (x.get("umdNm") or "").strip()
            sig = (x.get("aptSeq") or x.get("aptNm"), d, x.get("dealYear"), x.get("dealMonth"), x.get("dealDay"), x.get("dealAmount"), x.get("floor"), x.get("excluUseAr"))
            if sig in seen:
                continue
            seen.add(sig)
            s, g = CODE[c]; key = f"{s}|{g}|{d}"
            a = x.get("aptSeq") or f"{c}|{d}|{x.get('jibun', '')}|{x.get('aptNm', '')}"
            apt.setdefault(a, [key, []])[1].append(amt / ar * 3.3058)
            q = dong.setdefault(key, [0, 0.0, 0.0, 0.0]); q[0] += 1; q[1] += amt; q[2] += ar; q[3] += ar * sup_ratio(ar)
    out = {"ym": ym, "apt": {a: [k, round(st.median(v), 1), len(v)] for a, (k, v) in apt.items()},
           "dong": {k: [q[0], round(q[1]), round(q[2], 1), round(q[3], 1)] for k, q in dong.items()}}
    (OUT / f"{ym}.json.gz").write_bytes(gzip.compress(json.dumps(out, ensure_ascii=False, separators=(",", ":")).encode()))
    done.append(ym)
    log("저장", ym, "거래", len(seen), "단지", len(apt), "호출", CALLS[0], f"{time.time() - t_start:.0f}s")
log("끝 · 받은 달", len(done), "/", len(MONTHS), "호출", CALLS[0], "중단" if STOP[0] else "")
pathlib.Path("probe/out/rt_hist_log.json").write_text(json.dumps({"done": done, "log": LOG}, ensure_ascii=False, indent=1))
