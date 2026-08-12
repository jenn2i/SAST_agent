# AI 기반 SAST 에이전트 — raspberrypi/userland 분석 리포트

> 대상: `github.com/raspberrypi/userland` (master) · 도구: `ai-sast-userland` (multi-agent SAST)

## 1. 한눈에 보기

- 인덱싱한 소스 파일: **277개** (5.2 MB)
- 파일을 통째로 LLM 에 넣었을 때 예상 토큰: **약 1,548,769 토큰**
- 실제 LLM 에 올린 프롬프트 토큰(3개 배치 합계): **약 95,437 토큰** → **93.7% 절감**
- 판정 결과: 확정 **8건** / 하향 **3건** / 기각 **4건**
- 심각도 분포: 치명적 2 · 높음 5 · 보통 1 · 낮음 3

가장 중요한 결과부터 말하면, `hello_pi/hello_teapot/models.c` 의 Wavefront `.obj` 로더에서 **경계 검사 없는 `sscanf("%s")` 와 포맷 스트링 취약점**이 확인됐고, 같은 결함이 `raspicam/gl_scenes/models.c` 에 복제되어 있다. 그리고 `interface/vmcs_host/vcilcs.c` 의 IPC 수신 경로는 **경계 검사를 `vcos_assert` 에 의존**하는데, 이 매크로는 릴리스 빌드에서 `(void)0` 으로 사라진다.

## 2. 배치별 스캔 통계

| 배치 | 계층 | 파일 | 슬라이싱된 함수 | 싱크 적중 | Sieve 통과 | 중복 제거 | 저점수 폐기 | 토큰 절감 |
|---|---|---|---|---|---|---|---|---|
| `batch1` | host_applications (사용자 입력 접점) | 75 | 764 | 122 | 80 | 4 | 38 | 88.8% |
| `batch2` | containers (미디어 파서) | 69 | 825 | 179 | 100 | 0 | 79 | 94.56% |
| `batch3` | interface (IPC/드라이버 브리지) | 132 | 2098 | 127 | 45 | 0 | 82 | 96.16% |

- **`batch1` 선정 이유**: argv/파일경로 등 외부 입력이 직접 들어오는 CLI 앱 계층
- **`batch2` 선정 이유**: 네트워크/파일에서 온 신뢰할 수 없는 미디어 데이터를 파싱하는 계층
- **`batch3` 선정 이유**: VCHIQ/IPC 로 프로세스 경계를 넘는 데이터가 오가는 계층

## 3. 배치별 상세 결과

### batch1 — host_applications (사용자 입력 접점)

후보 80건 중 6건을 정밀 판정했고, **5건이 확정**됐다. 1건은 오탐으로 기각, 0건은 심각도를 낮췄다.

| ID | 파일:라인 | 함수 | CWE | 판정 | 심각도 | 신뢰도 | 요약 |
|---|---|---|---|---|---|---|---|
| B1-01 | `models.c:243` | `load_wavefront_obj` | CWE-787 / CWE-121 | 확정 | 치명적 | 0.95 | L243 의 sscanf 는 폭 지정자 없는 %s 로 최대 256바이트 라인을 name[MAX_MATERIAL_NAME=32] |
| B1-05 | `models.c:249` | `load_wavefront_obj` | CWE-787 / CWE-134 | 확정 | 치명적 | 0.90 | B1-01~B1-04 와 동일한 결함이 라인 오프셋 +6 으로 그대로 복제되어 있다 (L249 sscanf, L258 prin |
| B1-02 | `models.c:252` | `load_wavefront_obj` | CWE-134 | 확정 | 높음 | 0.92 | L252 와 L302 의 printf(s) 는 파일 내용을 포맷 문자열 자리에 그대로 넣는다. |
| B1-03 | `models.c:258` | `load_wavefront_obj` | CWE-787 / CWE-1284 | 확정 | 높음 | 0.85 | L258 의 pv += 3 이 MAX_VERTICES 상한과 비교되지 않아, 정점 수가 많은 .obj 는 m->data 힙 영 |
| B1-04 | `models.c:236` | `load_wavefront_obj` | CWE-125 | 확정 | 보통 | 0.80 | L236 의 s[strlen(s)-1] 은 s 가 빈 문자열일 때 strlen(s)-1 이 size_t 언더플로를 일으켜 s[ |
| B1-06 | `RaspiStillYUV.c:331` | `parse_cmdline` | CWE-120 (제기됨) | 기각 | 해당없음 | 0.93 | L326 에서 argv 길이를 재고 L331 에서 strncpy 로 복사한다. 목적지 크기가 슬라이스만으로는 불확실하다. |

#### B1-01 · 치명적 · CWE-787 / CWE-121

**위치** `host_applications/linux/apps/hello_pi/hello_teapot/models.c:243` (`load_wavefront_obj`)

**근거** models.c:44-50 에서 MAX_MATERIALS=4, MAX_MATERIAL_NAME=32, name 은 char[32] 로 확정된다. L222 의 line 버퍼는 char[257] 이므로 32바이트 필드에 최대 255바이트를 쓸 수 있다. 경계 검사 L244 는 쓰기 이후에 실행되어 material[4] 접근도 허용된다.

**Verifier 의 반론** modelname 이 하드코딩된 내부 에셋이라면 공격자 제어가 아니라는 반론이 가능하다. 그러나 load_wavefront_obj 는 경로를 인자로 받는 범용 로더이며, .obj 는 본질적으로 외부에서 반입되는 에셋 포맷이다.

**조치** sscanf 폭 지정자를 %31s 로 고정하고, 경계 검사 if (m->num_materials < MAX_MATERIALS) 를 sscanf 호출 앞으로 옮긴다.

#### B1-05 · 치명적 · CWE-787 / CWE-134

**위치** `host_applications/linux/apps/raspicam/gl_scenes/models.c:249` (`load_wavefront_obj`)

**근거** hello_teapot 판본과 raspicam/gl_scenes 판본이 별도로 유지되고 있어, 한쪽만 고치면 다른 쪽이 남는다.

**Verifier 의 반론** Sieve 의 정규화 해시가 두 파일을 접지 못한 것은 주변 코드가 미세하게 달라서다. 즉 '중복'이 아니라 '분기된 복제본'이며, 각각 개별 수정이 필요하다.

**조치** 두 파일을 공통 모듈로 통합하거나, 최소한 동일 패치를 양쪽에 모두 적용한다.

#### B1-02 · 높음 · CWE-134

**위치** `host_applications/linux/apps/hello_pi/hello_teapot/models.c:252` (`load_wavefront_obj`)

**근거** s 는 L222 fread 로 채워진 파일 라인이며 어떤 살균도 거치지 않는다. %x/%s 로 스택 정보가 노출되고 %n 이 가용한 libc 에서는 임의 쓰기로 이어진다.

**Verifier 의 반론** 직후 vc_assert(0) 이 프로세스를 중단시키므로 영향이 제한된다는 반론이 가능하다. 그러나 printf 는 assert 보다 먼저 평가되며, %n 은 이미 그 시점에 쓰기를 수행한다.

**조치** printf("%s", s) 로 교체한다. 동일 패턴이 L302 에도 존재한다.

#### B1-03 · 높음 · CWE-787 / CWE-1284

**위치** `host_applications/linux/apps/hello_pi/hello_teapot/models.c:258` (`load_wavefront_obj`)

**근거** qv/qt/qn/qf 는 L210-213 에서 MAX_VERTICES 간격으로 배치된 단일 블록의 부분 구간이다. pv/pt/pn/pf 증가에 대한 상한 검사가 루프 어디에도 없으므로, 정점이 100000개를 넘으면 인접 구간(텍스처 좌표 영역)부터 침범하고 결국 할당 끝을 넘어간다.

**Verifier 의 반론** m->data 가 충분히 크게 잡혀 있을 수 있다는 반론. 그러나 L343-344 에서 할당 크기가 정확히 MAX_VERTICES(100000) 기준으로 산정되어 있어 상한은 유한하다.

**조치** 각 증가 지점에서 (pv - qv)/3 < MAX_VERTICES 등 상한을 검사하고 초과 시 파싱을 중단한다.

#### B1-04 · 보통 · CWE-125

**위치** `host_applications/linux/apps/hello_pi/hello_teapot/models.c:236` (`load_wavefront_obj`)

**근거** L236 은 switch(s[0]) 로 빈 줄을 걸러내는 L239 보다 먼저 실행된다. 따라서 빈 줄 방어가 순서상 무력하다.

**Verifier 의 반론** 빈 줄은 L232 의 *end++ = 0 처리로 생기지 않는다는 반론이 가능하나, 파일이 개행으로 시작하면 첫 바이트가 즉시 0 이 되어 s 는 빈 문자열이 된다.

**조치** size_t n = strlen(s); if (n && s[n-1] == '\n') s[n-1] = 0; 형태로 길이 0 을 먼저 확인한다.

**기각된 후보 (오탐)**

- `B1-06` RaspiStillYUV.c:331 — L329 의 malloc(len + 10) 이 L331 의 strncpy(..., len+1) 보다 항상 9바이트 크다. 복사 길이가 목적지 크기가 아니라 목적지 할당의 기준이 된 원본 길이에서 파생되므로 초과가 성립하지 않는다.

### batch2 — containers (미디어 파서)

후보 100건 중 4건을 정밀 판정했고, **0건이 확정**됐다. 1건은 오탐으로 기각, 3건은 심각도를 낮췄다.

| ID | 파일:라인 | 함수 | CWE | 판정 | 심각도 | 신뢰도 | 요약 |
|---|---|---|---|---|---|---|---|
| B2-01 | `io_net.c:138` | `io_net_open_capture_file` | CWE-193 | 하향 | 낮음 | 0.88 | L138 sprintf 의 유일한 방어가 L134 의 매직 넘버 -4 산술이다. |
| B2-02 | `containers_filters.c:180` | `load_library` | CWE-787 / CWE-676 | 하향 | 낮음 | 0.85 | L180 strncat(filter_, "_", 1) 의 3번째 인자가 원본 길이로 주어져, 목적지 잔여 공간을 제한하지 못한 |
| B2-03 | `simple_reader.c:522` | `simple_reader_open` | CWE-787 | 하향 | 낮음 | 0.82 | L516 과 L522 두 번의 strcpy 가 L511 의 단일 malloc 버퍼를 공유한다. |
| B2-04 | `qsynth_reader.c:272` | `qsynth_get_duration` | CWE-190 (제기됨) | 기각 | 해당없음 | 0.90 | 파일에서 읽은 32비트 길이가 malloc 크기 계산에 직접 들어간다. |

#### B2-01 · 낮음 · CWE-193

**위치** `containers/io/io_net.c:138` (`io_net_open_capture_file`)

**근거** 포맷은 %s %s %c 3개(총 6자)가 host+port+1자로 치환되므로 실제 기록량은 strlen(format)+strlen(host)+strlen(port)-5 이고 NUL 포함 -4 다. 검사가 이를 300 이하로 묶으므로 char[300] 에 정확히 들어맞는다. 다만 여유가 0바이트이고 -4 가 포맷 문자열과 암묵적으로 결합된 매직 넘버라, IO_NET_CAPTURE_*_FILE 정의가 바뀌면 검사가 조용히 깨진다.

**Verifier 의 반론** 실제로 계산해보면 오버플로가 성립하지 않는다.

**조치** sprintf 를 snprintf(filename, sizeof(filename), ...) 로 바꾸고 반환값을 확인한다. 그러면 -4 산술 자체가 불필요해진다.

#### B2-02 · 낮음 · CWE-787 / CWE-676

**위치** `containers/core/containers_filters.c:180` (`load_library`)

**근거** L176 snprintf(filter_, sizeof(filter_), "%4.4s", ...) 가 최대 4자+NUL 을 쓰므로 L180 의 strncat 은 인덱스 4 와 5 에 '_' 와 NUL 을 써서 char filter_[6] 에 정확히 들어맞는다. 그러나 strncat 의 n 을 '붙일 문자열의 길이'로 쓴 것은 API 오용이며, filter_ 크기나 포맷 폭이 바뀌면 즉시 1바이트 오버플로가 된다.

**Verifier 의 반론** 현재 코드에서는 넘치지 않는다.

**조치** strncat 대신 vcos_safe_strcpy/snprintf 를 쓰거나 n 을 sizeof(filter_) - strlen(filter_) - 1 로 계산한다.

#### B2-03 · 낮음 · CWE-787

**위치** `containers/simple/simple_reader.c:522` (`simple_reader_open`)

**근거** L511 할당량은 strlen(A)+strlen(B)+1 이다. L517 의 end 초기값 uri+strlen(A)+1 이 가리키는 직전 바이트는 NUL 이므로 구분자로 매칭될 수 없고, 따라서 end 오프셋 k <= strlen(A) 가 보장된다. L522 의 기록량은 k+strlen(B)+1 <= 할당량이다. 여유는 역시 0바이트다.

**Verifier 의 반론** 경계가 정확히 성립한다.

**조치** snprintf 로 재작성하거나, 최소한 end 오프셋이 strlen(A) 이하임을 명시적으로 assert 한다.

**기각된 후보 (오탐)**

- `B2-04` qsynth_reader.c:272 — L263 에 len > (1<<20) 상한 검사가 malloc 보다 먼저 단락 평가로 실행되어 정수 오버플로 여지가 없다. L271-272 의 기록량 8+len 도 할당량 sizeof(QSYNTH_SEGMENT_T)+8+len 이내다.

### batch3 — interface (IPC/드라이버 브리지)

후보 45건 중 5건을 정밀 판정했고, **3건이 확정**됐다. 2건은 오탐으로 기각, 0건은 심각도를 낮췄다.

| ID | 파일:라인 | 함수 | CWE | 판정 | 심각도 | 신뢰도 | 요약 |
|---|---|---|---|---|---|---|---|
| B3-01 | `vcilcs.c:1048` | `ilcs_receive_buffer` | CWE-787 / CWE-617 | 확정 | 높음 | 0.87 | L1048 과 L1050 의 memcpy 길이가 IPC 메시지 필드에서 오는데, 목적지 크기 exe->bufferLen 과 비 |
| B3-02 | `vcilcs.c:1014` | `ilcs_receive_buffer` | CWE-191 | 확정 | 높음 | 0.83 | L1014 의 뺄셈 결과 bulk_len 이 음수가 될 수 있고, 그대로 bulk receive 길이로 전달된다. |
| B3-03 | `vcilcs.c:1058` | `ilcs_receive_buffer` | CWE-787 | 확정 | 높음 | 0.85 | L1058 memcpy 의 유일한 방어가 L1056 의 vcos_assert 다. |
| B3-04 | `vc_vchi_cecservice.c:749` | `vc_cec_send_message` | CWE-787 (제기됨) | 기각 | 해당없음 | 0.94 | L747, L749 의 sprintf 가 char s[96] 에 루프로 누적 기록한다. |
| B3-05 | `mmal_vc_diag.c:726` | `do_autosusptest` | CWE-125 (제기됨) | 기각 | 해당없음 | 0.95 | L726, L727 이 argv[2], argv[3] 에 접근한다. argc 검사 위치를 확인해야 한다. |

#### B3-01 · 높음 · CWE-787 / CWE-617

**위치** `interface/vmcs_host/vcilcs.c:1048` (`ilcs_receive_buffer`)

**근거** interface/vcos/vcos_assert.h:239 에서 VCOS_ASSERT_ENABLED 가 0 일 때 vcos_assert(cond) 는 (void)0 으로 정의된다. 즉 릴리스 빌드에서 이 검사들은 코드에서 사라진다. 게다가 L1016 의 assert 는 clen 만 보고 headerlen/trailerlen 값 자체는 보지 않는다. L1046 의 end = dest + exe->bufferLen 기준으로 trailerlen > bufferLen 이면 L1050 이 버퍼 앞쪽으로 기록한다.

**Verifier 의 반론** L1016 에 vcos_assert 가 있으니 검증된 것 아니냐는 반론. 그러나 이는 성립하지 않는다.

**조치** if (fixup->headerlen + fixup->trailerlen > exe->bufferLen) return NULL; 을 vcos_assert 가 아닌 실제 런타임 검사로 추가한다.

#### B3-02 · 높음 · CWE-191

**위치** `interface/vmcs_host/vcilcs.c:1014` (`ilcs_receive_buffer`)

**근거** int32_t bulk_len = exe->bufferLen - fixup->headerlen - fixup->trailerlen 에 하한 검사가 없다. 음수 bulk_len 은 L1026/L1028 의 vchiq_queue_bulk_receive* 로 전달되며, 수신측이 부호 없는 크기로 해석하면 대규모 DMA 기록이 된다.

**Verifier 의 반론** VideoCore 펌웨어가 신뢰 경계 안쪽이라면 공격자 제어가 아니라는 반론이 가능하다. 타당한 지적이므로 critical 이 아닌 high 로 유지한다.

**조치** 뺄셈 전에 headerlen + trailerlen <= bufferLen 을 확인하고, bulk_len <= 0 이면 조기 반환한다.

#### B3-03 · 높음 · CWE-787

**위치** `interface/vmcs_host/vcilcs.c:1058` (`ilcs_receive_buffer`)

**근거** L1056 vcos_assert(clen == sizeof(IL_PASS_BUFFER_EXECUTE_T) + exe->bufferLen) 이 릴리스 빌드에서 제거되면, 실제 메시지 길이 clen 보다 큰 bufferLen 을 주장하는 메시지가 인접 힙을 읽어 dest 로 복사한다.

**Verifier 의 반론** B3-01 과 같은 근본 원인(assert 로 경계 검사)이므로 별건이 아니라 묶어야 한다는 반론이 가능하다. 다만 코드 경로(IL_BUFFER_INLINE)가 달라 개별 패치가 필요해 분리 유지한다.

**조치** assert 를 if 문으로 승격하고, 불일치 시 VC_CONTAINER 오류 반환 경로로 빠지게 한다.

**기각된 후보 (오탐)**

- `B3-04` vc_vchi_cecservice.c:749 — interface/vmcs_host/vc_cec.h:45 에서 CEC_MAX_XMIT_LENGTH = 15 다. L747 이 4바이트, L749 루프가 최대 15회 x 3바이트 = 45바이트, NUL 1바이트로 총 50바이트이며 char s[96] 에 충분히 들어간다. 추가로 L732 에서 length <= CEC_MAX_XMIT_LENGTH 를 vcos_verify 로 먼저 거른다.
- `B3-05` mmal_vc_diag.c:726 — L719 의 if (argc != 4) 블록이 L722 exit(1) 로 종료하므로, L726 도달 시 argv[2], argv[3] 은 항상 유효하다.

## 4. 오탐 억제가 실제로 작동했는가

Sieve 단계는 의도적으로 '넓게' 잡는다. 판정은 Verifier 가 한다. 정밀 판정한 15건 중 4건이 기각되고 3건이 하향됐다. 특히 다음 세 건은 사람이 보면 위험해 보이지만 실제로는 안전한 코드였다.

- `vc_cec_send_message` 의 `sprintf` 루프 — 상수 `CEC_MAX_XMIT_LENGTH=15` 를 추적하니 최대 50바이트로 `char s[96]` 에 여유 있게 들어간다.
- `qsynth_get_duration` — 파일에서 읽은 길이를 `malloc` 에 쓰지만 `len > (1<<20)` 상한이 단락 평가로 먼저 걸린다.
- `do_autosusptest` — `argv[2]` 접근 전에 `argc != 4` 로 `exit(1)` 한다.

반대로 '하향' 3건은 지금은 안전하지만 **여유가 0바이트**인 코드다. 상수 하나만 바뀌면 즉시 취약해지므로 기각이 아니라 하향으로 남겼다.

## 5. 실행 정보

```
$ python3 run.py --repo ../userland-master --offline
repo files=277  elapsed=2.27s
```

Scout/Sieve 단계는 LLM 없이 **2.27초**만에 277개 파일을 처리했다. LLM 호출은 이후 단계에서만 발생한다.

> **재현 방법**: `ANTHROPIC_API_KEY` 를 설정하고 `--offline` 없이 실행하면 Analyst(Haiku) → Verifier(Sonnet) 단계까지 자동 수행된다. `--offline` 실행 시에는 `out/pending_prompts.json` 에 '실제로 전송했을 프롬프트'가 그대로 덤프된다.
