"""전력거래소 SMP(월) · EPSIS 시도별 발전량(연)."""
import datetime as dt, re
from common import get, load_json, save_json

OUT = "data/power_open.json"


def smp(d):
    r = get("https://new.kpx.or.kr/smpMonthly.es", {"mid": "a10606080300", "device": "pc"})
    h = r.text
    ser = d.setdefault("smp", {})
    i = h.find("월별 SMP")
    t = h[i:h.find("</table>", i)] if i > 0 else ""
    rows = re.findall(r"<tr>(.*?)</tr>", t, re.S)
    kind = None
    for row in rows:
        cells = [re.sub(r"<[^>]+>|\s+", "", c) for c in re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", row, re.S)]
        if not cells:
            continue
        if "SMP" in cells[0]:
            kind, cells = cells[0].replace("SMP", ""), cells[1:]
        if kind != "육지" or not cells or not cells[0].endswith("년"):
            continue
        yy = 2000 + int(cells[0][:-1])
        for mi, v in enumerate(cells[1:13], 1):
            if v:
                ser[f"{yy}-{mi:02d}"] = float(v)
    # 그래프용 최근 30개월 배열로 앞쪽 이력 보강
    m = re.search(r"var smpShore\s*=\s*\[([^\]]+)\]", h)
    if m and ser:
        vals = [float(x) for x in m.group(1).split(",") if x.strip()]
        last = max(ser)
        y, mo = map(int, last.split("-"))
        for v in reversed(vals):
            ser.setdefault(f"{y}-{mo:02d}", v)
            mo -= 1
            if mo == 0:
                y, mo = y - 1, 12
    d["smp"] = dict(sorted(ser.items()))


def epsis_gen(d):
    r = get("https://epsis.kpx.or.kr/epsisnew/selectEkgeGepGbaChart.do", {"menuId": "060104"})
    h = r.text
    cols = dict((k, v) for k, v in re.findall(r'dataField=\\?"(c\d+)\\?"[^>]*?headerText=\\?"([^"\\]+)', h))
    gen = {}
    for blk in re.finditer(r'((?:c\d+ = textFormmat\("[^"]*",count\);\s*)+)gridData\.push\(\{"year":"(\d{4})"', h):
        vals = dict(re.findall(r'(c\d+) = textFormmat\("([^"]*)"', blk.group(1)))
        row = {}
        for c, nm in cols.items():
            v = vals.get(c)
            try:
                row[nm] = round(float(v), 1)
            except (TypeError, ValueError):
                pass
        gen[blk.group(2)] = row
    d["gen_sido_mwh"] = gen


def collect():
    d = load_json(OUT, {})
    for fn in (smp, epsis_gen):
        try:
            fn(d)
        except Exception as e:
            d.setdefault("errors", {})[fn.__name__] = repr(e)[:200]
    d["updated"] = dt.date.today().isoformat()
    save_json(OUT, d)
    print("smp", list(d.get("smp", {}).items())[-2:], "gen years", sorted(d.get("gen_sido_mwh", {}))[-2:])


if __name__ == "__main__":
    collect()
