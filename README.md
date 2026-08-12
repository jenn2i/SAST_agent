# ai-sast-userland

`raspberrypi/userland` 를 대상으로 동작하는 **멀티 에이전트 SAST 도구**.

LLM 을 쓰지 않는 에이전트 2개가 후보를 극단적으로 좁히고,
LLM 에이전트 3개가 판정 · 반대신문 · 보고를 나눠 맡는다.

```
Scout ─▶ Sieve ─▶ Analyst ─▶ Verifier ─▶ Reporter
(무료)   (무료)   (Haiku)    (Sonnet)    (Sonnet)
```

## 실행

```bash
# 1) LLM 없이 후보 선별 + 프롬프트 덤프까지 (API 키 불필요)
python3 run.py --repo /path/to/userland --offline

# 2) 전체 파이프라인
export ANTHROPIC_API_KEY=sk-ant-...
python3 run.py --repo /path/to/userland

# 3) 리포트 생성
python3 make_report.py     # -> out/report.md, out/report.html
```

의존성 없음 (Python 3.8+ 표준 라이브러리만 사용).

## 실측 결과

| 항목 | 값 |
|---|---|
| 인덱싱한 소스 파일 | 277개 (5.4 MB) |
| 슬라이싱된 함수 | 3,687개 |
| 싱크 적중 함수 | 428개 |
| Sieve 통과 후보 | 225개 |
| 파일 통째로 넣을 때 토큰 | ~1,523,902 |
| 실제 프롬프트 토큰 | ~95,437 (**93.7% 절감**) |
| Scout+Sieve 소요 시간 | 2.13초 |
| 확정 / 하향 / 기각 | 8 / 3 / 4 |

주요 확정 취약점:

- `hello_teapot/models.c:243` — 폭 지정자 없는 `sscanf("%s")` 가
  256바이트 라인을 `char name[32]` 에 복사. 경계 검사는 쓰기 **이후**에 실행. (치명적)
- `hello_teapot/models.c:252` — `printf(s)` 포맷 스트링. `s` 는 파일 내용. (높음)
- `vmcs_host/vcilcs.c:1048` — IPC 로 받은 길이 필드로 `memcpy`. 유일한 방어인
  `vcos_assert` 는 릴리스 빌드에서 `(void)0` 로 사라짐. (높음)

전체 내용은 [`out/report.md`](out/report.md) 참고.

## 문서

| 문서 | 내용 |
|---|---|
| [`docs/architecture.md`](docs/architecture.md) | 에이전트 구성도, 역할·스킬 정의 |
| [`docs/token_strategy.md`](docs/token_strategy.md) | 토큰 절약 9가지 기법과 도입 이유 |
| [`docs/prompts.md`](docs/prompts.md) | 런타임 프롬프트 전문 + 설계 메타 프롬프트 |
| [`docs/differentiation.md`](docs/differentiation.md) | 기존 SAST 도구와의 차별점 |

## 구조

```
run.py                  엔트리포인트
make_report.py          Reporter 단계 (md/html 생성)
sastagent/
  config.py             싱크 규칙집 21개, 배치 정책, 토큰 예산
  scout.py              Agent 1 — 저장소 인덱싱 · 배치 분할
  slicer.py             함수 단위 분할기 (외부 파서 의존성 없음)
  sieve.py              Agent 2 — 규칙 매칭 · 점수화 · 중복 제거
  agents.py             Agent 3/4/5 + Context Broker
  llm.py                API 래퍼 (프롬프트 캐싱 · 디스크 캐시 · 토큰 원장)
  pipeline.py           오케스트레이터
  prompts/              4개 프롬프트 템플릿
out/
  result.json           파이프라인 전체 산출물
  llm_stage_results.json  Analyst/Verifier 판정 결과
  pending_prompts.json  offline 모드에서 전송 예정이던 프롬프트 덤프
  report.md / report.html
```

## 한계

- 데이터 흐름 분석은 **함수 내부**로 한정된다. 함수 간 흐름은 Verifier 가
  Context Broker 로 필요할 때만 부분 조회한다.
- 사내 커스텀 래퍼 함수(`safe_copy()` 같은)는 `config.SINK_RULES` 에
  직접 추가해야 인식된다.
- 완전성보다 정밀도를 택한 도구다. 오탐을 줄이는 대신 미탐이 존재한다.
