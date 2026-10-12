"""한전 사이버지점 '전력공급 여유지도'(345kV 변전소 기준 공급 여유용량, 공개 화면)의 자료를 받는다.

- 전국: 시 · 도별로 그 지역에 전기를 보내는 345kV 변전소와 여유용량(MW)
- 시 · 도마다: 시 · 군 · 구별로 관할 345kV 변전소와 여유용량(MW)
한전 안내대로 변압기 용량 기준의 참고값이며, 실제 공급 가능 여부는 전기사용 신청 뒤 확정된다.
결과: data/kepco_headroom.json
"""
import datetime as dt, json, os, subprocess, sys, time, urllib.parse
sys.path.insert(0, os.path.dirname(__file__))
from common import save_json

BASE = "https://cyber.kepco.co.kr/ckepco/front/jsp/CO/T/E/"
OUT = "data/kepco_headroom.json"


def get(url, params, tries=3):
    """한전 사이버지점은 오래된 TLS 설정이라 파이썬 기본 HTTPS로는 접속이 거절되어 curl로 받는다(인증서 검증은 그대로)."""
    full = url + "?" + urllib.parse.urlencode(params)
    last = None
    for i in range(tries):
        p = subprocess.run(["curl", "-sS", "--max-time", "60", "-A", "Mozilla/5.0 (dc-watch)", "-e", BASE + "COTEPP00105.jsp", full],
                           capture_output=True)
        if p.returncode == 0 and p.stdout:
            return p.stdout
        last = p.stderr.decode("utf-8", "ignore")[:200]
        time.sleep(2 * (i + 1))
    raise RuntimeError(last)


def fetch(addr):
    raw = get(BASE + "COTEPP00105_json.jsp", {"addr": addr})
    for enc in ("cp949", "utf-8"):
        try:
            return json.loads(raw.decode(enc)).get("result") or []
        except (UnicodeDecodeError, ValueError):
            continue
    raise RuntimeError(f"응답 해석 실패 {raw[:80]!r}")


def mw(v):
    try:
        return round(float(v))
    except (TypeError, ValueError):
        return None


def collect():
    rows = fetch("all")
    if not rows:
        print("한전 여유정보 응답 없음 — 이전 자료 유지"); return
    subs, sido_subs = {}, {}
    for x in rows:
        sd, nm, v = (x.get("ADMSTNM") or "").strip(), (x.get("K345SSNM") or "").strip(), mw(x.get("OSTSDOVPLSGENT"))
        if not nm:
            continue
        subs[nm] = v
        sido_subs.setdefault(sd, []).append(nm)
    sgg = {}
    for sd in sido_subs:
        try:
            for x in fetch(sd):
                g, nm, v = (x.get("ADMSTNM") or "").strip(), (x.get("K345SSNM") or "").strip(), mw(x.get("OSTSDOVPLSGENT"))
                if g and nm:
                    sgg.setdefault(sd, {}).setdefault(g, {})[nm] = v
                    subs.setdefault(nm, v)
        except Exception as e:  # 한 시 · 도가 실패해도 나머지는 남긴다
            print("err", sd, repr(e)[:120])
        time.sleep(0.5)
    out = {"updated": dt.date.today().isoformat(), "subs": subs, "sido": sido_subs,
           "sgg": {sd: {g: v for g, v in gs.items()} for sd, gs in sgg.items()},
           "src": "한국전력 사이버지점 전력공급 여유지도(345kV 변전소 기준)"}
    save_json(OUT, out)
    print("kepco headroom", len(subs), "substations,", sum(len(v) for v in sgg.values()), "sgg")


if __name__ == "__main__":
    collect()
