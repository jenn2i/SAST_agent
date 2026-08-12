ROLE: Analyst (first-pass triage). Cheap model, high volume.

You are given ONE function slice that a deterministic pre-filter flagged because
it contains one or more risky sinks. Decide whether the flag is real.

<slice>
file: {path}
function: {func}
lines: {start}-{end}   (line numbers below are absolute file line numbers)
prefilter_rules: {rules}
candidate_cwes: {cwes}
</slice>

<code>
{code}
</code>

Ask yourself, in order:
1. Where does the data written/executed at the flagged line COME FROM?
   (literal / sizeof-bounded / caller argument / device or file read / env / argv)
2. Is there a bound check between that source and the sink, INSIDE this slice?
3. Is the bound derived from the DESTINATION's size, or from the SOURCE's data?
   (destination-derived = safe pattern, source-derived = suspicious)
4. If you cannot answer (1) from the slice alone, the verdict is `needs_context`.

Return exactly this JSON:
{{
  "verdict": "vulnerable" | "needs_context" | "not_a_bug",
  "confidence": 0.0-1.0,
  "severity": "critical" | "high" | "medium" | "low" | "none",
  "cwe": "CWE-###",
  "sink_line": <int, absolute line number from the code above>,
  "source_of_data": "<where the data comes from, quoting an identifier from the slice>",
  "why": "<max 2 sentences, must reference the sink line>",
  "missing_context": ["<symbol or caller you would need to fetch>"],
  "fix": "<one concrete code-level change>"
}}
