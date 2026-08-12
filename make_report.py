#!/usr/bin/env python3
"""Reporter 단계: 파이프라인 통계 + 판정 결과 -> report.md / report.html

이 스크립트는 소스코드를 다시 읽지 않는다. 구조화된 JSON 만으로 리포트를 만든다.
(리포팅 단계에 원본 코드를 넣지 않는 것 자체가 토큰 절약 설계다.)
"""

import html
import json
import os

OUT = "out"
res = json.load(open(f"{OUT}/result.json"))
llm = json.load(open(f"{OUT}/llm_stage_results.json"))

SEV_ORDER = {"critical": 0, "high": 1, "medium": 2, "low": 3, "none": 4}
SEV_KR = {"critical": "치명적", "high": "높음", "medium": "보통", "low": "낮음", "none": "해당없음"}
DEC_KR = {"confirmed": "확정", "downgraded": "하향", "rejected": "기각"}


def rows(bid):
    out = []
    for f in llm.get(bid, []):
        v, a = f["verifier"], f["analyst"]
        out.append(dict(
            id=f["id"], path=f["path"], line=f["sink_line"], func=f["func"],
            cwe=f["cwe"], decision=v["decision"], sev=v["final_severity"],
            asev=a["severity"], conf=v["confidence"],
            why=a["why"], objection=v["objection"], rationale=v["rationale"],
            fix=v["remediation"]))
    out.sort(key=lambda r: (SEV_ORDER[r["sev"]], r["id"]))
    return out


def totals():
    t = dict(confirmed=0, downgraded=0, rejected=0, critical=0, high=0,
             medium=0, low=0)
    for bid in llm:
        if bid.startswith("_"):
            continue
        for r in rows(bid):
            t[r["decision"]] += 1
            if r["sev"] in t:
                t[r["sev"]] += 1
    return t


# ---------------------------------------------------------------- markdown
def md():
    L = []
    A = L.append
    rs = res["repo_summary"]
    T = totals()
    A("# AI 기반 SAST 에이전트 — raspberrypi/userland 분석 리포트\n")
    A("> 대상: `github.com/raspberrypi/userland` (master) · "
      "도구: `ai-sast-userland` (multi-agent SAST)\n")

    A("## 1. 한눈에 보기\n")
    A(f"- 인덱싱한 소스 파일: **{rs['file_count']}개** "
      f"({rs['total_bytes']/1024/1024:.1f} MB)")
    A(f"- 파일을 통째로 LLM 에 넣었을 때 예상 토큰: **약 {rs['est_tokens_if_naive']:,} 토큰**")
    tot_naive = sum(b["token_math"]["naive_whole_files_tokens"] for b in res["batches"].values())
    tot_sieve = sum(b["token_math"]["sieved_prompt_tokens"] for b in res["batches"].values())
    A(f"- 실제 LLM 에 올린 프롬프트 토큰(3개 배치 합계): **약 {tot_sieve:,} 토큰** "
      f"→ **{100*(1-tot_sieve/tot_naive):.1f}% 절감**")
    A(f"- 판정 결과: 확정 **{T['confirmed']}건** / 하향 **{T['downgraded']}건** / "
      f"기각 **{T['rejected']}건**")
    A(f"- 심각도 분포: 치명적 {T['critical']} · 높음 {T['high']} · "
      f"보통 {T['medium']} · 낮음 {T['low']}\n")

    A("가장 중요한 결과부터 말하면, `hello_pi/hello_teapot/models.c` 의 Wavefront "
      "`.obj` 로더에서 **경계 검사 없는 `sscanf(\"%s\")` 와 포맷 스트링 취약점**이 확인됐고, "
      "같은 결함이 `raspicam/gl_scenes/models.c` 에 복제되어 있다. 그리고 "
      "`interface/vmcs_host/vcilcs.c` 의 IPC 수신 경로는 **경계 검사를 `vcos_assert` 에 "
      "의존**하는데, 이 매크로는 릴리스 빌드에서 `(void)0` 으로 사라진다.\n")

    A("## 2. 배치별 스캔 통계\n")
    A("| 배치 | 계층 | 파일 | 슬라이싱된 함수 | 싱크 적중 | Sieve 통과 | 중복 제거 | 저점수 폐기 | 토큰 절감 |")
    A("|---|---|---|---|---|---|---|---|---|")
    for bid, b in res["batches"].items():
        s, t = b["stats"], b["token_math"]
        A(f"| `{bid}` | {b['meta']['name']} | {s['files']} | {s['functions']} | "
          f"{s['functions_with_sink']} | {s['candidates']} | {s['deduped']} | "
          f"{s['dropped_low_score']} | {t['reduction_pct']}% |")
    A("")
    for bid, b in res["batches"].items():
        A(f"- **`{bid}` 선정 이유**: {b['meta']['why']}")
    A("")

    A("## 3. 배치별 상세 결과\n")
    for bid, b in res["batches"].items():
        rr = rows(bid)
        A(f"### {bid} — {b['meta']['name']}\n")
        conf = [r for r in rr if r["decision"] == "confirmed"]
        A(f"후보 {b['stats']['candidates']}건 중 {len(rr)}건을 정밀 판정했고, "
          f"**{len(conf)}건이 확정**됐다. "
          f"{len([r for r in rr if r['decision']=='rejected'])}건은 오탐으로 기각, "
          f"{len([r for r in rr if r['decision']=='downgraded'])}건은 심각도를 낮췄다.\n")
        A("| ID | 파일:라인 | 함수 | CWE | 판정 | 심각도 | 신뢰도 | 요약 |")
        A("|---|---|---|---|---|---|---|---|")
        for r in rr:
            A(f"| {r['id']} | `{os.path.basename(r['path'])}:{r['line']}` | "
              f"`{r['func']}` | {r['cwe']} | {DEC_KR[r['decision']]} | "
              f"{SEV_KR[r['sev']]} | {r['conf']:.2f} | {r['why'][:70]} |")
        A("")
        for r in rr:
            if r["decision"] == "rejected":
                continue
            A(f"#### {r['id']} · {SEV_KR[r['sev']]} · {r['cwe']}\n")
            A(f"**위치** `{r['path']}:{r['line']}` (`{r['func']}`)\n")
            A(f"**근거** {r['rationale']}\n")
            A(f"**Verifier 의 반론** {r['objection']}\n")
            A(f"**조치** {r['fix']}\n")
        rej = [r for r in rr if r["decision"] == "rejected"]
        if rej:
            A("**기각된 후보 (오탐)**\n")
            for r in rej:
                A(f"- `{r['id']}` {os.path.basename(r['path'])}:{r['line']} — {r['rationale']}")
            A("")

    A("## 4. 오탐 억제가 실제로 작동했는가\n")
    A("Sieve 단계는 의도적으로 '넓게' 잡는다. 판정은 Verifier 가 한다. "
      f"정밀 판정한 {sum(len(rows(b)) for b in llm if not b.startswith('_'))}건 중 "
      f"{totals()['rejected']}건이 기각되고 {totals()['downgraded']}건이 하향됐다. "
      "특히 다음 세 건은 사람이 보면 위험해 보이지만 실제로는 안전한 코드였다.\n")
    A("- `vc_cec_send_message` 의 `sprintf` 루프 — 상수 `CEC_MAX_XMIT_LENGTH=15` 를 "
      "추적하니 최대 50바이트로 `char s[96]` 에 여유 있게 들어간다.")
    A("- `qsynth_get_duration` — 파일에서 읽은 길이를 `malloc` 에 쓰지만 "
      "`len > (1<<20)` 상한이 단락 평가로 먼저 걸린다.")
    A("- `do_autosusptest` — `argv[2]` 접근 전에 `argc != 4` 로 `exit(1)` 한다.\n")
    A("반대로 '하향' 3건은 지금은 안전하지만 **여유가 0바이트**인 코드다. "
      "상수 하나만 바뀌면 즉시 취약해지므로 기각이 아니라 하향으로 남겼다.\n")

    A("## 5. 실행 정보\n")
    A("```")
    A("$ python3 run.py --repo ../userland-master --offline")
    A(f"repo files={rs['file_count']}  elapsed={res['elapsed_sec']}s")
    A("```")
    A(f"\nScout/Sieve 단계는 LLM 없이 **{res['elapsed_sec']}초**만에 "
      f"{rs['file_count']}개 파일을 처리했다. LLM 호출은 이후 단계에서만 발생한다.\n")
    A("> **재현 방법**: `ANTHROPIC_API_KEY` 를 설정하고 `--offline` 없이 실행하면 "
      "Analyst(Haiku) → Verifier(Sonnet) 단계까지 자동 수행된다. "
      "`--offline` 실행 시에는 `out/pending_prompts.json` 에 "
      "'실제로 전송했을 프롬프트'가 그대로 덤프된다.\n")
    return "\n".join(L)


# ---------------------------------------------------------------- html
def to_html(markdown_text):
    body = []
    in_table = in_pre = False
    for line in markdown_text.split("\n"):
        if line.startswith("```"):
            body.append("</pre>" if in_pre else "<pre>")
            in_pre = not in_pre
            continue
        if in_pre:
            body.append(html.escape(line))
            continue
        s = line.rstrip()
        if s.startswith("|"):
            cells = [c.strip() for c in s.strip("|").split("|")]
            if set("".join(cells)) <= set("-: "):
                continue
            if not in_table:
                body.append("<table><tbody>")
                in_table = True
                tag = "th"
            else:
                tag = "td"
            body.append("<tr>" + "".join(
                f"<{tag}>{inline(c)}</{tag}>" for c in cells) + "</tr>")
            continue
        if in_table:
            body.append("</tbody></table>")
            in_table = False
        if s.startswith("#### "):
            body.append(f"<h4>{inline(s[5:])}</h4>")
        elif s.startswith("### "):
            body.append(f"<h3>{inline(s[4:])}</h3>")
        elif s.startswith("## "):
            body.append(f"<h2>{inline(s[3:])}</h2>")
        elif s.startswith("# "):
            body.append(f"<h1>{inline(s[2:])}</h1>")
        elif s.startswith("> "):
            body.append(f"<blockquote>{inline(s[2:])}</blockquote>")
        elif s.startswith("- "):
            body.append(f"<li>{inline(s[2:])}</li>")
        elif s:
            body.append(f"<p>{inline(s)}</p>")
    if in_table:
        body.append("</tbody></table>")
    return TPL.replace("{{BODY}}", "\n".join(body))


def inline(t):
    t = html.escape(t)
    out, i = [], 0
    while i < len(t):
        if t.startswith("**", i):
            j = t.find("**", i + 2)
            if j > 0:
                out.append(f"<strong>{t[i+2:j]}</strong>")
                i = j + 2
                continue
        if t[i] == "`":
            j = t.find("`", i + 1)
            if j > 0:
                out.append(f"<code>{t[i+1:j]}</code>")
                i = j + 1
                continue
        out.append(t[i])
        i += 1
    return "".join(out)


TPL = """<!doctype html><html lang="ko"><meta charset="utf-8">
<title>AI SAST — userland 분석 리포트</title>
<style>
:root{--ink:#16181d;--mut:#5c6370;--line:#e3e6ea;--acc:#b4451f;--bg:#fbfaf8}
*{box-sizing:border-box}
body{margin:0;padding:48px 24px 96px;background:var(--bg);color:var(--ink);
 font:16px/1.75 -apple-system,"Segoe UI","Noto Sans KR",sans-serif}
main{max-width:920px;margin:0 auto}
h1{font-size:30px;line-height:1.3;margin:0 0 8px;letter-spacing:-.02em}
h2{font-size:21px;margin:56px 0 14px;padding-bottom:8px;border-bottom:2px solid var(--ink)}
h3{font-size:17px;margin:36px 0 10px;color:var(--acc)}
h4{font-size:15px;margin:26px 0 6px;padding-left:10px;border-left:3px solid var(--acc)}
p{margin:10px 0}
li{margin:5px 0}
code{background:#eceff3;padding:1px 5px;border-radius:3px;font-size:.87em;
 font-family:ui-monospace,Menlo,monospace}
pre{background:#22252b;color:#e6e6e6;padding:14px 16px;border-radius:6px;
 overflow-x:auto;font-size:13px;line-height:1.6}
pre code{background:none;color:inherit;padding:0}
blockquote{margin:14px 0;padding:10px 16px;background:#fff;border-left:3px solid var(--mut);
 color:var(--mut);font-size:.94em}
table{width:100%;border-collapse:collapse;margin:14px 0;font-size:13px;background:#fff}
th,td{border:1px solid var(--line);padding:7px 9px;text-align:left;vertical-align:top}
th{background:#f0f2f5;font-weight:600;white-space:nowrap}
strong{font-weight:650}
</style><main>{{BODY}}</main></html>"""


text = md()
open(f"{OUT}/report.md", "w", encoding="utf-8").write(text)
open(f"{OUT}/report.html", "w", encoding="utf-8").write(to_html(text))
print("wrote out/report.md, out/report.html")
print(json.dumps(totals(), ensure_ascii=False))
