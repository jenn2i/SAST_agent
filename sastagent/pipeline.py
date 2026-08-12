"""오케스트레이터: Scout -> Sieve -> Analyst -> Verifier -> Reporter."""

import json
import os
import time
from . import scout, sieve, agents
from .llm import LLM, TokenLedger
from .config import BATCH_PLAN


def run(cfg):
    os.makedirs(cfg.out_dir, exist_ok=True)
    t0 = time.time()
    ledger = TokenLedger()
    llm = LLM(cache_dir=os.path.join(cfg.out_dir, ".llmcache"),
              offline=cfg.offline, ledger=ledger)

    # ---- Agent 1: Scout ---------------------------------------------------
    index = scout.index_repo(cfg.repo)
    repo_summary = scout.summarize(index)
    parts = scout.partition(index, cfg.batches)
    broker = agents.ContextBroker(cfg.repo, index)

    # 커버리지 점검: 어떤 배치에도 속하지 않는 파일이 있는지 명시적으로 기록한다.
    # (배치 include 경로가 아키텍처 계층 3개뿐이라, 그 경계 밖 디렉토리는 스캔에서 빠진다.)
    covered = set()
    for part in parts.values():
        covered.update(f["rel"] for f in part["files"])
    uncovered = sorted(f["rel"] for f in index if f["rel"] not in covered)

    report = dict(repo=cfg.repo, repo_summary=repo_summary, batches={},
                  coverage=dict(indexed_files=len(index),
                                covered_files=len(covered),
                                uncovered_files=uncovered,
                                note="uncovered_files 는 읽기 실패가 아니라, 3개 배치의 "
                                     "include 경로(host_applications/, containers/, "
                                     "interface/) 밖에 있어 이번 배치 계획에서 "
                                     "제외된 파일이다."))

    for bid, part in parts.items():
        meta, files = part["meta"], part["files"]

        # ---- Agent 2: Sieve ----------------------------------------------
        sv = sieve.sieve_files(files)
        cands, stats = sv["candidates"], sv["stats"]
        stats["candidates"] = len(cands)

        # ---- Agent 3: Analyst --------------------------------------------
        analyzed = agents.run_analyst(llm, cands, cfg.max_chunks_per_batch)
        stats["analyzed"] = len(analyzed)

        # ---- Agent 4: Verifier -------------------------------------------
        verified = agents.run_verifier(llm, analyzed, broker)
        stats["confirmed"] = sum(
            1 for v in verified
            if (v.get("verifier") or {}).get("decision") == "confirmed")

        # ---- Agent 5: Reporter (프롬프트만 조립; 실제 호출은 LLM 단계) ----
        findings = [dict(id=v["candidate"]["id"],
                         path=v["candidate"]["path"],
                         func=v["candidate"]["func"],
                         analyst=v["analyst"], verifier=v["verifier"])
                    for v in verified]
        rp = agents.build_reporter_prompt(bid, meta, stats, findings)
        narrative = llm.call("reporter", "claude-sonnet-4-6",
                             agents.SYSTEM, rp, 2000)

        report["batches"][bid] = dict(
            meta=meta, stats=stats,
            candidates=cands[:cfg.max_chunks_per_batch],
            findings=findings, narrative=narrative)

        # 토큰 절감 실측을 위한 계산
        naive = sum(f["bytes"] for f in files) / 3.5
        kept = sum(len(c["code"]) for c in cands[:cfg.max_chunks_per_batch]) / 3.5
        report["batches"][bid]["token_math"] = dict(
            naive_whole_files_tokens=int(naive),
            sieved_prompt_tokens=int(kept),
            reduction_pct=round(100 * (1 - kept / naive), 2) if naive else 0)

    report["ledger"] = ledger.total()
    report["ledger_rows"] = ledger.rows
    report["pending_llm_calls"] = len(llm.pending)
    report["elapsed_sec"] = round(time.time() - t0, 2)

    json.dump(report, open(os.path.join(cfg.out_dir, "result.json"), "w"),
              ensure_ascii=False, indent=1)
    # offline 모드: 실제로 보냈을 프롬프트를 '전부' 그대로 덤프 (과제 산출물)
    # 과거 버전은 앞 50개만 저장했으나, "전체 납품" 요건을 위해 전량 저장으로 변경.
    if llm.pending:
        json.dump(llm.pending,
                  open(os.path.join(cfg.out_dir, "pending_prompts.json"), "w"),
                  ensure_ascii=False, indent=1)
    return report
