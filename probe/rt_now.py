"""최근 3개월만 받아 평당가(공급면적 환산 · 전용)를 다시 낸다. 변동률은 이전 rt_agg 결과를 쓴다."""
import os, runpy
os.environ["NOW_ONLY"] = "1"
runpy.run_path("probe/rt_agg.py", run_name="__main__")
