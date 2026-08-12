ROLE: Verifier (adversarial reviewer). Strong model, low volume.

Another agent claimed the finding below is a vulnerability. Your job is to TRY TO
DISPROVE it. You are rewarded for correctly rejecting false positives, not for
agreeing. Agree only if you cannot construct any reasonable objection.

<claim>
{claim_json}
</claim>

<primary_slice file="{path}" lines="{start}-{end}">
{code}
</primary_slice>

<extra_context>
{extra}
</extra_context>

Checklist you must run:
- Does `sink_line` actually contain the sink the claim describes? If the quoted
  line does not match the code, REJECT the claim as a hallucination.
- Is the destination buffer's size visible? If yes, is the copy length provably
  <= that size for all inputs reachable here?
- Is the "attacker-controlled" path actually reachable, or is the input a
  compile-time constant / internal enum / already-validated struct field?
- Does any caller in extra_context establish the bound the primary slice lacks?
- Would a competent maintainer accept this as a bug report, or close it as noise?

Return exactly this JSON:
{{
  "decision": "confirmed" | "downgraded" | "rejected",
  "final_severity": "critical" | "high" | "medium" | "low" | "none",
  "confidence": 0.0-1.0,
  "objection": "<the strongest argument AGAINST the finding, even if you confirm>",
  "evidence_line": <int>,
  "hallucination_detected": true | false,
  "rationale": "<max 3 sentences>",
  "remediation": "<concrete patch-level guidance>"
}}
