# 프롬프트 전문 (Prompts)

두 종류를 나눠 싣는다.

- **A. 도구가 런타임에 사용하는 프롬프트** — 실제 API 호출에 들어가는 것
- **B. 이 도구를 설계하려고 내가 스스로에게 던진 프롬프트** — 메타 프롬프트

---

# A. 런타임 프롬프트

파일 위치: `sastagent/prompts/`

## A-0. 공통 시스템 규칙집 — `system_rulebook.md`

모든 LLM 호출의 `system` 블록에 들어가며, `cache_control: ephemeral` 로
캐싱된다. 여기 담긴 5개 규칙이 **환각 방지의 1차 방어선**이다.

```
You are a static application security testing (SAST) engine for C/C++ code in an
embedded Linux userland stack (Raspberry Pi VideoCore userland: media parsers,
IPC bridges, CLI camera apps).

## Ground rules (violating any of these makes your output useless)
1. You only see a SLICE of the program. You never see the whole call graph.
   Therefore you must NEVER assert a vulnerability you cannot point at with a
   concrete line number in the slice you were given.
2. If the safety of a construct depends on a caller you cannot see, the correct
   verdict is `needs_context`, NOT `vulnerable`. Say exactly what you would need.
3. Do not invent identifiers. Every symbol you name must appear verbatim in the
   slice. If you catch yourself writing a plausible-sounding function name that
   is not in the slice, stop and downgrade the finding.
4. Prefer FEWER, HIGHER-CONFIDENCE findings. A false positive costs a reviewer
   more than a missed low-severity issue costs the project.
5. Embedded context matters: fixed-size stack buffers fed by device/IPC data are
   real risks; a `memcpy` whose length is a compile-time `sizeof` is not.
...
## Output contract
Return ONE JSON object. No markdown, no prose, no explanation outside the JSON.
```

**설계 의도**
- 규칙 1·3 → "본 것만 말해라". 라인 번호를 못 대면 주장할 수 없게 만든다.
- 규칙 2 → **모른다고 말할 출구를 만들어준다.** 이게 없으면 LLM 은
  아무 말이나 지어내서 빈칸을 채운다. `needs_context` 라는 명예로운
  퇴로를 주는 게 환각을 줄이는 가장 효과적인 장치였다.
- 규칙 4 → SAST 도구가 실무에서 버려지는 1번 이유가 오탐 폭탄이라서.
- 규칙 5 → 임베디드 도메인 지식을 주입. 범용 프롬프트면 `memcpy` 를 전부
  의심해서 노이즈가 폭발한다.

## A-1. Analyst — `analyst.md`

전문은 `sastagent/prompts/analyst.md`. 핵심은 **강제된 사고 순서**다.

```
Ask yourself, in order:
1. Where does the data written/executed at the flagged line COME FROM?
   (literal / sizeof-bounded / caller argument / device or file read / env / argv)
2. Is there a bound check between that source and the sink, INSIDE this slice?
3. Is the bound derived from the DESTINATION's size, or from the SOURCE's data?
   (destination-derived = safe pattern, source-derived = suspicious)
4. If you cannot answer (1) from the slice alone, the verdict is `needs_context`.
```

**설계 의도** — 3번이 이 프롬프트의 핵심이다.
`strncpy(dst, src, len)` 이 안전한지 아닌지는 `len` 이 **목적지 크기에서
왔는지, 원본 데이터에서 왔는지**로 갈린다. 이 한 문장이
`RaspiStillYUV.c` 의 `malloc(len+10)` / `strncpy(..., len+1)` 을
정확히 안전으로 분류하게 만들었다.

출력은 고정 JSON 스키마:
```json
{"verdict","confidence","severity","cwe","sink_line",
 "source_of_data","why","missing_context","fix"}
```
`sink_line` 을 **절대 라인 번호**로 요구하는 게 중요하다.
이게 있어야 다음 단계에서 대조 검증이 가능하다.

## A-2. Verifier — `verifier.md`

전문은 `sastagent/prompts/verifier.md`. 핵심은 **역할을 적대적으로 설정**한 것.

```
Another agent claimed the finding below is a vulnerability. Your job is to TRY TO
DISPROVE it. You are rewarded for correctly rejecting false positives, not for
agreeing. Agree only if you cannot construct any reasonable objection.

Checklist you must run:
- Does `sink_line` actually contain the sink the claim describes? If the quoted
  line does not match the code, REJECT the claim as a hallucination.
- Is the destination buffer's size visible? ...
- Is the "attacker-controlled" path actually reachable, or is the input a
  compile-time constant / internal enum / already-validated struct field?
- Does any caller in extra_context establish the bound the primary slice lacks?
- Would a competent maintainer accept this as a bug report, or close it as noise?
```

**설계 의도**
- 체크리스트 1번이 **환각 탐지기**다. Analyst 가 존재하지 않는 라인을
  인용하면 바로 잡힌다. `hallucination_detected` 플래그로 따로 집계한다.
- 마지막 항목("메인테이너가 이걸 버그 리포트로 받아줄까?")은 판정 기준을
  추상적 위험도에서 **실무 수용성**으로 옮긴다. 이게 심각도 하향 판단에
  잘 작동했다.
- 결정을 `confirmed / downgraded / rejected` 3단으로 둔 이유:
  이분법이면 "지금은 안전하지만 여유가 0바이트"인 코드를 표현할 수 없다.
  실제로 `io_net.c`, `containers_filters.c`, `simple_reader.c` 3건이
  여기 해당한다.

## A-3. Reporter — `reporter.md`

```
ROLE: Reporter. Runs ONCE per batch, never sees raw source code — only the
structured findings that survived verification.

Rules: do not add findings that are not in findings_json. Do not restate line
numbers that are not present. If confirmed == 0, say so plainly instead of
padding.
```

**설계 의도** — "확정 0건이면 그냥 0건이라고 써라"가 중요하다.
LLM 은 빈 리포트를 싫어해서 뭔가를 채우려 든다. 미리 허락해줘야 한다.

---

# B. 이 도구를 만들기 위해 내가 스스로에게 던진 프롬프트

과제 요구사항에 있는 "작성 시 요청했던 prompt" 항목이다.
설계 과정에서 실제로 스스로에게 던진 질문들을 순서대로 남긴다.

## B-1. 문제 정의

> *"160,000줄짜리 C 저장소를 LLM 으로 스캔해야 한다. 컨텍스트 윈도우는
> 한참 모자라다. 이걸 '어떻게 잘라서 넣을까'의 문제로 보지 말고,
> **'무엇을 넣지 않을 것인가'의 문제**로 다시 정의하면 어떻게 되나?"*

→ 이 재정의가 전체 설계를 결정했다. 청킹 전략을 고민하는 대신
사전 필터(Sieve)를 1급 시민으로 승격시켰다. 결과적으로 토큰 93.7% 감소.

## B-2. 역할 분리 기준

> *"멀티 에이전트를 만들라고 했는데, 에이전트를 '나누기 위해 나누는' 함정을
> 피하려면 어떻게 해야 하나? 각 에이전트가 **다른 인센티브**를 갖게
> 만들 수는 없나?"*

→ Analyst 는 "찾는" 인센티브, Verifier 는 "기각하는" 인센티브를 갖게 했다.
같은 모델이 두 역할을 하면 자기 주장을 옹호하지만, 프롬프트로 목표를
반대로 걸면 실제로 반박한다. 이게 오탐 억제의 핵심이었다.

## B-3. 환각 억제

> *"LLM 이 존재하지 않는 취약점을 지어내는 건 언제인가? → 정보가 부족한데
> 답을 내야 할 때다. 그럼 **'모른다'를 정당한 답으로 만들면** 되지 않나?"*

→ `needs_context` verdict 도입. 그리고 그것만으로 부족하니
Verifier 에게 "인용한 라인이 실제 코드와 다르면 환각으로 기각"이라는
기계적 대조 규칙을 줬다.

## B-4. 배치 설계

> *"3개 배치를 파일 개수로 나누면 의미가 없다. **위협 모델이 같은 코드끼리**
> 묶으면 배치 단위로 일관된 판단을 내릴 수 있지 않을까?"*

→ 입력 접점 / 미디어 파서 / IPC 경계 3계층으로 분할.
실제로 batch3 의 확정 3건이 전부 "IPC 경계에서 온 길이 필드를 안 믿어야
한다"는 하나의 근본 원인으로 수렴했다.

## B-5. 자기 검증

> *"내가 만든 도구가 찾았다고 주장하는 취약점을, 내가 실제 소스를 열어서
> 라인 하나하나 대조하면 몇 건이 살아남나?"*

→ 이 질문 때문에 `vc_cec_send_message` 의 `sprintf` 를 의심했다가
`vc_cec.h:45` 의 `CEC_MAX_XMIT_LENGTH = 15` 를 확인하고 기각했다.
`vcos_assert` 가 릴리스 빌드에서 `(void)0` 이 된다는 것도
`vcos_assert.h:239` 를 직접 열어서 확인했다.
**리포트의 모든 상수와 라인 번호는 이 대조 과정을 거친 값이다.**

## B-6. 마지막 점검

> *"이 리포트를 userland 메인테이너에게 보내면, 몇 건이 'invalid' 로
> 닫힐까? 닫힐 것 같은 건 지금 빼자."*

→ 15건 중 4건을 기각, 3건을 하향해서 확정 8건만 남겼다.
