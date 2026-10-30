"""전국 아파트 매매 실거래 → apt-watch cache/rt 새 형식(v2) 달별 파일(같은 집 반복매매 지수용).

- 키 · 요청 주소는 어떤 출력에도 남기지 않는다(clean()).
- PART: "new" = 2016-01 ~ 지난달, "old" = 2006-01 ~ 2015-12 (두 번에 나눠 동시에 돌림)
- 한 달 파일 probe/out/v2/YYYYMM.json.gz:
  {"ym", "v": 2, "u": {단지: [시도|시군구|동, [[전용면적, 층, 거래금액(만원)], ...]]},
   "dong": {시도|시군구|동: [건수, 거래금액 합(만원), 전용면적 합, 공급면적(환산) 합]}}
  (apt-watch collector/market.py rt_fetch 와 같은 규칙: 해제 거래 제외 · 같은 거래 중복 제거 · 전용 10㎡ 미만 제외)
"""
import concurrent.futures as cf, datetime as dt, gzip, json, os, pathlib, re, threading, time, urllib.parse
import xml.etree.ElementTree as ET
import requests

KEY = os.environ.get("DATA_GO_KR_KEY", "").strip()
OUT = pathlib.Path("probe/out/v2"); OUT.mkdir(parents=True, exist_ok=True)
EP = "https://apis.data.go.kr/1613000/RTMSDataSvcAptTradeDev/getRTMSDataSvcAptTradeDev"
SUP_R = [(40, 1.413), (59, 1.385), (74, 1.352), (84, 1.324), (105, 1.306), (135, 1.327)]
SHORT = {"서울특별시": "서울", "부산광역시": "부산", "대구광역시": "대구", "인천광역시": "인천", "대전광역시": "대전", "울산광역시": "울산",
         "세종특별자치시": "세종", "경기도": "경기", "강원특별자치도": "강원", "충청북도": "충북", "충청남도": "충남", "전북특별자치도": "전북",
         "경상북도": "경북", "경상남도": "경남", "제주특별자치도": "제주"}
LOG = []


def clean(s):
    s = str(s)
    for k in (KEY, urllib.parse.quote(KEY, safe=""), urllib.parse.quote_plus(KEY)):
        if k:
            s = s.replace(k, "***")
    s = re.sub(r"serviceKey=[^&\s'\")]+", "serviceKey=***", s)
    return re.sub(r"https?://\S+", "<url>", s)


def log(*a):
    m = clean(" ".join(str(x) for x in a)); LOG.append(m); print(m, flush=True)


def sup_ratio(ar):
    if ar <= SUP_R[0][0]:
        return SUP_R[0][1]
    for (a0, r0), (a1, r1) in zip(SUP_R, SUP_R[1:]):
        if ar <= a1:
            return r0 + (r1 - r0) * (ar - a0) / (a1 - a0)
    return SUP_R[-1][1]


CODE = {}
for sd, c5, umd, sgg, dong, ri in json.load(open("data/bjd_units.json", encoding="utf-8")):
    s = ("광주" if re.search(r"구$", sgg) else "전남") if sd.startswith("전남광주") else SHORT.get(sd, sd)
    CODE[c5] = (s, "세종시" if s == "세종" else re.sub(r"^(.+?시)\s.+구$", r"\1", sgg))

today = dt.date.today(); last = (today.replace(day=1) - dt.timedelta(days=1))
y0, y1 = ((2016, 1), (last.year, last.month)) if PART == "new" else ((2006, 1), (2015, 12))  # noqa: F821
MONTHS, (y, m) = [], y0
while (y, m) <= y1:
    MONTHS.append(f"{y}{m:02d}"); y, m = (y + (m == 12), m % 12 + 1)
MONTHS.reverse()
todo = pathlib.Path(f"probe/v2_todo_{PART}.txt")   # noqa: F821  — 있으면 그 달만(앞서 받은 달은 건너뜀)
if todo.exists():
    MONTHS = [m for m in MONTHS if m in set(todo.read_text().split())]
log("PART", PART, "달", len(MONTHS), MONTHS[0], "~", MONTHS[-1], "코드", len(CODE))  # noqa: F821

sess = requests.Session(); lock = threading.Lock(); STOP = [False]; CALLS = [0]
for att in range(5):
    try:
        sess.get(EP, params={"serviceKey": KEY, "LAWD_CD": "11680", "DEAL_YMD": MONTHS[0], "pageNo": 1, "numOfRows": 1}, timeout=(10, 30)); break
    except Exception as e:  # noqa
        log("접속 확인 실패", att + 1, type(e).__name__); time.sleep(15)
else:
    pathlib.Path(f"probe/out/rt_v2_{PART}_log.json").write_text(json.dumps({"done": [], "log": LOG}, ensure_ascii=False, indent=1)); raise SystemExit(0)  # noqa: F821


def fetch(code, ymd):
    rows, page = [], 1
    while True:
        if STOP[0]:
            return None
        for att in range(5):
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
                if att == 4:
                    log("실패", code, ymd, type(e).__name__); return None
                time.sleep(2 + att * 3)
        if page * 1000 >= tot:
            return rows
        page += 1


t0 = time.time(); done = []
for ym in MONTHS:
    if STOP[0] or time.time() - t0 > 92 * 60:
        log("시간 · 한도로 멈춤", ym); break
    with cf.ThreadPoolExecutor(8) as ex:
        res = list(ex.map(lambda c: (c, fetch(c, ym)), list(CODE)))
    if any(v is None for _, v in res):
        log("미완료 달 저장 안 함", ym); continue
    seen, u, dong = set(), {}, {}
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
            try:
                fl = int(x.get("floor") or 0)
            except ValueError:
                fl = 0
            u.setdefault(a, [key, []])[1].append([round(ar, 2), fl, int(round(amt))])
            q = dong.setdefault(key, [0, 0.0, 0.0, 0.0]); q[0] += 1; q[1] += amt; q[2] += ar; q[3] += ar * sup_ratio(ar)
    out = {"ym": ym, "v": 2, "u": u, "dong": {k: [q[0], round(q[1]), round(q[2], 1), round(q[3], 1)] for k, q in dong.items()}}
    (OUT / f"{ym}.json.gz").write_bytes(gzip.compress(json.dumps(out, ensure_ascii=False, separators=(",", ":")).encode(), mtime=0))
    done.append(ym)
    if len(done) % 12 == 0:
        log("저장", ym, "누적 달", len(done), "호출", CALLS[0], f"{time.time() - t0:.0f}s")
log("끝 · 받은 달", len(done), "/", len(MONTHS), "호출", CALLS[0], f"{time.time() - t0:.0f}s")
pathlib.Path(f"probe/out/rt_v2_{PART}_log.json").write_text(json.dumps({"done": done, "log": LOG}, ensure_ascii=False, indent=1))  # noqa: F821
