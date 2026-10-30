"""서울 25개 구 · 2006-01 ~ 지난달 아파트 매매 실거래 → 거래 한 건씩(시험: 같은 단지 · 같은 면적끼리 지수).

- 키 · 요청 주소는 어떤 출력에도 남기지 않는다(clean()).
- 달마다 probe/out/unit/YYYYMM.json.gz: {"ym", "r": [[단지, 전용면적, 층, 거래금액(만원), 일, 법정동, 건축년도], ...]}
  (해제 거래 제외, 같은 거래 중복 제거)
"""
import concurrent.futures as cf, datetime as dt, gzip, json, os, pathlib, re, threading, time, urllib.parse
import xml.etree.ElementTree as ET
import requests

KEY = os.environ.get("DATA_GO_KR_KEY", "").strip()
OUT = pathlib.Path("probe/out/unit"); OUT.mkdir(parents=True, exist_ok=True)
EP = "https://apis.data.go.kr/1613000/RTMSDataSvcAptTradeDev/getRTMSDataSvcAptTradeDev"
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


CODES = sorted({x[1] for x in json.load(open("data/bjd_units.json", encoding="utf-8")) if x[0].startswith("서울")})
today = dt.date.today(); last = (today.replace(day=1) - dt.timedelta(days=1))
MONTHS, y, m = [], 2006, 1
while (y, m) <= (last.year, last.month):
    MONTHS.append(f"{y}{m:02d}"); y, m = (y + (m == 12), m % 12 + 1)
MONTHS.reverse()
log("달", len(MONTHS), MONTHS[0], "~", MONTHS[-1], "구", len(CODES))

sess = requests.Session(); lock = threading.Lock(); STOP = [False]; CALLS = [0]

# 접속 확인(안 되면 바로 끝냄)
for att in range(4):
    try:
        sess.get(EP, params={"serviceKey": KEY, "LAWD_CD": "11680", "DEAL_YMD": MONTHS[0], "pageNo": 1, "numOfRows": 1}, timeout=(10, 30)); break
    except Exception as e:  # noqa
        log("접속 확인 실패", att + 1, type(e).__name__); time.sleep(10)
else:
    pathlib.Path("probe/out/rt_unit_log.json").write_text(json.dumps({"done": [], "log": LOG}, ensure_ascii=False, indent=1)); raise SystemExit(0)


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
                    log("실패", code, ymd, type(e).__name__); return None
                time.sleep(2 + att * 3)
        if page * 1000 >= tot:
            return rows
        page += 1


t0 = time.time(); done = []
for ym in MONTHS:
    if STOP[0]:
        break
    with cf.ThreadPoolExecutor(5) as ex:
        res = list(ex.map(lambda c: (c, fetch(c, ym)), CODES))
    if any(v is None for _, v in res):
        log("미완료 달 저장 안 함", ym)
        continue
    seen, out = set(), []
    for c, rows in res:
        for x in rows:
            if (x.get("cdealType") or "").strip() in ("O", "o"):
                continue
            try:
                amt = int(float((x.get("dealAmount") or "0").replace(",", ""))); ar = float(x.get("excluUseAr") or 0)
            except ValueError:
                continue
            if amt <= 0 or ar < 10:
                continue
            d = (x.get("umdNm") or "").strip()
            sig = (x.get("aptSeq") or x.get("aptNm"), d, x.get("dealYear"), x.get("dealMonth"), x.get("dealDay"), x.get("dealAmount"), x.get("floor"), x.get("excluUseAr"))
            if sig in seen:
                continue
            seen.add(sig)
            a = x.get("aptSeq") or f"{c}|{d}|{x.get('jibun', '')}|{x.get('aptNm', '')}"
            try:
                fl = int(x.get("floor") or 0)
            except ValueError:
                fl = 0
            try:
                by = int(x.get("buildYear") or 0)
            except ValueError:
                by = 0
            out.append([a, round(ar, 2), fl, amt, int(x.get("dealDay") or 0), f"{c}|{d}", by])
    (OUT / f"{ym}.json.gz").write_bytes(gzip.compress(json.dumps({"ym": ym, "r": out}, ensure_ascii=False, separators=(",", ":")).encode(), mtime=0))
    done.append(ym)
    if len(done) % 12 == 0:
        log("저장", ym, "누적 달", len(done), "호출", CALLS[0], f"{time.time() - t0:.0f}s")
log("끝 · 받은 달", len(done), "/", len(MONTHS), "호출", CALLS[0], f"{time.time() - t0:.0f}s", "중단" if STOP[0] else "")
pathlib.Path("probe/out/rt_unit_log.json").write_text(json.dumps({"done": done, "log": LOG}, ensure_ascii=False, indent=1))
