"""코드 분할기(Slicer).

파일을 통째로 LLM 에 넣으면 토큰이 폭발한다. 그래서 '함수 단위'로 자른다.
tree-sitter 같은 외부 파서 없이 동작하도록, 주석/문자열 상태 머신 + 괄호
균형 계산을 직접 구현했다. C 의 다양한 코딩 스타일(중괄호가 다음 줄,
인자 목록이 여러 줄)을 모두 처리한다.
"""

import re
from dataclasses import dataclass

CALLABLE = re.compile(r"([A-Za-z_][A-Za-z0-9_]*)\s*\(")

KEYWORDS = {
    "if", "for", "while", "switch", "do", "else", "return", "sizeof", "defined",
    "catch", "case", "typedef", "struct", "union", "enum", "static_assert",
    "assert", "__attribute__", "and", "or", "not",
}

QUALIFIERS = re.compile(
    r"^\s*(static|extern|inline|const|unsigned|signed|struct|union|enum|"
    r"VCHPRE_|__attribute__|virtual|explicit|template)\b")


@dataclass
class Chunk:
    path: str
    func: str
    start: int      # 1-based, inclusive
    end: int
    code: str

    @property
    def loc(self) -> int:
        return self.end - self.start + 1


def _clean_line(line: str, in_block: bool):
    """주석·문자열 내부를 지운 라인. 괄호 계산이 오염되지 않도록 한다."""
    out, i, n = [], 0, len(line)
    while i < n:
        c = line[i]
        nxt = line[i + 1] if i + 1 < n else ""
        if in_block:
            if c == "*" and nxt == "/":
                in_block = False
                i += 2
                continue
            i += 1
            continue
        if c == "/" and nxt == "*":
            in_block = True
            i += 2
            continue
        if c == "/" and nxt == "/":
            break
        if c in "\"'":
            q = c
            i += 1
            while i < n:
                if line[i] == "\\":
                    i += 2
                    continue
                if line[i] == q:
                    i += 1
                    break
                i += 1
            out.append(" ")
            continue
        out.append(c)
        i += 1
    return "".join(out), in_block


def _clean(text: str):
    lines, in_block = [], False
    for ln in text.splitlines():
        c, in_block = _clean_line(ln, in_block)
        lines.append("" if c.lstrip().startswith("#") else c)
    return lines


def _match_paren(clean, li, ci):
    depth = 0
    for l in range(li, min(li + 25, len(clean))):
        row = clean[l]
        start = ci if l == li else 0
        for c in range(start, len(row)):
            if row[c] == "(":
                depth += 1
            elif row[c] == ")":
                depth -= 1
                if depth == 0:
                    return l, c
    return None, None


def _next_significant(clean, l, c):
    for li in range(l, min(l + 6, len(clean))):
        row = clean[li]
        start = c + 1 if li == l else 0
        for ci in range(start, len(row)):
            ch = row[ci]
            if ch.isspace():
                continue
            return ch, li, ci
    return None, None, None


def slice_functions(path: str, text: str) -> list:
    raw = text.splitlines()
    clean = _clean(text)
    n = len(clean)
    chunks, i = [], 0

    while i < n:
        row = clean[i]
        if not row.strip():
            i += 1
            continue
        matched = False
        for m in CALLABLE.finditer(row):
            name = m.group(1)
            if name in KEYWORDS:
                continue
            pre = row[:m.start()].rstrip()
            if pre.endswith((".", "->", "=", ",", "&&", "||", "!", "+", "-")):
                continue
            open_col = m.end() - 1
            el, ec = _match_paren(clean, i, open_col)
            if el is None:
                continue
            ch, bl, bc = _next_significant(clean, el, ec)
            if ch != "{":
                continue        # ';' 이면 prototype, 그 외는 단순 호출식
            depth, j, started = 0, bl, False
            while j < n:
                depth += clean[j].count("{") - clean[j].count("}")
                if "{" in clean[j]:
                    started = True
                if started and depth <= 0:
                    break
                j += 1
            if j >= n:
                break
            head = i
            if head > 0:
                prev = clean[head - 1].strip()
                if prev and not prev.endswith((";", "{", "}", ",", ")")) \
                        and (QUALIFIERS.match(prev)
                             or re.fullmatch(r"[A-Za-z_][\w \*]*", prev)):
                    head -= 1
            chunks.append(Chunk(path, name, head + 1, j + 1,
                                "\n".join(raw[head:j + 1])))
            i = j + 1
            matched = True
            break
        if not matched:
            i += 1
    return chunks


def shrink(chunk: Chunk, hit_lines, max_lines: int, pad: int) -> Chunk:
    """함수가 너무 길면 싱크 주변만 남긴다. 생략 구간은 명시적으로 표기."""
    if chunk.loc <= max_lines:
        return chunk
    body = chunk.code.splitlines()
    rel = sorted({h - chunk.start for h in hit_lines
                  if 0 <= h - chunk.start < len(body)})
    keep = set(range(0, min(8, len(body))))
    for r in rel:
        keep.update(range(max(0, r - pad), min(len(body), r + pad + 1)))
    kept, prev = [], -2
    for idx in sorted(keep):
        if idx != prev + 1 and prev >= 0:
            kept.append(f"/* ... {idx - prev - 1} lines omitted ... */")
        kept.append(f"{chunk.start + idx}: {body[idx]}")
        prev = idx
    return Chunk(chunk.path, chunk.func, chunk.start, chunk.end, "\n".join(kept))
