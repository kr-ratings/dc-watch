import os, re, time, json
import requests

DGK = os.environ.get("DATA_GO_KR_KEY", "").strip()
KEPCO = os.environ.get("KEPCO_API_KEY", "").strip()

S = requests.Session()
S.headers["User-Agent"] = "Mozilla/5.0 (dc-watch collector)"


def scrub(s):
    s = str(s)
    for k in (DGK, KEPCO):
        if k:
            s = s.replace(k, "***")
    return re.sub(r"(serviceKey|ServiceKey|apiKey)=[^&\s']+", r"\1=***", s)


class Quota:
    def __init__(self, limit):
        self.limit, self.used = limit, 0

    def take(self):
        if self.used >= self.limit:
            raise QuotaExceeded()
        self.used += 1


class QuotaExceeded(Exception):
    pass


def get(url, params, tries=4, timeout=(20, 90)):
    last = None
    for i in range(tries):
        try:
            r = S.get(url, params=params, timeout=timeout)
            if r.status_code >= 500:
                raise requests.exceptions.HTTPError(f"HTTP {r.status_code}")
            return r
        except requests.exceptions.RequestException as e:
            last = e
            time.sleep(4 * (i + 1))
    raise RuntimeError(scrub(repr(last)))


def load_json(path, default):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


def save_json(path, obj):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, separators=(",", ":"))
    os.replace(tmp, path)
