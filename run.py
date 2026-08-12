#!/usr/bin/env python3
"""엔트리포인트.
  python run.py --repo ../userland-master --offline      # LLM 없이 후보/프롬프트만
  ANTHROPIC_API_KEY=... python run.py --repo ../userland-master
"""
import argparse, json
from sastagent.config import RunConfig, BATCH_PLAN
from sastagent import pipeline

p = argparse.ArgumentParser()
p.add_argument("--repo", required=True)
p.add_argument("--out", default="out")
p.add_argument("--offline", action="store_true")
p.add_argument("--max-chunks", type=int, default=40)
p.add_argument("--batches", nargs="*", default=list(BATCH_PLAN))
a = p.parse_args()

cfg = RunConfig(repo=a.repo, out_dir=a.out, batches=a.batches,
                offline=a.offline, max_chunks_per_batch=a.max_chunks)
r = pipeline.run(cfg)

print(f"repo: {r['repo_summary']}")
for bid, b in r["batches"].items():
    s, t = b["stats"], b["token_math"]
    print(f"\n[{bid}] {b['meta']['name']}")
    print(f"  files={s['files']} functions={s['functions']} "
          f"sink_hit={s['functions_with_sink']} candidates={s['candidates']} "
          f"dedup={s['deduped']} dropped={s['dropped_low_score']}")
    print(f"  tokens naive={t['naive_whole_files_tokens']:,} -> "
          f"sieved={t['sieved_prompt_tokens']:,} ({t['reduction_pct']}% 절감)")
print(f"\nelapsed={r['elapsed_sec']}s  pending_llm_calls={r['pending_llm_calls']}")

cov = r["coverage"]
if cov["uncovered_files"]:
    print(f"\n[WARN] 배치 범위 밖 파일 {len(cov['uncovered_files'])}개 "
          f"(읽기 실패 아님, 배치 include 경로 밖):")
    for f in cov["uncovered_files"]:
        print(f"  - {f}")
else:
    print("\n커버리지: 인덱싱된 모든 파일이 배치에 포함됨")
