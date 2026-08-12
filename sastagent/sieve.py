"""Agent 2 — Sieve (체).

역할: 규칙집으로 '위험 싱크'가 있는 함수만 골라낸다. LLM 호출 0회.
이 단계가 토큰 절약의 90% 를 담당한다. (전체 소스 -> 후보 함수 몇십 개)
또한 정규화 해시로 중복 함수를 접어(fold) 같은 코드를 두 번 분석하지 않는다.
"""

import hashlib
import re
from .config import SINK_RULES, MIN_CHUNK_SCORE, MAX_CHUNK_LINES, CONTEXT_WINDOW_LINES
from .slicer import slice_functions, shrink

_COMPILED = [(r, re.compile(r["pattern"])) for r in SINK_RULES]
_WS = re.compile(r"\s+")
_CMT = re.compile(r"//[^\n]*|/\*.*?\*/", re.S)


def normalize(code: str) -> str:
    """주석/공백 차이를 무시한 정규화 (중복 제거용)."""
    return _WS.sub(" ", _CMT.sub("", code)).strip()


def fingerprint(code: str) -> str:
    return hashlib.sha1(normalize(code).encode("utf-8", "ignore")).hexdigest()[:16]


def scan_chunk(chunk) -> dict:
    hits, score, tags, cwes = [], 0, set(), set()
    for line_no, line in enumerate(chunk.code.splitlines(), start=chunk.start):
        s = line.strip()
        if s.startswith("//") or s.startswith("*"):
            continue
        for rule, rx in _COMPILED:
            if rx.search(line):
                hits.append(dict(rule=rule["id"], line=line_no, cwe=rule["cwe"],
                                 text=line.strip()[:200]))
                score += rule["weight"]
                tags.add(rule["tag"])
                cwes.add(rule["cwe"])
    # source(입력) + sink(위험함수) 가 같은 함수에 공존하면 가중치 부여
    if "source" in tags and ({"buffer", "command", "format", "path"} & tags):
        score = int(score * 1.6)
    return dict(hits=hits, score=score, tags=sorted(tags), cwes=sorted(cwes))


def sieve_files(files: list, min_score: int = MIN_CHUNK_SCORE) -> dict:
    """파일 리스트 -> 후보 청크 리스트 + 통계."""
    candidates, seen = [], {}
    stats = dict(files=0, functions=0, functions_with_sink=0,
                 dropped_low_score=0, deduped=0, loc_total=0, loc_kept=0)

    for f in files:
        try:
            text = open(f["abs"], encoding="utf-8", errors="ignore").read()
        except OSError:
            continue
        stats["files"] += 1
        stats["loc_total"] += text.count("\n") + 1
        for ch in slice_functions(f["rel"], text):
            stats["functions"] += 1
            r = scan_chunk(ch)
            if not r["hits"]:
                continue
            stats["functions_with_sink"] += 1
            if r["score"] < min_score:
                stats["dropped_low_score"] += 1
                continue
            fp = fingerprint(ch.code)
            if fp in seen:
                seen[fp]["duplicates"].append(f"{ch.path}:{ch.start}")
                stats["deduped"] += 1
                continue
            small = shrink(ch, [h["line"] for h in r["hits"]],
                           MAX_CHUNK_LINES, CONTEXT_WINDOW_LINES)
            item = dict(
                id=fp, path=ch.path, func=ch.func, start=ch.start, end=ch.end,
                loc=ch.loc, score=r["score"], tags=r["tags"], cwes=r["cwes"],
                hits=r["hits"], code=small.code, duplicates=[],
            )
            seen[fp] = item
            candidates.append(item)
            stats["loc_kept"] += small.code.count("\n") + 1

    candidates.sort(key=lambda c: -c["score"])
    return dict(candidates=candidates, stats=stats)
