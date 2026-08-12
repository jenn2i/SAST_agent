# AI 기반 SAST 에이전트 — 통합 리포트

**프로젝트명** `ai-sast-userland` · **대상** `github.com/raspberrypi/userland` (master)
**작성** BoB15 컨설팅 트랙 박정은

---

## 목차

1. [한눈에 보기 (Executive Summary)](#1-한눈에-보기-executive-summary)
2. [에이전트 구성도 (Architecture)](#2-에이전트-구성도-architecture)
3. [스킬 설계 시 주안점](#3-스킬-설계-시-주안점)
4. [토큰 절약 방안 — 설계와 도입 이유](#4-토큰-절약-방안--설계와-도입-이유)
5. [작성 시 사용한 프롬프트](#5-작성-시-사용한-프롬프트)
6. [산출물 — 분석 결과](#6-산출물--분석-결과)
7. [기존 도구와의 차별점](#7-기존-도구와의-차별점)
8. [한계와 향후 과제](#8-한계와-향후-과제)

---

## 1. 한눈에 보기 (Executive Summary)

> **한 문장 요약** — *"LLM 은 비싸니까, LLM 이 꼭 봐야 하는 코드만 골라서 보여준다."*

160,000줄짜리 저장소를 LLM 컨텍스트에 통째로 넣는 건 불가능하다. 그래서
**LLM 을 쓰지 않는 에이전트 2개**로 후보를 극단적으로 좁힌 뒤,
**LLM 에이전트 3개**가 판정 → 반대신문 → 보고를 나눠 맡는 5-에이전트
파이프라인을 만들었다.

### 핵심 수치

| 항목 | 값 |
|---|---|
| 인덱싱한 소스 파일 | 277개 (5.4 MB) |
| 슬라이싱된 함수 | 3,687개 |
| 위험 싱크 적중 함수 | 428개 (11.6%) |
| Sieve 통과 후보 | 225개 |
| 파일 통째로 넣을 때 예상 토큰 (bytes 기반 추정) | 약 1,523,902 |
| Sieve 통과 후 프롬프트 페이로드 추정 토큰 | 약 95,437 (**93.7% 페이로드 절감 추정**) |
| Scout + Sieve 소요 시간 | 2.13초 (LLM 호출 0회) |
| 정밀 판정 건수 | 15건 |
| 확정 / 하향 / 기각 | 8건 / 3건 / 4건 |
| 심각도 분포 | 치명적 2 · 높음 5 · 보통 1 · 낮음 3 |

*토큰 수치는 Sieve 통과 코드의 분량 기준 추정치이며, 판정 결과는
API 실행 대신 동일 프롬프트 절차를 수동 적용해 도출했다 — 방법론
상세는 8장 참고.*

### 가장 중요한 발견 두 가지

- **`hello_teapot/models.c` Wavefront `.obj` 로더** — 경계 검사 없는
  `sscanf("%s")` 로 256바이트 파일 라인을 32바이트 필드에 복사 (치명적).
  같은 결함이 `raspicam/gl_scenes/models.c` 에 복제되어 있음.
- **`interface/vmcs_host/vcilcs.c` IPC 수신 경로** — 경계 검사를
  `vcos_assert` 에만 의존하는데, 이 매크로는 **릴리스 빌드에서
  `(void)0` 으로 사라짐** (높음).

---


## 2. 에이전트 구성도 (Architecture)

### 2-1. 전체 흐름

```
                    raspberrypi/userland  (277 files / 5.4 MB / ~1.55M tokens)
                                 │
   ┌─────────────────────────────▼──────────────────────────────┐
   │  Agent 1 : Scout  (정찰병)                    LLM 호출 0회   │
   │  · 저장소 워킹, 소스 파일 인덱싱                            │
   │  · 아키텍처 계층 기준으로 3개 batch 분할                    │
   └─────────────────────────────┬──────────────────────────────┘
                                 │  batch1 / batch2 / batch3
   ┌─────────────────────────────▼──────────────────────────────┐
   │  Agent 2 : Sieve  (체)                        LLM 호출 0회  │
   │  · Slicer 로 함수 단위 분할 (3,687 functions)               │
   │  · 21개 싱크 규칙으로 점수화 → 저점수 폐기                  │
   │  · 정규화 해시로 중복 함수 접기(fold)                       │
   │  · 긴 함수는 싱크 주변만 shrink                             │
   │  ⇒ 여기서 토큰 96.7% 가 사라진다                            │
   └─────────────────────────────┬──────────────────────────────┘
                                 │  225 candidates
   ┌─────────────────────────────▼──────────────────────────────┐
   │  Agent 3 : Analyst  (1차 판정관)      model: Haiku 4.5      │
   │  · 후보 1건 = 호출 1회, JSON 스키마 강제                    │
   │  · vulnerable / needs_context / not_a_bug 3분류             │
   │  · 모르면 반드시 needs_context (환각 방지 1차 방어선)       │
   └─────────────────────────────┬──────────────────────────────┘
                                 │  고위험만 승격
   ┌─────────────────────────────▼──────────────────────────────┐
   │  Agent 4 : Verifier  (반대신문관)     model: Sonnet 4.6     │
   │  · Analyst 주장을 "반박하는" 것이 목표                      │
   │  · 인용한 라인이 실제 코드와 다르면 → 환각으로 기각         │
   │  · 부족한 문맥은 Context Broker 로 on-demand 조회           │
   │  ⇒ confirmed / downgraded / rejected                        │
   └─────────────────────────────┬──────────────────────────────┘
                                 │  구조화된 findings (소스 없음)
   ┌─────────────────────────────▼──────────────────────────────┐
   │  Agent 5 : Reporter  (보고관)         model: Sonnet 4.6     │
   │  · 원본 소스를 아예 보지 않는다 (설계상 의도)               │
   │  · batch당 1회 호출 → report.md / report.html               │
   └────────────────────────────────────────────────────────────┘

   ┌────────────────────────────────────────────────────────────┐
   │  Tool : Context Broker  (문맥 중개인)          LLM 아님     │
   │  Verifier 가 "이 심볼 더 보여줘" 라고 할 때만 코드를 퍼옴   │
   │  1회 최대 3심볼 / 60줄 예산 → 문맥 요청이 토큰 폭탄이 되는  │
   │  것을 막는다                                                │
   └────────────────────────────────────────────────────────────┘
```

### 2-2. 에이전트별 역할과 스킬

| # | 에이전트 | 역할(Role) | 보유 스킬(Skill) | 모델 | 호출 수 |
|---|---|---|---|---|---|
| 1 | **Scout** | 저장소 지도 제작 | 파일시스템 워킹, 확장자/디렉터리 필터, 계층 기반 배치 분할 | 없음 | 0 |
| 2 | **Sieve** | 후보 선별 | 함수 단위 슬라이싱, 싱크 규칙 매칭, source↔sink 동거 가중치, 정규화 해시 dedup, shrink | 없음 | 0 |
| 3 | **Analyst** | 1차 판정 | 데이터 출처 추적, 경계 검사 유무 판단, JSON 스키마 준수, 모를 때 `needs_context` 선언 | Haiku 4.5 | 후보당 1 |
| 4 | **Verifier** | 반대신문 | 라인 대조 환각 탐지, 상수·매크로 추적, 도달 가능성 반박, 심각도 조정 | Sonnet 4.6 | 고위험당 1 |
| 5 | **Reporter** | 보고서 작성 | 집계, 한국어 서술, 표 생성 — **소스 코드 접근 없음** | Sonnet 4.6 | 배치당 1 |

**Analyst 와 Verifier 를 나눈 이유** — 한 에이전트가 "찾고" 동시에
"검증"하면 자기가 쓴 말을 옹호하게 된다. Verifier 프롬프트에는
명시적으로 이렇게 써서 인센티브를 반대로 걸었다.

> *"You are rewarded for correctly rejecting false positives, not for agreeing."*

이 분리로 정밀 판정 15건 중 **4건 기각, 3건 하향**이 나왔다.

### 2-3. Sieve 규칙집 구조

각 규칙은 `(정규식, 가중치, CWE, 태그)` 4-튜플이다.

```python
dict(id="MEM.STRCPY", pattern=r"\b(strcpy|strcat|stpcpy)\s*\(",
     weight=9, cwe="CWE-120", tag="buffer")
```

핵심은 **source ↔ sink 동거 가중치**다. `argv`/`getenv`/`fread` 같은
*입력원(source)* 과 `strcpy`/`system`/`sprintf` 같은 *위험 지점(sink)* 이
**같은 함수 안에 함께 있으면** 점수를 1.6배로 올린다. 데이터 흐름 분석을
안 해도 "입력이 들어오는 함수에서 위험한 걸 한다"는 가장 흔한 취약 패턴을
값싸게 잡아낼 수 있다.

### 2-4. 배치 분할 기준

파일 개수로 3등분하지 않고 **아키텍처 계층**으로 나눴다. 같은 계층 안의
코드는 위협 모델이 비슷해서, 배치 단위로 일관된 판단이 가능하다.

| 배치 | 계층 | 위협 모델 |
|---|---|---|
| batch1 | `host_applications/` | CLI 인자·파일 경로 등 **사용자 입력**이 직접 들어옴 |
| batch2 | `containers/` | 네트워크·파일에서 온 **신뢰할 수 없는 미디어 데이터** 파싱 |
| batch3 | `interface/` | VCHIQ/ILCS 로 **프로세스·펌웨어 경계**를 넘는 데이터 |

---

## 3. 스킬 설계 시 주안점

각 에이전트에게 "스킬"을 부여할 때 고려한 원칙을 정리한다.

### 3-1. Scout / Sieve — "판단하지 않는 스킬"

이 두 에이전트는 의도적으로 LLM 을 배제했다. 스킬을 설계할 때 기준은
**"정규식과 괄호 균형 계산만으로 답이 나오는 일인가?"** 였다.
- 파일 인덱싱, 디렉터리 필터링 → 답이 결정론적이므로 LLM 불필요
- 함수 단위 슬라이싱 → tree-sitter 같은 외부 파서 의존성 없이, 주석/문자열
  상태 머신 + 중괄호 카운팅으로 직접 구현 (환경 제약 없이 어디서든 동작)
- 싱크 규칙 매칭 → "위험한 함수 이름이 있는가"는 판단이 아니라 검색이다

**주안점**: LLM 이 잘하는 일(맥락 판단)과 못 미더운 일(정확한 문자열 탐색)을
분리하고, 후자는 절대 LLM 에 맡기지 않는다.

### 3-2. Analyst — "정해진 순서로 생각하게 하는 스킬"

Analyst 의 스킬은 데이터 출처 추적 능력인데, 이를 프롬프트 안에서
**강제된 사고 순서**로 스킬화했다.

```
1. Where does the data COME FROM?
2. Is there a bound check between source and sink, INSIDE this slice?
3. Is the bound derived from the DESTINATION's size, or the SOURCE's data?
4. If you cannot answer (1), the verdict is needs_context.
```

**주안점**: "판단해라"라고만 하면 LLM 마다 접근 순서가 들쭉날쭉해서
품질이 흔들린다. 체크리스트를 순서대로 강제하면 같은 프롬프트를
어느 모델에 태워도 결과 품질 편차가 줄어든다. 3번 항목("목적지 크기
기준인가, 원본 데이터 기준인가")이 결과적으로 가장 많은 오탐을 걸러냈다.

### 3-3. Verifier — "반박을 시키는 스킬"

Verifier 의 스킬은 "코드를 검증하는 것"이 아니라 **"동료의 주장에서
허점을 찾는 것"** 으로 정의했다. 체크리스트 마지막 항목을 이렇게 뒀다.

> *"Would a competent maintainer accept this as a bug report, or close it as noise?"*

**주안점**: 판정 기준을 추상적인 "위험도"가 아니라 **실무 수용성**으로
옮기면, "이론적으로는 위험하지만 현실적으로 무해한" 코드를 정확히
하향시킬 수 있다. 또한 체크리스트 1번(라인 대조)은 환각 탐지 스킬로
따로 분리해서, Analyst 의 주장이 실제 코드와 일치하는지부터 기계적으로
검사하게 했다.

### 3-4. Reporter — "보지 않는 것도 스킬이다"

Reporter 는 원본 소스에 접근하지 않는다는 제약 자체가 스킬 설계다.

**주안점**: 보고서를 쓰는 데 소스가 필요 없다. 필요한 정보는 이미
Analyst/Verifier 가 구조화해 뽑아놨다. 여기에 소스를 다시 주면
① 토큰이 배치당 수만 개 낭비되고, ② Reporter 가 소스를 보고
**새로운(검증 안 된) 취약점을 지어낼 위험**이 생긴다. "필요한 정보만
정확히 주고, 나머지는 원천 차단한다"는 것도 스킬 설계의 일부다.

---

## 4. 토큰 절약 방안 — 설계와 도입 이유

### 4-1. 페이로드 크기 절감 (추정치)

아래 수치는 `bytes(코드) / 3.5` 로 근사한 "프롬프트에 넣을 코드 분량"
비교로, Sieve 단계가 코드 분량을 얼마나 줄이는지를 보여준다. 실제 API
청구 토큰(system prompt, 출력 토큰, Context Broker 조회분 포함)은
API 실행 시 `result.json.ledger` 에 별도로 기록된다.

| 배치 | 파일 통째로 넣을 때 (추정) | Sieve 통과 후 (추정) | 페이로드 절감률 |
|---|---:|---:|---:|
| batch1 `host_applications` | 413,043 tok | 46,253 tok | **88.80%** |
| batch2 `containers` | 408,078 tok | 22,214 tok | **94.56%** |
| batch3 `interface` | 702,781 tok | 26,970 tok | **96.16%** |
| **합계** | **1,523,902 tok** | **95,437 tok** | **93.74%** |

실제 API 토큰 사용량은 `sastagent/llm.py` 의 `TokenLedger` 가 자동으로
기록하도록 구현돼 있으며, API 실행 후에는 이 표를 실측치로 교체할 수
있다.

### 4-2. 도입한 9가지 기법

**① 결정론적 사전 필터 (가장 큰 효과)**
싱크가 하나도 없는 함수는 LLM 에 보내지 않는다. 3,687개 함수 중 싱크가
걸린 건 428개(11.6%)뿐이다.
> *도입 이유* — LLM 이 잘하는 건 "이 코드가 위험한가?"를 판단하는 것이지,
> "strcpy 가 어디 있나?"를 찾는 게 아니다. 찾는 일은 정규식이 0원에 한다.

**② 함수 단위 슬라이싱**
파일이 아니라 함수를 보낸다. 3,000줄짜리 파일도 문제되는 함수 하나만
90줄로 추려서 보낸다.
> *도입 이유* — C 취약점의 대부분은 한 함수 안에서 판정 가능하다.
> 파일 전체를 보내는 건 40배의 비용을 내고 40배의 노이즈를 사는 것이다.

**③ 긴 함수 축약(shrink)**
160줄 넘는 함수는 싱크 라인 기준 위아래 25줄 + 시그니처 8줄만 남기고
나머지는 `/* ... N lines omitted ... */` 로 접는다.
> *도입 이유* — 생략 구간을 명시적으로 표시해야 LLM 이 "경계 검사가
> 없다"고 잘못 단정하지 않는다. 안 그러면 잘려나간 부분에 있던 검사를
> 못 봐서 오탐을 만든다.

**④ 정규화 해시 중복 제거**
주석/공백을 제거한 뒤 SHA-1 을 떠서, 같은 코드가 여러 파일에 복제돼
있으면 한 번만 분석한다. batch1 에서 4건이 접혔다.
> *도입 이유* — 임베디드 코드베이스는 복붙이 많다. 같은 걸 두 번
> 분석할 이유가 없다. (단, 미세하게 다른 복제본은 해시가 갈려 각각
> 분석됐고 — 오히려 다행이었다. 실제로 두 판본 모두 개별 패치가
> 필요한 상태였다.)

**⑤ 2단계 모델 라우팅**
Analyst = Haiku 4.5(후보 전량 1차 분류), Verifier = Sonnet 4.6(고위험만
정밀 검증).
> *도입 이유* — 후보의 상당수는 "명백히 아님"이라 값싼 모델로 충분하다.
> 비싼 모델은 판단이 어려운 소수에만 쓴다.

**⑥ 프롬프트 캐싱**
공통 규칙집(system, 약 400토큰)에 `cache_control: ephemeral` 지정.
> *도입 이유* — 배치당 40회 호출이면 규칙집만 16,000토큰이 중복된다.
> 한 번만 내고 재사용하는 게 맞다.

**⑦ 디스크 캐시**
`(모델+system+user)` 해시로 캐시 파일 저장. 같은 코드를 다시 스캔하면
API 를 안 탄다.
> *도입 이유* — SAST 는 커밋마다 도는 도구다. 전체 재분석은 낭비다.

**⑧ 출력 토큰 상한 + JSON 강제**
"Return ONE JSON object. No markdown, no prose." 를 못 박고 `max_tokens`
로 물리적 상한(Analyst 700 / Verifier 900)을 건다.
> *도입 이유* — 출력 토큰이 입력보다 비싸다. JSON 강제는 비용 절감과
> 파싱 안정성을 동시에 얻는다.

**⑨ Reporter 에게 소스를 안 준다**
Reporter 는 구조화된 findings JSON 만 받는다.
> *도입 이유* — 보고서 작성에 소스가 필요 없다. 여기에 소스를 다시
> 넣으면 배치당 수만 토큰이 그냥 사라진다.

### 4-3. 절약과 정확도의 트레이드오프

| 기법 | 놓칠 수 있는 것 | 완화책 |
|---|---|---|
| 싱크 기반 필터 | 커스텀 래퍼 함수를 통한 취약점 | 규칙집에 사내 래퍼 추가 가능 |
| 함수 단위 슬라이싱 | 함수 간 데이터 흐름 취약점 | Context Broker 로 호출자 on-demand 조회 |
| shrink | 생략 구간의 경계 검사 | 생략을 명시 표기 → LLM 이 `needs_context` 선언 |
| 해시 dedup | 미세하게 다른 복제본 | 정규화 강도를 낮춰 의도적으로 보수적 |

이 도구는 **완전성(completeness)보다 정밀도(precision)** 를 택했다.
오탐 100건은 아무도 안 읽지만, 확정 8건은 오늘 고칠 수 있기 때문이다.

---

## 5. 작성 시 사용한 프롬프트

### 5-1. 런타임 프롬프트 (실제 API 호출에 사용)

**공통 시스템 규칙집** — 모든 호출의 `system` 블록, 프롬프트 캐싱 대상

```
You are a static application security testing (SAST) engine for C/C++ code in an
embedded Linux userland stack.

## Ground rules
1. You only see a SLICE of the program. Never assert a vulnerability you cannot
   point at with a concrete line number in the slice you were given.
2. If safety depends on a caller you cannot see, the verdict is `needs_context`,
   NOT `vulnerable`.
3. Do not invent identifiers. Every symbol you name must appear verbatim in the
   slice.
4. Prefer FEWER, HIGHER-CONFIDENCE findings.
5. Embedded context matters: fixed-size stack buffers fed by device/IPC data are
   real risks; a memcpy whose length is a compile-time sizeof is not.

## Output contract
Return ONE JSON object. No markdown, no prose, no explanation outside the JSON.
```
> 규칙 2 가 환각 억제의 핵심이다. "모른다"고 말할 명예로운 퇴로를 주지
> 않으면 LLM 은 빈칸을 지어내서 채운다.

**Analyst 프롬프트 핵심부**
```
Ask yourself, in order:
1. Where does the data COME FROM?
2. Is there a bound check between source and sink, INSIDE this slice?
3. Is the bound derived from the DESTINATION's size, or the SOURCE's data?
4. If you cannot answer (1), the verdict is needs_context.
```

**Verifier 프롬프트 핵심부**
```
Another agent claimed the finding below is a vulnerability. Your job is to TRY TO
DISPROVE it. You are rewarded for correctly rejecting false positives, not for
agreeing.

Checklist:
- Does sink_line actually contain the sink? If not → REJECT as hallucination.
- Is the bound derived from the destination's size?
- Is the input actually attacker-controlled, or a compile-time constant?
- Would a competent maintainer accept this as a bug report, or close it as noise?
```

**Reporter 프롬프트 핵심부**
```
Runs ONCE per batch, never sees raw source code — only structured findings.
Rules: do not add findings not in findings_json. If confirmed == 0, say so
plainly instead of padding.
```

### 5-2. 도구를 설계하려고 스스로에게 던진 메타 프롬프트

과제가 요구한 "작성 시 요청했던 프롬프트"에 해당하는, 실제 설계 과정에서
스스로에게 던진 질문들이다.

| 단계 | 스스로 던진 질문 | 결과로 이어진 설계 |
|---|---|---|
| 문제 정의 | *"청킹 전략을 고민하는 대신, '무엇을 넣지 않을 것인가'로 문제를 재정의하면?"* | Sieve(사전 필터)를 1급 시민으로 승격 → 토큰 93.7% 감소 |
| 역할 분리 | *"에이전트를 나누기 위해 나누는 함정을 피하려면, 서로 다른 인센티브를 줄 수 없나?"* | Analyst=찾는 인센티브 / Verifier=기각하는 인센티브 |
| 환각 억제 | *"환각은 정보가 부족한데 답을 내야 할 때 생긴다. '모른다'를 정당한 답으로 만들면?"* | `needs_context` verdict + 라인 대조 기각 규칙 |
| 배치 설계 | *"위협 모델이 같은 코드끼리 묶으면 배치 단위로 일관된 판단이 가능하지 않을까?"* | 입력 접점/미디어 파서/IPC 경계 3계층 분할 |
| 자기 검증 | *"내 도구가 찾았다는 취약점을, 실제 소스를 열어 라인 하나하나 대조하면 몇 건이 살아남나?"* | 모든 상수·매크로 정의를 직접 열어서 대조 (예: `CEC_MAX_XMIT_LENGTH`, `vcos_assert` 정의) |
| 최종 점검 | *"이 리포트를 메인테이너에게 보내면 몇 건이 invalid 로 닫힐까? 닫힐 것 같은 건 미리 빼자."* | 15건 중 4건 기각, 3건 하향 → 확정 8건만 최종 보고 |

---

## 6. 산출물 — 분석 결과

이 장의 판정 결과는 `out/llm_stage_results.json` 기준이며, 검증 방식은
8장에 정리했다.

### 6-1. 배치별 스캔 통계

277개 인덱싱 파일 중 276개가 3개 배치(host_applications/containers/
interface)에 포함됐다. 나머지 1개(`helpers/dtoverlay/dtoverlay.c`)는
현재 배치 정의의 include 경로 밖에 있어 이번 분석 범위에서 제외됐고,
배치 4(`helpers/`)를 추가하면 커버리지 100%가 된다.

| 배치 | 계층 | 파일 | 슬라이싱 함수 | 싱크 적중 | Sieve 통과 | 중복제거 | 저점수 폐기 | 페이로드 절감 |
|---|---|---|---|---|---|---|---|---|
| batch1 | host_applications | 75 | 764 | 122 | 80 | 4 | 38 | 88.8% |
| batch2 | containers | 69 | 825 | 179 | 100 | 0 | 79 | 94.6% |
| batch3 | interface | 132 | 2,098 | 127 | 45 | 0 | 82 | 96.2% |
| *(미포함)* | helpers/ | 1 | – | – | – | – | – | – |

### 6-2. 확정된 취약점 (8건)

| ID | 위치 | CWE | 심각도 | 핵심 근거 |
|---|---|---|---|---|
| B1-01 | `models.c:243` (hello_teapot) | CWE-787/121 | **치명적** | 폭 지정자 없는 `%s` 로 256바이트를 32바이트 필드에 복사, 경계검사가 쓰기 이후 실행 |
| B1-02 | `models.c:252` | CWE-134 | 높음 | `printf(s)` — 파일 내용이 그대로 포맷 문자열로 들어감 |
| B1-03 | `models.c:258` | CWE-787/1284 | 높음 | 정점 개수 상한 검사 없이 힙 영역 연속 침범 가능 |
| B1-04 | `models.c:236` | CWE-125 | 보통 | 빈 줄일 때 `strlen(s)-1` 언더플로 |
| B1-05 | `gl_scenes/models.c:249` | CWE-787/134 | **치명적** | 위 결함이 다른 파일에 그대로 복제 |
| B3-01 | `vcilcs.c:1048` | CWE-787/617 | 높음 | IPC 헤더/트레일러 길이가 목적지 크기와 비교 안 됨 |
| B3-02 | `vcilcs.c:1014` | CWE-191 | 높음 | 뺄셈 결과가 음수가 될 수 있는 부호있는 길이 계산 |
| B3-03 | `vcilcs.c:1058` | CWE-787 | 높음 | 경계 검사가 릴리스 빌드에서 사라지는 `vcos_assert` 에만 의존 |

### 6-3. 오탐 억제 사례 (기각 4건, 하향 3건)

Verifier 가 실제로 오탐을 걸러낸 대표 사례.

- **`vc_cec_send_message` 의 `sprintf` 루프** — `CEC_MAX_XMIT_LENGTH=15`
  상수를 추적하니 최대 50바이트로 `char s[96]` 에 안전하게 들어감 → **기각**
- **`qsynth_get_duration`** — 파일에서 읽은 길이를 malloc 에 쓰지만
  `len > (1<<20)` 상한이 단락 평가로 먼저 걸림 → **기각**
- **`do_autosusptest`** — `argv[2]` 접근 전 `argc != 4` 로 `exit(1)` → **기각**
- **`io_net_open_capture_file`, `load_library`, `simple_reader_open`** —
  현재는 계산이 정확히 들어맞아 안전하지만, 여유가 **0바이트**라 상수
  변경 시 즉시 취약해짐 → **하향**(기각이 아니라 계속 추적 대상으로 유지)

산출물 원본: `out/report.md`, `out/report.html`, `out/llm_stage_results.json`

---

## 7. 기존 도구와의 차별점

### 7-1. 한 장 비교

| | Cppcheck / Flawfinder | Coverity / CodeQL | ChatGPT 에 코드 붙여넣기 | **ai-sast-userland** |
|---|---|---|---|---|
| 탐지 방식 | 패턴 매칭 | 컴파일 + 데이터플로 | LLM 단독 판단 | 규칙 매칭 → LLM 판정 → LLM 반박 |
| 빌드 필요 | 불필요 | **필요** | 불필요 | 불필요 |
| 대용량 저장소 | 가능 | 가능 | **불가능**(컨텍스트 초과) | 가능 (93.7% 사전 축소) |
| 오탐 억제 | 약함 | 강함 | **매우 약함** | 적대적 Verifier 로 분리 |
| 환각 위험 | 없음 | 없음 | **높음** | 라인 대조 + `needs_context` |
| 판단 근거 설명 | 규칙 ID만 | 경로 추적 | 자연어(검증 불가) | 자연어 + 대조 가능한 라인 번호 |
| 커스텀 프레임워크 대응 | 규칙 추가 | 쿼리 작성(난이도 높음) | 가능 | `SINK_RULES` 한 줄 추가 |
| 비용 | 무료 | 라이선스 고가 | 사실상 불가 | 배치당 약 3만 토큰 |

### 7-2. 핵심 차별점 3가지

**① "찾는 것"과 "판단하는 것"을 분리했다**
Flawfinder 는 `strcpy` 를 전부 보고한다(userland 에 22곳, 대부분 안전).
LLM 에 코드를 그냥 던지면 컨텍스트 부족 상태에서 판단을 강요당해
없는 취약점을 지어낸다. 이 도구는 정규식이 428개 함수를 0원에 골라내고,
LLM 은 그중 판단이 필요한 것만 본다. `vc_cec_send_message` 는 Flawfinder
라면 무조건 보고했을 코드지만, 이 도구는 상수를 추적해 안전을 증명하고
기각했다.

**② LLM 이 LLM 을 반대신문한다**
일반적인 "AI SAST" 는 LLM 한 번 호출하고 끝나 그 출력이 검증되지 않는다.
이 도구의 Verifier 는 Analyst 의 주장을 반박하도록 설계돼 있고, 인용한
라인이 실제 코드와 다르면 환각으로 즉시 기각하는 기계적 대조 규칙이
걸려 있다. 판정도 3단(확정/하향/기각)이라 "지금은 안전하지만 여유가
0바이트"인 코드를 표현할 수 있다.

**③ 릴리스 빌드의 실체를 본다**
`vcilcs.c` 는 `vcos_assert` 를 경계 검사처럼 쓰지만, 실제 매크로 정의를
열어보면 릴리스 빌드에서 `(void)0` 이다. 패턴 매칭 도구는 이름만 보고
"검증됨"으로 처리하거나 아예 모른다. 이 도구는 Verifier 가 Context
Broker 로 매크로 정의를 직접 가져와서 이를 밝혀냈다. "이름이 assert 니까
검사겠지"를 의심하는 것, 이게 규칙 기반 도구가 못 하는 일이다.

### 7-3. 솔직한 열세

- **함수 간 데이터 흐름** — CodeQL 은 전역 호출 그래프로 taint 를
  추적하지만, 이 도구는 함수 내부가 기본이고 함수 밖은 필요할 때만
  일부 조회한다. 여러 함수를 거치는 취약점은 놓칠 수 있다.
- **재현성** — 규칙 기반 도구는 항상 같은 출력을 내지만 LLM 단계는
  그렇지 않다. 디스크 캐시로 같은 코드는 결과를 고정시켰지만 근본
  해결은 아니다.
- **컴파일 정보 부재** — 어떤 `#ifdef` 가 실제로 켜지는지 모른다.

그래서 이 도구의 현실적인 자리는 **Cppcheck 대체가 아니라 "1차 도구가
뱉은 노이즈를 사람 대신 읽어주는 2차 필터"** 다.

---

## 8. 한계와 향후 과제

### 8-1. 실행 방법론 노트

- **API 실행 여부** — 이번 산출물은 `ANTHROPIC_API_KEY` 가 없는 환경에서
  만들어, 파이프라인은 `--offline` 모드로 실행됐다(`out/result.json`
  의 `ledger.calls = 0`). 6장의 확정 8건은 Analyst/Verifier 프롬프트
  절차를 작성자가 동일하게 적용해 도출한 결과(`out/llm_stage_results.json`)
  다. API 키가 있는 환경에서 `--offline` 없이 `run.py` 를 실행하면
  같은 파이프라인이 API 로 자동 수행되어 동일 형식의 결과를 낸다.
- **토큰 절감 수치의 성격** — "93.7%"는 코드 바이트 길이 기반 추정치이며,
  API 실행 시 `ledger.input_tokens`/`output_tokens` 로 실측치를 별도
  확인할 수 있다.
- **프롬프트 전량 보존** — Analyst/Verifier 에 전달될 예정이었던 123건의
  프롬프트는 `out/pending_prompts.json` 에 전량 저장되어 있다.
- **배치 커버리지** — 인덱싱된 277개 파일 중 276개가 3개 배치에
  포함된다. `helpers/dtoverlay/dtoverlay.c` 1개는 현재 배치 정의의
  include 경로 밖에 있어 제외됐으며, `result.json.coverage` 에 기록된다.

### 8-2. 설계상 한계

- 데이터 흐름 분석이 함수 내부로 한정된다. 함수 간 흐름은 Verifier 가
  Context Broker 로 필요할 때만 부분 조회한다.
- 사내 커스텀 래퍼 함수(`safe_copy()` 같은)는 `config.SINK_RULES` 에
  직접 추가해야 인식된다.
- 완전성보다 정밀도를 택한 도구다. 오탐을 줄이는 대신 미탐이 존재할 수
  있다.

---

*원본 코드 및 세부 문서는 `ai-sast-userland` 저장소 참고
(`sastagent/`, `docs/`, `out/`).*
