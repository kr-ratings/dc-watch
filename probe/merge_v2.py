"""(로컬 도구) dc-watch probe-out-N 브랜치의 probe/out/v2/*.json.gz 를 apt-watch cache/rt 로 옮기고,
아직 옛 형식인 달을 v2_todo_new.txt / v2_todo_old.txt 로 적는다.
사용: python3 probe/merge_v2.py <dc-watch 경로> <apt-watch 경로> N [N ...]"""
import gzip, pathlib, shutil, subprocess, sys, tarfile, io

dc, apt, nums = pathlib.Path(sys.argv[1]), pathlib.Path(sys.argv[2]), sys.argv[3:]
dst = apt / "cache/rt"; moved = 0
for n in nums:
    ref = f"refs/remotes/origin/probe-out-{n}"
    subprocess.run(["git", "-C", str(dc), "fetch", "-q", "origin", f"refs/heads/probe-out-{n}:{ref}"], check=True)
    tar = subprocess.run(["git", "-C", str(dc), "archive", ref, "probe/out"], check=True, capture_output=True).stdout
    with tarfile.open(fileobj=io.BytesIO(tar)) as tf:
        for m in tf.getmembers():
            if m.name.startswith("probe/out/v2/") and m.name.endswith(".json.gz"):
                b = tf.extractfile(m).read()
                if b'"v":2' in gzip.decompress(b)[:64]:
                    (dst / pathlib.Path(m.name).name).write_bytes(b); moved += 1
def v2(f):
    with gzip.open(f, "rt", encoding="utf-8") as fh:
        return '"v":2' in fh.read(64)
left = sorted(f.name[:6] for f in dst.glob("*.json.gz") if not v2(f))
new, old = [m for m in left if m >= "201601"], [m for m in left if m < "201601"]
here = pathlib.Path(__file__).parent
(here / "v2_todo_new.txt").write_text("\n".join(new) + "\n"); (here / "v2_todo_old.txt").write_text("\n".join(old) + "\n")
print("옮긴 달", moved, "· 남은 옛 형식 달: 2016~", len(new), "/ ~2015", len(old))
