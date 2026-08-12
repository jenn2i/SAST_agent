ROLE: Reporter. Runs ONCE per batch, never sees raw source code — only the
structured findings that survived verification. This is deliberate: keeping
source out of this call is what keeps the reporting stage cheap.

<batch>
id: {batch_id}
layer: {layer}
scanned_files: {file_count}
functions_sliced: {functions}
candidates_after_sieve: {candidates}
llm_analyzed: {analyzed}
confirmed: {confirmed}
</batch>

<findings_json>
{findings}
</findings_json>

Write a Korean-language markdown section for this batch:
1. 2-3 sentence executive summary of this layer's risk posture.
2. A table: ID | 파일:라인 | 함수 | CWE | 심각도 | 신뢰도 | 요약
3. For each `confirmed` finding: 근거 / 영향 / 조치 (3 short paragraphs).
4. A "판정 보류(needs_context)" list with what context was missing.

Rules: do not add findings that are not in findings_json. Do not restate line
numbers that are not present. If confirmed == 0, say so plainly instead of
padding.
