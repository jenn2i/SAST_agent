"""Agent 3/4/5 구현 + Context Broker(문맥 중개인) 도구.

Analyst  : 값싼 모델로 후보를 1차 판정 (대량)
Verifier : 강한 모델로 고위험만 반박 시도 (소량)
Reporter : 소스코드를 아예 안 보고 구조화된 결과만으로 리포트 작성
"""

import json
import os
import re
from .llm import parse_json
from .config import MODEL_CHEAP, MODEL_STRONG, TOKEN_BUDGET

PROMPT_DIR = os.path.join(os.path.dirname(__file__), "prompts")


def load_prompt(name: str) -> str:
    return open(os.path.join(PROMPT_DIR, name), encoding="utf-8").read()


SYSTEM = load_prompt("system_rulebook.md")


# ---------------------------------------------------------------------------
# Context Broker : Verifier 가 "이 심볼 더 보여줘" 라고 할 때만 코드를 퍼온다.
# 전체 파일을 미리 넣지 않는 것이 핵심 (필요할 때만 = on-demand)
# ---------------------------------------------------------------------------
class ContextBroker:
    def __init__(self, repo: str, index: list, budget_lines: int = 60):
        self.repo = repo
        self.map = {f["rel"]: f["abs"] for f in index}
        self.budget = budget_lines

    def fetch(self, symbols) -> str:
        if not symbols:
            return "(none requested)"
        out, used = [], 0
        for sym in symbols[:3]:
            sym = re.sub(r"[^A-Za-z0-9_]", "", str(sym))
            if not sym:
                continue
            rx = re.compile(rf"\b{sym}\b")
            for rel, ab in self.map.items():
                if used >= self.budget:
                    break
                try:
                    lines = open(ab, encoding="utf-8", errors="ignore").read().splitlines()
                except OSError:
                    continue
                for i, ln in enumerate(lines):
                    if rx.search(ln) and ("(" in ln or "=" in ln or "#define" in ln):
                        lo, hi = max(0, i - 2), min(len(lines), i + 3)
                        seg = "\n".join(f"{n+1}: {lines[n]}" for n in range(lo, hi))
                        out.append(f"--- {rel}:{i+1} (symbol: {sym})\n{seg}")
                        used += hi - lo
                        break
                if used >= self.budget:
                    break
        return "\n".join(out) if out else "(symbol not found in indexed sources)"


# ---------------------------------------------------------------------------
def run_analyst(llm, candidates, limit):
    tmpl = load_prompt("analyst.md")
    results = []
    for c in candidates[:limit]:
        user = tmpl.format(
            path=c["path"], func=c["func"], start=c["start"], end=c["end"],
            rules=", ".join(sorted({h["rule"] for h in c["hits"]})),
            cwes=", ".join(c["cwes"]), code=c["code"])
        raw = llm.call("analyst", MODEL_CHEAP, SYSTEM, user,
                       TOKEN_BUDGET["analyst_max_tokens"])
        verdict = parse_json(raw)
        results.append(dict(candidate=c, analyst=verdict, prompt=user))
    return results


def run_verifier(llm, analyzed, broker):
    tmpl = load_prompt("verifier.md")
    out = []
    for item in analyzed:
        a = item.get("analyst")
        # 고위험만 강한 모델로 올린다 -> 이것이 모델 라우팅 절약
        if not a or a.get("verdict") == "not_a_bug":
            continue
        if a.get("severity") in ("low", "none") and a.get("verdict") != "vulnerable":
            continue
        c = item["candidate"]
        extra = broker.fetch(a.get("missing_context") or [])
        user = tmpl.format(claim_json=json.dumps(a, ensure_ascii=False),
                           path=c["path"], start=c["start"], end=c["end"],
                           code=c["code"], extra=extra)
        raw = llm.call("verifier", MODEL_STRONG, SYSTEM, user,
                       TOKEN_BUDGET["verifier_max_tokens"])
        out.append(dict(candidate=c, analyst=a, verifier=parse_json(raw), prompt=user))
    return out


def build_reporter_prompt(batch_id, meta, stats, findings):
    tmpl = load_prompt("reporter.md")
    return tmpl.format(
        batch_id=batch_id, layer=meta["name"], file_count=stats["files"],
        functions=stats["functions"], candidates=stats.get("candidates", 0),
        analyzed=stats.get("analyzed", 0), confirmed=stats.get("confirmed", 0),
        findings=json.dumps(findings, ensure_ascii=False, indent=1)[:12000])
