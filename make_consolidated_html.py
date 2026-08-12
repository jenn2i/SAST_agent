import html, re

src = "out/consolidated_report.md"
dst = "out/consolidated_report.html"
text = open(src, encoding="utf-8").read()

def inline(t):
    t = html.escape(t)
    # bold
    t = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", t)
    # code
    t = re.sub(r"`([^`]+)`", r"<code>\1</code>", t)
    # links [text](#anchor) or [text](url)
    t = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r'<a href="\2">\1</a>', t)
    return t

def slugify(s):
    s = re.sub(r"[^\w가-힣\s-]", "", s).strip().lower()
    s = re.sub(r"[\s]+", "-", s)
    return s

lines = text.split("\n")
body = []
in_table = in_pre = False
for raw in lines:
    line = raw.rstrip("\n")
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
        body.append("<tr>" + "".join(f"<{tag}>{inline(c)}</{tag}>" for c in cells) + "</tr>")
        continue
    if in_table:
        body.append("</tbody></table>")
        in_table = False
    if s.startswith("#### "):
        t = s[5:]; body.append(f'<h4 id="{slugify(t)}">{inline(t)}</h4>')
    elif s.startswith("### "):
        t = s[4:]; body.append(f'<h3 id="{slugify(t)}">{inline(t)}</h3>')
    elif s.startswith("## "):
        t = s[3:]; body.append(f'<h2 id="{slugify(t)}">{inline(t)}</h2>')
    elif s.startswith("# "):
        t = s[2:]; body.append(f'<h1 id="{slugify(t)}">{inline(t)}</h1>')
    elif s.startswith("> "):
        body.append(f"<blockquote>{inline(s[2:])}</blockquote>")
    elif re.match(r"^\d+\.\s", s):
        body.append(f"<li class='num'>{inline(re.sub(r'^\d+\.\s','',s))}</li>")
    elif s.startswith("- "):
        body.append(f"<li>{inline(s[2:])}</li>")
    elif s == "---":
        body.append("<hr>")
    elif s:
        body.append(f"<p>{inline(s)}</p>")

TPL = """<!doctype html><html lang="ko"><meta charset="utf-8">
<title>AI SAST 통합 리포트 — userland</title>
<style>
:root{--ink:#16181d;--mut:#5c6370;--line:#e3e6ea;--acc:#b4451f;--bg:#fbfaf8}
*{box-sizing:border-box}
body{margin:0;padding:0;background:var(--bg);color:var(--ink);
 font:16px/1.75 -apple-system,"Segoe UI","Noto Sans KR",sans-serif}
.wrap{max-width:960px;margin:0 auto;padding:48px 24px 96px}
h1{font-size:30px;line-height:1.3;margin:0 0 8px;letter-spacing:-.02em}
h2{font-size:22px;margin:56px 0 14px;padding-bottom:8px;border-bottom:2px solid var(--ink)}
h3{font-size:18px;margin:36px 0 10px;color:var(--acc)}
h4{font-size:15px;margin:26px 0 6px;padding-left:10px;border-left:3px solid var(--acc)}
p{margin:10px 0}
li{margin:5px 0;margin-left:20px}
li.num{list-style:decimal;margin-left:24px}
code{background:#eceff3;padding:1px 5px;border-radius:3px;font-size:.87em;
 font-family:ui-monospace,Menlo,monospace}
pre{background:#22252b;color:#e6e6e6;padding:14px 16px;border-radius:6px;
 overflow-x:auto;font-size:13px;line-height:1.6;white-space:pre}
pre code{background:none;color:inherit;padding:0}
blockquote{margin:14px 0;padding:10px 16px;background:#fff;border-left:3px solid var(--mut);
 color:var(--mut);font-size:.94em}
table{width:100%;border-collapse:collapse;margin:14px 0;font-size:13px;background:#fff}
th,td{border:1px solid var(--line);padding:7px 9px;text-align:left;vertical-align:top}
th{background:#f0f2f5;font-weight:600;white-space:nowrap}
strong{font-weight:650}
hr{border:none;border-top:1px solid var(--line);margin:36px 0}
a{color:var(--acc);text-decoration:none}
a:hover{text-decoration:underline}
</style><div class="wrap">{{BODY}}</div></html>"""

open(dst, "w", encoding="utf-8").write(TPL.replace("{{BODY}}", "\n".join(body)))
print("wrote", dst)
