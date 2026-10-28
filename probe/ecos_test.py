"""ECOS가 GitHub Actions 러너에서 열리는지 확인(공개 견본 키만 씀)."""
import json, pathlib, time, requests
OUT = pathlib.Path("probe/out"); OUT.mkdir(parents=True, exist_ok=True); res = {}
for name, url in [("ecos_https", "https://ecos.bok.or.kr/api/StatisticSearch/sample/json/kr/1/10/161Y008/M/202601/202608/BBGA00"),
                  ("ecos_http", "http://ecos.bok.or.kr/api/StatisticSearch/sample/json/kr/1/10/161Y008/M/202601/202608/BBGA00"),
                  ("ecos_home", "https://ecos.bok.or.kr/")]:
    for att in range(3):
        t = time.time()
        try:
            r = requests.get(url, timeout=(20, 40), headers={"User-Agent": "Mozilla/5.0"})
            res[f"{name}_{att}"] = {"status": r.status_code, "sec": round(time.time() - t, 1), "len": len(r.content), "head": r.text[:80]}
        except Exception as e:  # noqa
            res[f"{name}_{att}"] = {"err": type(e).__name__, "msg": str(e)[:160], "sec": round(time.time() - t, 1)}
        time.sleep(2)
(OUT / "ecos_test.json").write_text(json.dumps(res, ensure_ascii=False, indent=1)); print(json.dumps(res, ensure_ascii=False, indent=1))
