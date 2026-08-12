"""전역 설정: 위험 싱크(sink) 규칙집, 토큰 예산, 배치 정책."""

from dataclasses import dataclass, field

# ---------------------------------------------------------------------------
# 1) Sieve Agent 가 사용하는 결정론적 규칙집 (LLM 호출 0회)
#    weight: 이 싱크가 얼마나 "LLM 이 봐줄 가치가 있는가" 점수
#    cwe   : 매핑되는 CWE (리포트/프롬프트 힌트로 사용)
# ---------------------------------------------------------------------------
SINK_RULES = [
    # --- memory / buffer ---
    dict(id="MEM.STRCPY",   pattern=r"\b(strcpy|strcat|stpcpy)\s*\(",        weight=9,  cwe="CWE-120", tag="buffer"),
    dict(id="MEM.SPRINTF",  pattern=r"\b(sprintf|vsprintf)\s*\(",            weight=9,  cwe="CWE-787", tag="buffer"),
    dict(id="MEM.GETS",     pattern=r"\bgets\s*\(",                          weight=10, cwe="CWE-242", tag="buffer"),
    dict(id="MEM.MEMCPY",   pattern=r"\b(memcpy|memmove|bcopy)\s*\(",        weight=5,  cwe="CWE-787", tag="buffer"),
    dict(id="MEM.ALLOCA",   pattern=r"\balloca\s*\(",                        weight=7,  cwe="CWE-770", tag="memory"),
    dict(id="MEM.STRNCPY",  pattern=r"\b(strncpy|strncat)\s*\(",             weight=4,  cwe="CWE-170", tag="buffer"),
    dict(id="MEM.MALLOCMUL", pattern=r"\b(malloc|calloc|realloc)\s*\([^;]*[*+]", weight=6, cwe="CWE-190", tag="integer"),
    dict(id="MEM.FREE",     pattern=r"\bfree\s*\(",                          weight=3,  cwe="CWE-416", tag="memory"),

    # --- command / process ---
    dict(id="CMD.SYSTEM",   pattern=r"\b(system|popen|execlp|execvp)\s*\(",  weight=10, cwe="CWE-78",  tag="command"),

    # --- format string ---
    dict(id="FMT.PRINTF",   pattern=r"\b(printf|fprintf|syslog)\s*\(\s*[A-Za-z_][A-Za-z0-9_\->\.\[\]]*\s*\)", weight=8, cwe="CWE-134", tag="format"),

    # --- file / path ---
    dict(id="FS.TMP",       pattern=r"\b(tmpnam|mktemp|tempnam)\s*\(",       weight=8,  cwe="CWE-377", tag="race"),
    dict(id="FS.ACCESS",    pattern=r"\baccess\s*\(",                        weight=7,  cwe="CWE-367", tag="race"),
    dict(id="FS.CHMOD",     pattern=r"\b(chmod|umask)\s*\(",                 weight=5,  cwe="CWE-732", tag="perm"),
    dict(id="FS.OPENUSER",  pattern=r"\b(fopen|open)\s*\(\s*(argv|[a-z_]*path|[a-z_]*name)", weight=5, cwe="CWE-22", tag="path"),

    # --- untrusted input source ---
    dict(id="IN.ARGV",      pattern=r"\bargv\s*\[",                          weight=4,  cwe="CWE-20",  tag="source"),
    dict(id="IN.GETENV",    pattern=r"\bgetenv\s*\(",                        weight=6,  cwe="CWE-20",  tag="source"),
    dict(id="IN.SCANF",     pattern=r"\b(scanf|sscanf|fscanf)\s*\(",         weight=7,  cwe="CWE-20",  tag="source"),
    dict(id="IN.ATOI",      pattern=r"\b(atoi|atol|strtol)\s*\(",            weight=4,  cwe="CWE-190", tag="source"),
    dict(id="IN.READ",      pattern=r"\b(read|recv|recvfrom|fread)\s*\(",    weight=4,  cwe="CWE-20",  tag="source"),

    # --- crypto / random ---
    dict(id="CRY.RAND",     pattern=r"\b(rand|srand|random)\s*\(",           weight=5,  cwe="CWE-338", tag="crypto"),
]

# 싱크가 하나도 없으면 LLM 에 절대 보내지 않는다 (토큰 절약의 핵심)
MIN_CHUNK_SCORE = 6          # 이 점수 미만 청크는 폐기
MAX_CHUNK_LINES = 160        # 함수가 너무 길면 싱크 주변만 잘라낸다
CONTEXT_WINDOW_LINES = 25    # 싱크 위/아래로 확보할 최소 문맥

# ---------------------------------------------------------------------------
# 2) 배치 정책
# ---------------------------------------------------------------------------
BATCH_PLAN = {
    "batch1": dict(
        name="host_applications (사용자 입력 접점)",
        include=["host_applications/"],
        why="argv/파일경로 등 외부 입력이 직접 들어오는 CLI 앱 계층",
    ),
    "batch2": dict(
        name="containers (미디어 파서)",
        include=["containers/"],
        why="네트워크/파일에서 온 신뢰할 수 없는 미디어 데이터를 파싱하는 계층",
    ),
    "batch3": dict(
        name="interface (IPC/드라이버 브리지)",
        include=["interface/"],
        why="VCHIQ/IPC 로 프로세스 경계를 넘는 데이터가 오가는 계층",
    ),
}

# ---------------------------------------------------------------------------
# 3) 모델 라우팅 & 토큰 예산
# ---------------------------------------------------------------------------
MODEL_CHEAP = "claude-haiku-4-5-20251001"   # Analyst: 대량 1차 판정
MODEL_STRONG = "claude-sonnet-4-6"          # Verifier: 고위험만 정밀 재검증

TOKEN_BUDGET = dict(
    per_batch_input=400_000,
    per_batch_output=60_000,
    analyst_max_tokens=700,      # JSON 만 뱉게 강제 -> 출력 토큰 상한
    verifier_max_tokens=900,
)

SKIP_DIRS = {".git", "build", "opensrc", "makefiles", "docs", "pkgconfig"}
SOURCE_EXT = {".c", ".cpp", ".cc"}


@dataclass
class RunConfig:
    repo: str
    out_dir: str = "out"
    batches: list = field(default_factory=lambda: list(BATCH_PLAN.keys()))
    offline: bool = False          # True 면 LLM 호출 없이 후보까지만 생성
    max_chunks_per_batch: int = 40 # 배치당 LLM 에 올릴 최대 청크 (비용 상한)
