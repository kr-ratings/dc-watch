"""공개 전 확인용: site/index.html에 dash.json을 넣은 한 파일짜리 미리보기를 만든다.
사용: python3 tools/preview.py <출력 경로>
"""
import json, re, sys

h = open("site/index.html", encoding="utf-8").read()
d = json.load(open("site/data/dash.json", encoding="utf-8"))
cov = d["permits"].get("coverage", {})
done, tot = sum(v[0] for v in cov.values()), sum(v[1] for v in cov.values()) or 1
note = ("건축 인허가는 전국 수집을 마쳤고 매일 바뀐 대장만 다시 받습니다." if d["permits"].get("complete") else
        f"건축 인허가는 전국 동·리 단위를 매일 나눠 도는 첫 바퀴 중({done / tot * 100:.0f}%, {done:,}/{tot:,} 단위)이라 아직 돌지 않은 지역은 빠져 있습니다.")
draft = (f'<div class="draft" role="note"><b>공개 전 시안</b><span>모든 칸이 원출처에서 자동으로 받은 실제 값입니다. {note} '
         f'용량(MW)과 제도·일정은 공개 보도·보고서를 매주 다시 검색해 갱신합니다.</span></div>')
title = re.search(r"<title>.*?</title>", h).group(0)
font = re.search(r'<link rel="preconnect".*?display=swap">', h, re.S).group(0)
style = re.search(r"<style>.*?</style>", h, re.S).group(0)
body = re.search(r"<body>(.*)</body>", h, re.S).group(1).replace("<!--DRAFT-->", draft)
data = "<script>window.DASH=" + json.dumps(d, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/") + ";</script>"
body = body.replace("<script>\nconst $=", data + "\n<script>\nconst $=", 1)
out = sys.argv[1] if len(sys.argv) > 1 else "preview.html"
open(out, "w", encoding="utf-8").write(title + "\n" + font + "\n" + style + "\n" + body)
print("preview", out, len(body))
