"""Agent 1 — Scout (정찰병).

역할: 저장소 전체를 걸어다니며 '지도'를 만든다. LLM 을 단 한 번도 쓰지 않는다.
산출: 파일 인벤토리 + 배치 분할 결과.
"""

import os
from .config import SKIP_DIRS, SOURCE_EXT, BATCH_PLAN


def index_repo(repo: str) -> list:
    files = []
    for root, dirs, names in os.walk(repo):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS and not d.startswith(".")]
        for nm in names:
            ext = os.path.splitext(nm)[1]
            if ext not in SOURCE_EXT:
                continue
            full = os.path.join(root, nm)
            rel = os.path.relpath(full, repo)
            try:
                size = os.path.getsize(full)
            except OSError:
                continue
            files.append(dict(rel=rel, abs=full, bytes=size))
    files.sort(key=lambda f: f["rel"])
    return files


def partition(files: list, batch_ids: list) -> dict:
    """배치별로 파일을 나눈다. 배치 = '아키텍처 계층' 기준으로 자른다."""
    out = {}
    for bid in batch_ids:
        spec = BATCH_PLAN[bid]
        sel = [f for f in files
               if any(f["rel"].replace("\\", "/").startswith(p) for p in spec["include"])]
        out[bid] = dict(meta=spec, files=sel)
    return out


def summarize(files: list) -> dict:
    total = sum(f["bytes"] for f in files)
    return dict(file_count=len(files), total_bytes=total,
                est_tokens_if_naive=int(total / 3.5))
