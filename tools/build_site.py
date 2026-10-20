"""Generate the static Greengold website.

The site in ``website/`` is plain HTML. This script writes every page from one
layout, renders ``docs/SPEC.md`` into ``spec.html``, and builds the benchmark
page from ``website/benchmarks/data.json``. Run it from anywhere:

    python tools/build_site.py

The output is checked in; the host does not run a build.
"""

from __future__ import annotations

import html
import json
import re
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SITE = ROOT / "website"
SPEC = ROOT / "docs" / "SPEC.md"
VERSION = "0.23.0"
DOMAIN = "https://greengoldlang.com"
UPDATED = "2026-10-13"

# --------------------------------------------------------------------------
# Icons (24x24 stroke icons)
# --------------------------------------------------------------------------

def icon(body: str, extra: str = "") -> str:
    return (f'<svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="2" '
            f'stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"{extra}>{body}</svg>')


ICONS = {
    "arrow": icon('<path d="M5 12h14M13 6l6 6-6 6"/>'),
    "chev": icon('<path d="M9 6l6 6-6 6"/>'),
    "copy": icon('<rect x="9" y="9" width="11" height="11" rx="2"/><path d="M5 15V5a2 2 0 0 1 2-2h10"/>'),
    "book": icon('<path d="M4 4.5A2.5 2.5 0 0 1 6.5 2H20v17H6.5A2.5 2.5 0 0 0 4 21.5z"/><path d="M4 21.5A2.5 2.5 0 0 1 6.5 19H20v3H6.5"/>'),
    "chart": icon('<path d="M3 3v18h18"/><path d="M7 15l4-4 3 3 6-7"/>'),
    "key": icon('<circle cx="7.5" cy="15.5" r="4.5"/><path d="M10.7 12.3L21 2M16 7l3 3M14 9l2 2"/>'),
    "lock": icon('<rect x="4" y="11" width="16" height="10" rx="2"/><path d="M8 11V7a4 4 0 0 1 8 0v4"/>'),
    "alert": icon('<path d="M12 9v4M12 17h.01"/><path d="M10.3 3.9L1.8 18a2 2 0 0 0 1.7 3h17a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0z"/>'),
    "wrench": icon('<path d="M9 11l3 3L22 4"/><path d="M21 12v7a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11"/>'),
    "cpu": icon('<rect x="5" y="5" width="14" height="14" rx="2"/><rect x="9" y="9" width="6" height="6"/><path d="M9 2v3M15 2v3M9 19v3M15 19v3M2 9h3M2 15h3M19 9h3M19 15h3"/>'),
    "layers": icon('<path d="M12 2l10 6-10 6L2 8z"/><path d="M2 16l10 6 10-6"/>'),
    "check": icon('<path d="M20 6L9 17l-5-5"/>'),
    "flask": icon('<path d="M9 3h6M10 3v6L4.5 19a2 2 0 0 0 1.8 3h11.4a2 2 0 0 0 1.8-3L14 9V3"/><path d="M7 15h10"/>'),
    "pin": icon('<path d="M12 22s7-6.2 7-12a7 7 0 0 0-14 0c0 5.8 7 12 7 12z"/><circle cx="12" cy="10" r="2.5"/>'),
    "info": icon('<circle cx="12" cy="12" r="10"/><path d="M12 16v-4M12 8h.01"/>'),
    "mail": icon('<rect x="2" y="4" width="20" height="16" rx="2"/><path d="M22 6l-10 7L2 6"/>'),
    "github": icon('<path d="M9 19c-5 1.5-5-2.5-7-3m14 6v-3.9a3.4 3.4 0 0 0-.9-2.6c3.1-.4 6.4-1.5 6.4-7A5.4 5.4 0 0 0 20 4.8 5 5 0 0 0 19.9 1S18.7.6 16 2.5a13.4 13.4 0 0 0-7 0C6.3.6 5.1 1 5.1 1A5 5 0 0 0 5 4.8a5.4 5.4 0 0 0-1.5 3.7c0 5.5 3.3 6.6 6.4 7A3.4 3.4 0 0 0 9 18.1V22"/>'),
    "heart": icon('<path d="M20.8 4.6a5.5 5.5 0 0 0-7.8 0L12 5.7l-1-1.1a5.5 5.5 0 0 0-7.8 7.8l1 1.1L12 21.2l7.8-7.7 1-1.1a5.5 5.5 0 0 0 0-7.8z"/>'),
    "linkedin": icon('<path d="M16 8a6 6 0 0 1 6 6v7h-4v-7a2 2 0 0 0-4 0v7h-4v-7a6 6 0 0 1 6-6z"/><rect x="2" y="9" width="4" height="12"/><circle cx="4" cy="4" r="2"/>'),
    "sun": icon('<circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4"/>', ' class="sun"'),
    "moon": icon('<path d="M21 12.8A9 9 0 1 1 11.2 3a7 7 0 0 0 9.8 9.8z"/>', ' class="moon"'),
    "menu": icon('<path d="M4 6h16M4 12h16M4 18h16"/>'),
    "code": icon('<path d="M16 18l6-6-6-6M8 6l-6 6 6 6"/>'),
    "file": icon('<path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><path d="M14 2v6h6"/>'),
    "bolt": icon('<path d="M13 2L3 14h9l-1 8 10-12h-9z"/>'),
    "pause": icon('<rect x="6" y="4" width="4" height="16" rx="1"/><rect x="14" y="4" width="4" height="16" rx="1"/>'),
}

# --------------------------------------------------------------------------
# Syntax highlighting
# --------------------------------------------------------------------------

GG_KEYWORDS = {
    "fn", "struct", "impl", "enum", "feature", "match", "if", "elif", "else", "then",
    "return", "fixed", "const", "for", "in", "while", "break", "continue", "pass",
    "defer", "and", "or", "not", "test", "require", "import", "type", "comptime",
    "hot", "extern", "unsafe", "trust", "soa", "copy", "lend", "consume", "read",
    "exclusive", "let", "step", "as", "tied", "to", "private", "public", "overflow",
    "wrapping", "ref", "mut", "self", "var",
}
GG_CONSTANTS = {"true", "false", "null"}
GG_TYPES = {
    "i8", "i16", "i32", "i64", "isize", "u8", "u16", "u32", "u64", "usize",
    "f32", "f64", "bool", "str", "string", "int", "uint", "float", "double", "void",
}

TOKEN_RE = re.compile(r"""
    (?P<comment>\#.*$)
  | (?P<str>[f$]?"(?:\\.|[^"\\])*"?)
  | (?P<chr>'(?:\\.|[^'\\])*')
  | (?P<num>\b(?:0x[0-9a-fA-F_]+|0b[01_]+|\d[\d_]*(?:\.\d[\d_]*)?(?:[eE][+-]?\d+)?)\b)
  | (?P<word>[A-Za-z_][A-Za-z0-9_]*)
  | (?P<op>=>|->|\.\.=|\.\.|[+\-*/%]=|==|!=|<=|>=|=)
""", re.X)


def esc(text: str) -> str:
    return html.escape(text, quote=False)


DECLARED_RE = re.compile(r"\b(?:struct|enum|feature|union|type|impl)\s+([A-Za-z_]\w*)")


def highlight_line(line: str, declared: frozenset = frozenset()) -> str:
    out = []
    pos = 0
    for m in TOKEN_RE.finditer(line):
        out.append(esc(line[pos:m.start()]))
        kind = m.lastgroup
        text = m.group()
        cls = ""
        if kind == "comment":
            cls = "tok-comment"
        elif kind in ("str", "chr"):
            cls = "tok-str"
        elif kind == "num":
            cls = "tok-num"
        elif kind == "op":
            cls = "tok-op"
        elif kind == "word":
            rest = line[m.end():]
            if text in GG_KEYWORDS:
                cls = "tok-kw"
            elif text in GG_CONSTANTS:
                cls = "tok-num"
            elif text in GG_TYPES or text in declared or (text[0].isupper() and (len(text) == 1 or any(c.islower() for c in text))):
                cls = "tok-type"
            elif rest.startswith("(") or (rest.startswith("[") and re.match(r"\[[A-Za-z0-9_, \[\]]*\]\(", rest)):
                cls = "tok-fn"
        out.append(f'<span class="{cls}">{esc(text)}</span>' if cls else esc(text))
        pos = m.end()
    out.append(esc(line[pos:]))
    return "".join(out)


def highlight(source: str) -> str:
    declared = frozenset(DECLARED_RE.findall(source))  # a type declared in lowercase is still a type
    return "\n".join(highlight_line(line, declared) for line in source.strip("\n").split("\n"))


C_KEYWORDS = {
    # C++ and Rust, enough to make the benchmark sources readable.
    "auto", "bool", "break", "case", "char", "const", "constexpr", "continue", "default",
    "do", "double", "else", "enum", "false", "float", "for", "if", "include", "inline",
    "int", "long", "namespace", "new", "delete", "nullptr", "return", "short", "signed",
    "sizeof", "static", "struct", "switch", "template", "true", "typedef", "typename",
    "unsigned", "using", "void", "while", "class", "public", "private", "std",
    "as", "crate", "dyn", "extern", "fn", "impl", "in", "let", "loop", "match", "mod",
    "move", "mut", "pub", "ref", "self", "Self", "super", "trait", "type", "unsafe",
    "use", "where",
}


def highlight_c(source: str) -> str:
    out_lines = []
    for line in source.rstrip("\n").split("\n"):
        out = []
        pos = 0
        for m in re.finditer(r'(?P<comment>//.*$)|(?P<str>"(?:\\.|[^"\\])*")|(?P<pre>^\s*#\s*\w+)|'
                             r"(?P<num>\b\d[\d_]*(?:\.\d+)?(?:[a-z]\w*)?\b)|(?P<word>[A-Za-z_]\w*)", line):
            out.append(esc(line[pos:m.start()]))
            kind = m.lastgroup
            text = m.group()
            cls = {"comment": "tok-comment", "str": "tok-str", "pre": "tok-kw", "num": "tok-num"}.get(kind, "")
            if kind == "word":
                if text in C_KEYWORDS:
                    cls = "tok-kw"
                elif re.fullmatch(r"(?:[iu](?:8|16|32|64|128|size)|f32|f64|usize|String|Vec|Box|Option)", text) or text[0].isupper():
                    cls = "tok-type"
                elif line[m.end():].startswith("("):
                    cls = "tok-fn"
            out.append(f'<span class="{cls}">{esc(text)}</span>' if cls else esc(text))
            pos = m.end()
        out.append(esc(line[pos:]))
        out_lines.append("".join(out))
    return "\n".join(out_lines)


def highlight_json(source: str) -> str:
    def repl(m: re.Match) -> str:
        if m.group("key"):
            return f'<span class="tok-key">{esc(m.group("key"))}</span>:'
        if m.group("str"):
            return f'<span class="tok-str">{esc(m.group("str"))}</span>'
        if m.group("lit"):
            return f'<span class="tok-kw">{m.group("lit")}</span>'
        if m.group("num"):
            return f'<span class="tok-num">{m.group("num")}</span>'
        return esc(m.group())
    pattern = re.compile(r'(?P<key>"(?:\\.|[^"\\])*")\s*:|(?P<str>"(?:\\.|[^"\\])*")|(?P<lit>\btrue\b|\bfalse\b|\bnull\b)|(?P<num>-?\d+(?:\.\d+)?)|[^"\w-]+|.')
    return pattern.sub(repl, source.rstrip("\n"))


def highlight_terminal(source: str) -> str:
    lines = []
    for raw in source.rstrip("\n").split("\n"):
        line = esc(raw)
        if raw.startswith("Error:"):
            line = f'<span class="t-err">error:</span>{esc(raw[6:])}'
        elif raw.strip().startswith("--&gt;") or raw.strip().startswith("-->"):
            m = re.match(r"(\s*)--> (\S+)(\s+)(GG\d+)(.*)", raw)
            if m:
                line = (f'{m.group(1)}<span class="t-gutter">--&gt;</span> <span class="t-loc">{esc(m.group(2))}</span>'
                        f'{m.group(3)}<span class="t-label">{m.group(4)}</span><span class="t-dim">{esc(m.group(5))}</span>')
        elif raw.strip().startswith("= help"):
            line = re.sub(r"= help:", '<span class="t-help">= help:</span>', line)
        elif "fix (verified)" in raw:
            line = line.replace("= fix (verified):", '<span class="t-ok">= fix (verified):</span>')
        elif "fix (manual)" in raw:
            line = line.replace("= fix (manual):", '<span class="t-dim">= fix (manual):</span>')
        elif re.match(r"\s*\d*\s*\|", raw):
            m = re.match(r"(\s*\d*\s*\|)(.*)", raw)
            gutter, rest = m.group(1), m.group(2)
            if rest.strip().startswith("^"):
                cm = re.match(r"(\s*)(\^+)(.*)", rest)
                rest_html = f'{cm.group(1)}<span class="t-caret">{cm.group(2)}</span><span class="t-label">{esc(cm.group(3))}</span>'
            else:
                rest_html = highlight_line(rest)
            line = f'<span class="t-gutter">{esc(gutter)}</span>{rest_html}'
        elif re.match(r"\d+ errors? found", raw):
            line = f'<span class="t-err">{esc(raw)}</span>'
        lines.append(line)
    return "\n".join(lines)


# --------------------------------------------------------------------------
# Building blocks
# --------------------------------------------------------------------------

def copy_button() -> str:
    return f'<button type="button" class="copy" aria-label="Copy code">{ICONS["copy"]}<span class="label">Copy</span></button>'


def code_window(source: str, file: str = "", lang: str = "gg", extra_class: str = "", note: str = "",
                pre_html: str | None = None) -> str:
    if pre_html is None:
        pre_html = {"gg": highlight, "c": highlight_c, "json": highlight_json, "term": highlight_terminal}[lang](source)
    head = (f'<figcaption class="code-head">'
            f'<span class="code-file">{esc(file)}</span>{copy_button()}</figcaption>')
    note_html = f'<p class="code-note">{note}</p>' if note else ""
    cls = f"code {extra_class}".strip()
    return f'<figure class="{cls}">{head}<pre><code>{pre_html}</code></pre>{note_html}</figure>'


def tabbed_code(items: list[dict], extra_class: str = "") -> str:
    tabs = []
    panels = []
    for i, item in enumerate(items):
        sel = "true" if i == 0 else "false"
        tabs.append(f'<button type="button" class="code-tab" role="tab" id="tab-{item["id"]}" aria-controls="panel-{item["id"]}" '
                    f'aria-selected="{sel}" tabindex="{0 if i == 0 else -1}" data-file="{esc(item["file"])}">{esc(item["label"])}</button>')
        hidden = "" if i == 0 else " hidden"
        note = f'<p class="code-note">{item["note"]}</p>' if item.get("note") else ""
        panels.append(f'<div class="code-panel" role="tabpanel" id="panel-{item["id"]}" aria-labelledby="tab-{item["id"]}"{hidden}>'
                      f'<pre><code>{item.get("html") or highlight(item["code"])}</code></pre>{note}</div>')
    head = (f'<figcaption class="code-head">'
            f'<span class="code-file">{esc(items[0]["file"])}</span>{copy_button()}</figcaption>')
    return (f'<figure class="code {extra_class}" data-tabs>{head}'
            f'<div class="code-tabs" role="tablist" aria-label="Examples">{"".join(tabs)}</div>{"".join(panels)}</figure>')


NAV = [
    ("why", "why.html", "Why"),
    ("spec", "spec.html", "Spec"),
    ("benchmarks", "benchmarks.html", "Benchmarks"),
    ("playground", "playground.html", "Playground"),
    ("learn", "learn/index.html", "Learn"),
    ("diagnostics", "diagnostics.html", "Diagnostics"),
    ("roadmap", "roadmap.html", "Roadmap"),
    ("about", "about.html", "About"),
]

THEME_BOOT = ("<script>(function(){try{var t=localStorage.getItem('gg-theme');"
              "if(t==='light'||t==='dark')document.documentElement.setAttribute('data-theme',t);}catch(e){}})();</script>")


def asset_version() -> str:
    """Short content hash so a deploy never pairs new HTML with a cached old style.css or app.js."""
    import hashlib
    h = hashlib.sha256()
    for name in ("style.css", "app.js"):
        h.update((SITE / name).read_bytes())
    return h.hexdigest()[:10]


def layout(key: str, path: str, title: str, description: str, body: str, root: str = "", extra_head: str = "") -> str:
    """`root` is the path from this page back to the site root ("../" for a page in a folder); it is put in front of every
    relative link and script of the shared header and footer. `body` and `extra_head` are written relative to the root."""
    full_title = "Greengold — Systems speed, readable ownership" if key == "home" else f"{title} — Greengold"
    url = f"{DOMAIN}/" if key == "home" else f"{DOMAIN}/{path}"
    current = ' aria-current="page"'
    nav = "\n".join(
        f'        <a href="{href}"{current if k == key else ""}>{label}</a>' for k, href, label in NAV)
    page = f"""<!DOCTYPE html>
<html lang="en" class="no-js">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>{esc(full_title)}</title>
  <meta name="description" content="{html.escape(description)}">
  <meta name="theme-color" content="#090d0b">
  <link rel="canonical" href="{url}">
  <meta property="og:title" content="{esc(full_title)}">
  <meta property="og:description" content="{html.escape(description)}">
  <meta property="og:type" content="website">
  <meta property="og:url" content="{url}">
  <meta property="og:image" content="{DOMAIN}/assets/greengold_logo.png">
  <meta name="twitter:card" content="summary">
  <link rel="icon" type="image/png" href="assets/greengold_logo.png">
  <link rel="apple-touch-icon" href="assets/greengold_logo.png">
  {THEME_BOOT}
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link href="https://fonts.googleapis.com/css2?family=Bricolage+Grotesque:opsz,wght@12..96,600;12..96,700;12..96,800&family=Inter:wght@400;500;600&family=JetBrains+Mono:wght@400;500;600;700&display=swap" rel="stylesheet">
  <link rel="stylesheet" href="style.css?v={asset_version()}">
{extra_head}</head>
<body>
  <a class="skip" href="#main">Skip to content</a>
  <header class="site-header">
    <div class="wrap header-inner">
      <a href="index.html" class="brand" aria-label="Greengold home">
        <img src="assets/greengold_logo.png" alt="" width="30" height="30">
        <span>Greengold</span>
        <span class="brand-version">v{VERSION}</span>
      </a>
      <nav id="site-nav" class="site-nav" aria-label="Main">
{nav}
      </nav>
      <div class="header-tools">
        <a class="icon-btn" href="https://github.com/Greengold-Lang/greengold-lang" rel="noopener" aria-label="Greengold on GitHub" title="Greengold on GitHub">{ICONS["github"]}</a>
        <a class="icon-btn" href="https://www.patreon.com/greengoldlang" rel="noopener" aria-label="Support Greengold on Patreon" title="Support on Patreon">{ICONS["heart"]}</a>
        <button type="button" class="icon-btn theme-toggle" aria-label="Switch colour theme">{ICONS["sun"]}{ICONS["moon"]}</button>
        <button type="button" class="icon-btn menu-toggle" aria-expanded="false" aria-controls="site-nav" aria-label="Menu">{ICONS["menu"]}</button>
      </div>
    </div>
  </header>

  <main id="main">
{body}
  </main>

  <footer class="site-footer">
    <div class="wrap">
      <div class="footer-grid">
        <div class="footer-brand">
          <a href="index.html" class="brand"><img src="assets/greengold_logo.png" alt="" width="30" height="30"><span>Greengold</span></a>
          <p>A statically typed systems language. Native code through LLVM, ownership in three words.</p>
        </div>
        <div class="footer-col">
          <h4>Language</h4>
          <ul>
            <li><a href="why.html">Why Greengold</a></li>
            <li><a href="spec.html">Specification</a></li>
            <li><a href="spec.md">spec.md</a></li>
          </ul>
        </div>
        <div class="footer-col">
          <h4>Evidence</h4>
          <ul>
            <li><a href="benchmarks.html">Benchmarks</a></li>
            <li><a href="benchmarks/data.json">Benchmark data</a></li>
            <li><a href="diagnostics.html">Diagnostics</a></li>
          </ul>
        </div>
        <div class="footer-col">
          <h4>Project</h4>
          <ul>
            <li><a href="https://github.com/Greengold-Lang/greengold-lang">GitHub</a></li>
            <li><a href="https://github.com/Greengold-Lang/greengold-lang/releases/latest">Download</a></li>
            <li><a href="https://www.patreon.com/greengoldlang" rel="noopener">Support on Patreon</a></li>
            <li><a href="https://github.com/Greengold-Lang/greengold-lang#install">Install</a></li>
            <li><a href="roadmap.html">Roadmap</a></li>
            <li><a href="about.html">About</a></li>
            <li><a href="llms.txt">llms.txt</a></li>
          </ul>
        </div>
      </div>
      <div class="footer-bottom">
        <span>© 2026 Umut Faruk Dilli. Greengold is released under the MIT License.</span>
        <span>Version {VERSION}</span>
      </div>
    </div>
  </footer>
  <script src="app.js?v={asset_version()}"></script>
</body>
</html>
"""
    if root:
        page = re.sub(r'((?:href|src)=")(?!https?:|#|mailto:|data:)', lambda m: m.group(1) + root, page)
    return page


def page_hero(kicker: str, title: str, lede: str, extra: str = "", narrow: bool = False) -> str:
    wrap = "wrap narrow" if narrow else "wrap"
    return f"""    <section class="page-hero">
      <div class="{wrap}">
        {"" if kicker == title else f'<span class="kicker">{kicker}</span>'}
        <h1>{title}</h1>
        <p class="lede">{lede}</p>
        {extra}
      </div>
    </section>"""


# --------------------------------------------------------------------------
# Benchmark data
# --------------------------------------------------------------------------

LANGS = [
    ("C++ (GCC -O3)", "cpp", "C++", "g++ -O3"),
    ("Rust (opt-level=3)", "rust", "Rust", "rustc opt-level=3"),
    ("Greengold (Release)", "gg", "Greengold", "gg build --release"),
]

WORKLOADS = json.loads((ROOT / "tools" / "site_workloads.json").read_text(encoding="utf-8"))


def load_bench() -> list[dict]:
    data = json.loads((SITE / "benchmarks" / "data.json").read_text(encoding="utf-8"))["results"]
    rows = []
    for wid, title, desc in WORKLOADS:
        if wid not in data:  # a workload added after the last measured run
            continue
        res = data[wid]
        higher_better = wid == "primes"
        metric = {k: (res[k]["passes"] if higher_better else res[k]["median_ms"]) for k, *_ in LANGS}
        gg = metric["Greengold (Release)"]
        def judge(best):
            gap = (best - gg) / best if higher_better else (gg - best) / best
            return gap, ("faster" if gap < 0 else "within" if gap <= 0.05 else "slower")

        others = [metric["C++ (GCC -O3)"], metric["Rust (opt-level=3)"]]
        best = max(others) if higher_better else min(others)
        gap, verdict = judge(best)
        vs = {k: dict(zip(("gap", "verdict"), judge(metric[key])))
              for k, key in (("cpp", "C++ (GCC -O3)"), ("rust", "Rust (opt-level=3)"))}
        rows.append(dict(id=wid, title=title, desc=desc, res=res, metric=metric, higher=higher_better,
                         gap=gap, verdict=verdict, best=best, vs=vs))
    return rows


def fmt_ms(v: float) -> str:
    if v >= 1000:
        return f"{v / 1000:.2f} s"
    return f"{v:.1f} ms" if v >= 100 else f"{v:.2f} ms"


def verdict_badge(row: dict) -> str:
    out = []
    for key, name in (("cpp", "C++"), ("rust", "Rust")):
        v = row["vs"][key]
        pct = abs(v["gap"]) * 100
        if v["verdict"] == "faster":
            text = f'{pct:.1f}% more passes' if row["higher"] else (f'{pct:.0f}% faster' if pct >= 10 else f'{pct:.1f}% faster')
        elif v["verdict"] == "within":
            text = f'within {max(pct, 0.1):.1f}%'
        else:
            text = f'{pct:.1f}% slower'
        out.append(f'<span class="badge {v["verdict"]}"><span class="vs">vs {name}</span> {text}</span>')
    return f'<span class="badges">{"".join(out)}</span>'


def bars(row: dict) -> str:
    values = row["metric"]
    top = max(values.values())
    parts = []
    for key, cls, name, _ in LANGS:
        v = values[key]
        width = max(v / top * 100, 1.5)
        label = f"{v:,.0f}" if row["higher"] else fmt_ms(v)
        parts.append(f'<div class="bar {cls}"><span>{name}</span><span class="bar-track">'
                     f'<span class="bar-fill" style="--w:{width:.1f}%"></span></span><span class="bar-val">{label}</span></div>')
    return f'<div class="bars">{"".join(parts)}</div>'


def brow(row: dict, link: str) -> str:
    unit = "passes, higher is better" if row["higher"] else "median"
    return (f'<div class="brow"><div class="brow-head"><a href="{link}#{row["id"]}">{esc(row["title"])} '
            f'<span class="t-dim" style="font-weight:400;color:var(--muted);font-size:.82rem">· {unit}</span></a>'
            f'{verdict_badge(row)}</div>{bars(row)}</div>')


# --------------------------------------------------------------------------
# Pages
# --------------------------------------------------------------------------

HERO_TABS = [
    dict(id="own", label="Ownership", file="account.gg", code="""struct Account:
    owner: string
    balance: i64

fn show(a: read Account):
    print(a.owner, a.balance)

fn deposit(a: lend Account, amount: i64):
    a.balance += amount

fn close(a: consume Account):
    print("closed", a.owner)

fn main():
    acct = Account{ owner: string.from("Ada"), balance: 100 }
    deposit(acct, 50)
    show(acct)
    close(acct)""",
         note="The mode is written once, on the parameter. The call stays <code>f(x)</code>. After <code>close</code>, <code>acct</code> is gone."),
    dict(id="err", label="Result and ?", file="digits.gg", code="""fn parse_digit(c: u8) -> Result[i32, str]:
    if c < '0' or c > '9':
        return Err("not a digit")
    return Ok(i32(c - '0'))

fn add_digits(a: u8, b: u8) -> Result[i32, str]:
    x = parse_digit(a)?
    y = parse_digit(b)?
    return Ok(x + y)

fn main():
    match add_digits('3', '4'):
        Ok(v):
            print(v)
        Err(e):
            print(e)""",
         note="<code>Optional</code> and <code>Result</code> are prelude enums. <code>?</code> returns early on <code>Err</code> and stands on its own line."),
    dict(id="clo", label="Closures", file="adders.gg", code="""fn make_adder(k: i32) -> Fn(i32) -> i32:
    return fn(x: i32) -> i32 => x + k

fn main():
    steps = List[Fn(i32) -> i32]()
    steps.push(make_adder(1))
    steps.push(make_adder(10))
    v = 0
    for f in steps:
        v = f(v)
    print(v, make_adder(5)(1))""",
         note="<code>Fn</code> is an owned closure: it can be returned and stored in a list. A plain <code>fn</code> argument is compiled for the closure, so the call is direct."),
    dict(id="match", label="match", file="shapes.gg", code="""enum Shape:
    Circle(f64)
    Rect(f64, f64)
    Empty

fn area(s: Shape) -> f64:
    return match s:
        Circle(r) => 3.14159 * r * r
        Rect(w, h) => w * h
        Empty => 0.0

fn main():
    print(area(Shape.Rect(2.0, 3.0)))""",
         note="A <code>match</code> must cover every variant. In a pattern a bare name is a variant, so a typo is an error, not a catch-all."),
    dict(id="test", label="Tests", file="clamp.gg", code="""fn clamp(n: i32, lo: i32, hi: i32) -> i32:
    if n < lo:
        return lo
    elif n > hi:
        return hi
    return n

test:
    require clamp(5, 0, 10) == 5

test edges:
    require clamp(-3, 0, 10) == 0
    require clamp(99, 0, 10) == 10

fn main():
    print(clamp(42, 0, 10))""",
         note="A <code>test</code> block belongs to the function above it. <code>gg test</code> runs them; <code>gg test --json</code> reports each one."),
]


def build_index(rows: list[dict]) -> str:
    faster = sum(r["verdict"] == "faster" for r in rows)
    within = sum(r["verdict"] == "within" for r in rows)
    n = len(rows)
    picks = [r for r in rows if r["id"] in ("matmul", "qsort", "mandel", "trees")]
    bench_rows = "".join(brow(r, "benchmarks.html") for r in picks)
    diag_text = (SITE / "diagnostics" / "use-after-consume.txt").read_text(encoding="utf-8")
    diag_text = diag_text.replace("website\\diagnostics\\", "")
    diag_term = code_window("", "gg check counter.gg", extra_class="term",
                            pre_html='<span class="t-prompt">$ </span>gg check counter.gg\n' + highlight_terminal(diag_text))

    fixed_html = (
        '<span class="tok-kw">fn</span> <span class="tok-fn">main</span>():\n'
        '    <span class="tok-kw">fixed</span> limit <span class="tok-op">=</span> <span class="tok-num">3</span>\n'
        '    total <span class="tok-op">=</span> <span class="tok-num">0</span>\n'
        '    <span class="tok-kw">for</span> i <span class="tok-kw">in</span> <span class="tok-num">0</span><span class="tok-op">..</span>limit:\n'
        '        total <span class="tok-op">+=</span> i\n'
        '    <span class="inlay">fixed</span>name <span class="tok-op">=</span> <span class="tok-str">"gg"</span>\n'
        '    <span class="tok-fn">print</span>(name, total)')

    cards = [
        ("key", "Ownership without lifetimes", "Parameters say <code>read</code>, <code>lend</code>, or <code>consume</code>. A stored reference is <code>tied to</code> the place it came from. There is no lifetime syntax.", "spec.html#parameter-modes"),
        ("bolt", "Native speed through LLVM", f"Release builds keep bounds and overflow checks and still finish within 5% of C++ and Rust, or ahead of both, on {faster + within} of {n} workloads.", "benchmarks.html"),
        ("lock", "Mutability is inferred", "Variables can change by default. One that never changes is treated as <code>fixed</code>, and the editor shows it as an inlay hint.", "spec.html#3-bindings"),
        ("alert", "Failures are loud", "Integer overflow, division by zero, bad shifts, and out-of-bounds indexes trap, in debug and in <code>--release</code>.", "spec.html#12-numbers"),
        ("wrench", "Diagnostics with checked fixes", "<code>gg check --json</code> returns stable codes and fixes. A fix marked <code>verified</code> was applied to a copy and made the error go away.", "diagnostics.html"),
        ("layers", "One way to write it", "One spelling for each construct, one specification, and a list of rejected forms. People and language models read the same language.", "why.html"),
    ]
    card_html = "".join(
        f'<article class="card reveal"><h3><a href="{href}">{t}</a></h3><p>{d}</p></article>'
        for ic, t, d, href in cards)

    modes = [
        ("read", "A shared borrow. The function may read, not assign. The caller keeps the value.", """fn show(a: read Account):
    print(a.balance)"""),
        ("lend", "An exclusive borrow. The function may change the value in place; nothing else may touch it during the call.", """fn deposit(a: lend Account, n: i64):
    a.balance += n"""),
        ("consume", "Takes ownership. After the call the argument is gone, and using it again is a compile error.", """fn close(a: consume Account):
    print("closed")"""),
    ]
    mode_html = "".join(
        f'<div class="mode reveal"><div class="mode-top"><span class="mode-word">{w}</span><p>{d}</p></div>'
        f'<figure class="code"><pre><code>{highlight(c)}</code></pre></figure></div>' for w, d, c in modes)

    body = f"""    <section class="hero">
      <div class="wrap hero-grid">
        <div>
          <p class="eyebrow">Version {VERSION}. New: one-command install for Windows, Linux, and macOS, and <code>gg update</code>. <a href="roadmap.html">What changed</a></p>
          <h1>Systems speed.<br><span class="accent">Readable ownership.</span></h1>
          <p class="lede">Greengold is a statically typed systems language that compiles to native code through LLVM. Ownership is three words on a parameter, mutability is inferred, and every diagnostic can carry a checked fix.</p>
          <div class="hero-actions">
            <a class="btn btn-primary" href="spec.html">{ICONS["book"]} Read the spec</a>
            <a class="btn btn-ghost" href="benchmarks.html">{ICONS["chart"]} See benchmarks</a>
            <a class="btn btn-ghost" href="https://github.com/Greengold-Lang/greengold-lang" rel="noopener">{ICONS["github"]} GitHub</a>
          </div>
          <div class="hero-cmd"><span><span class="prompt">$ </span>gg run hello.gg</span></div>
        </div>
        {tabbed_code(HERO_TABS, "hero-code")}
      </div>
    </section>

    <section class="section tight">
      <div class="wrap">
        <div class="stats reveal">
          <div class="stat"><div class="stat-value">{faster}<small> / {n}</small></div><div class="stat-label">workloads where Greengold beat both C++ and Rust</div></div>
          <div class="stat"><div class="stat-value">{faster + within}<small> / {n}</small></div><div class="stat-label">ahead, or within 5% of the faster of the two</div></div>
          <div class="stat"><div class="stat-value">3</div><div class="stat-label">ownership words: <code>read</code>, <code>lend</code>, <code>consume</code></div></div>
        </div>
      </div>
    </section>

    <section class="section">
      <div class="wrap">
        <div class="section-head reveal">
          <h2>What the language does</h2>
          <p>Native code, value types, and no garbage collector. Six choices define how Greengold reads and fails.</p>
        </div>
        <div class="cards">{card_html}</div>
      </div>
    </section>

    <section class="section alt">
      <div class="wrap">
        <div class="section-head reveal">
          <h2>Ownership is three words</h2>
          <p>The mode is written on the parameter, never at the call.</p>
        </div>
        <div class="modes">{mode_html}</div>
        <div class="callout reveal">{ICONS["info"]}<p>A bare parameter of a heap type gets its mode from the body: <code>read</code> when the body only reads it, <code>lend</code> when it changes it, <code>consume</code> when it moves it. Write the mode only when you want to pin it in the signature.</p></div>
      </div>
    </section>

    <section class="section">
      <div class="wrap">
        <div class="split reveal">
          <div>
            <span class="kicker">Bindings</span>
            <h3>Variables can change. The ones that don't are marked for you.</h3>
            <p>There is no <code>var</code> and no <code>mut</code> on locals. Every variable can change. A variable that nothing changes is treated as <code>fixed</code>, and your editor shows the inferred word as an inlay hint.</p>
            <ul class="checks">
              <li>Write <code>fixed</code> to turn the inference into a guarantee.</li>
              <li>Assigning, lending, or mutating a <code>fixed</code> value is a compile error.</li>
              <li>Writing <code>var</code> is an error that tells you to delete it.</li>
            </ul>
          </div>
          {code_window("", "main.gg — inlay hints on", pre_html=fixed_html)}
        </div>

        <div class="split flip reveal">
          <div>
            <span class="kicker">Diagnostics</span>
            <h3>Diagnostics with fixes the compiler has tried</h3>
            <p>Every diagnostic has a stable <code>GGxxxx</code> code, labels for the definition, the move, and the later use, and a list of fixes.</p>
            <ol class="diag-steps">
              <li><span><code>gg check --json</code> returns the same diagnostic as structured data.</span></li>
              <li><span>The compiler applies each candidate fix to a copy and re-checks it.</span></li>
              <li><span>Only fixes that made the error disappear are marked <code>verified</code>.</span></li>
            </ol>
            <a class="spec-link" href="diagnostics.html">See the full GG0301 output {ICONS["arrow"]}</a>
          </div>
          {diag_term}
        </div>
      </div>
    </section>

    <section class="section alt">
      <div class="wrap">
        <div class="split reveal">
          <div>
            <span class="kicker">Performance</span>
            <h3>Checks stay on in release builds</h3>
            <p>{n} workloads against <code>g++ -O3</code> and <code>rustc -C opt-level=3</code>, measured on {DATE_LONG}. Greengold's <code>--release</code> keeps bounds checks and integer overflow traps on.</p>
            <ul class="checks">
              <li>Median of five runs; peak memory, compile time, and binary size too.</li>
              <li>Every program prints a checked result, so the work is not optimized away.</li>
              <li>Sources for all three languages are published next to the numbers.</li>
            </ul>
            <a class="spec-link" href="benchmarks.html">All {n} workloads {ICONS["arrow"]}</a>
          </div>
          <div class="bench-panel">
            <div class="legend"><span><i class="lg-cpp"></i>C++</span><span><i class="lg-rust"></i>Rust</span><span><i class="lg-gg"></i>Greengold</span><span style="margin-left:auto">shorter is faster</span></div>
            {bench_rows}
          </div>
        </div>
      </div>
    </section>

    <section class="section">
      <div class="wrap">
        <div class="section-head reveal">
          <h2>Status</h2>
          <p>What exists today, and what is outside the safety guarantee.</p>
        </div>
        <div class="status-grid">
          <div class="panel reveal">
            <h3>{ICONS["cpu"]} The toolchain</h3>
            <dl class="kv">
              <dt>Version</dt><dd>{VERSION}. <a href="https://github.com/Greengold-Lang/greengold-lang/releases/latest">Download</a> for Windows, Linux, and macOS, or <a href="https://github.com/Greengold-Lang/greengold-lang">read the source on GitHub</a>.</dd>
              <dt>Compiler</dt><dd>Written in Python. Emits LLVM IR through <code>llvmlite</code> and links with clang or gcc. LLVM is the only backend.</dd>
              <dt>Tools</dt><dd><code>gg check</code>, <code>run</code>, <code>build</code>, <code>test</code>, <code>fmt</code>, <code>doc</code>, <code>api</code>, <code>bindgen</code>, and a language server with inlay hints.</dd>
              <dt>Self-hosting</dt><dd>Paused. The lexer is written in Greengold; language work happens in the Python compiler for now.</dd>
            </dl>
          </div>
          <div class="panel warn reveal">
            <h3>{ICONS["alert"]} Outside the guarantee</h3>
            <ul class="list">
              <li><code>unsafe:</code> blocks — pointers are not checked for liveness, alignment, or bounds.</li>
              <li><code>trust</code>, which skips one bounds check, in <code>unsafe:</code> or a <code>hot fn</code>.</li>
              <li>The <code>--unchecked</code> build flag, which removes bounds checks.</li>
              <li><code>std.thread</code>, a pthread wrapper with no <code>Send</code> or <code>Share</code> bound.</li>
              <li>Not supported: dynamic dispatch, lifetime names, storing or returning a slice <code>[]T</code>.</li>
            </ul>
          </div>
        </div>
      </div>
    </section>

    <section class="section tight">
      <div class="wrap">
        <div class="cta reveal">
          <h2>The language is one document</h2>
          <p>Eighteen sections, one example per feature, and the list of forms the compiler rejects. Also available as plain Markdown for tools and models.</p>
          <div class="hero-actions">
            <a class="btn btn-primary" href="spec.html">{ICONS["book"]} Read the spec</a>
            <a class="btn btn-ghost" href="spec.md">{ICONS["file"]} spec.md</a>
          </div>
        </div>
      </div>
    </section>"""
    return layout("home", "", "Greengold",
                  "Greengold is a statically typed systems language that compiles to native code through LLVM. Ownership is three words on a parameter, mutability is inferred, and diagnostics carry checked fixes.",
                  body)


def build_why() -> str:
    items = [
        ("One way to write each construct",
         "<p>The spec gives one example per feature and a list of forms the compiler rejects. The diagnostic names the rule instead of guessing what you meant, so code written by a person, a teammate, or a language model all looks the same.</p>"
         '<div class="chips"><span class="chip"><s>else if</s><span class="arrow">→</span><b>elif</b></span>'
         '<span class="chip"><s>// note</s><span class="arrow">→</span><b># note</b></span>'
         '<span class="chip"><s>f(consume x)</s><span class="arrow">→</span><b>f(x)</b></span>'
         '<span class="chip"><s>fn T.m()</s><span class="arrow">→</span><b>impl T:</b></span>'
         '<span class="chip"><s>var x = 1</s><span class="arrow">→</span><b>x = 1</b></span></div>',
         "spec.html#17-widths-precedence-and-rejected-forms", "Rejected forms",
         None),
        ("Ownership is three words",
         "<p><code>read</code>, <code>lend</code>, and <code>consume</code> are written on the parameter. The call stays <code>f(x)</code>. For a heap value with no written mode, the compiler reads the body and picks the mode for you — and the caller sees it.</p>",
         "spec.html#parameter-modes", "Parameter modes",
         ("counter.gg", """struct Counter:
    value: i32

fn bump(c: lend Counter):
    c.value += 1

fn finish(c: consume Counter):
    print(c.value)

fn main():
    c = Counter{ value: 1 }
    bump(c)
    finish(c)""")),
        ("Mutable by default, fixed by inference",
         "<p>Variables can change. A variable that nothing changes is treated as <code>fixed</code>, so writing the word only adds a guarantee. Lending or assigning a <code>fixed</code> value is an error. Your editor shows the inferred <code>fixed</code> as an inlay hint, so you see it without typing it.</p>",
         "spec.html#3-bindings", "Bindings",
         ("bindings.gg", """fn main():
    fixed limit = 10
    x = 5
    y = 5
    y = 6
    y += 1
    print(x, y, limit)""")),
        ("No lifetime syntax",
         "<p>A stored <code>read</code> or <code>lend</code> is tied to the variable it came from. When a function returns a reference and more than one parameter could be its origin, you name it with <code>tied to</code> — a parameter name, not a lifetime variable.</p>",
         "spec.html#11-references", "References",
         ("refs.gg", """struct Player:
    hp: i32

fn pick(a: read Player, b: read Player) -> ref Player tied to b:
    return b

fn main():
    hero = Player{ hp: 2 }
    ally = Player{ hp: 6 }
    print(pick(hero, ally).hp)""")),
        ("Failures are loud",
         "<p>Integer <code>+</code>, <code>-</code>, and <code>*</code> trap when the result does not fit. Division by zero and bad shifts trap. Indexing is bounds-checked. All of it stays on in <code>--release</code>. When you want wrapping, you say so: <code>overflow: wrap</code>, a <code>wrapping:</code> block, or <code>a wrapping_add b</code>.</p>",
         "spec.html#12-numbers", "Numbers",
         ("overflow.gg", """fn main():
    n: u8 = 250
    print(checked_add[u8](n, 10).value_or(0))
    print(n wrapping_add 10)
    print(n + 10)   # traps: integer overflow""")),
        ("Diagnostics carry a checked fix",
         "<p><code>gg check --json</code> returns a code, a rule, a message, a span, labels, and fixes. <code>verified</code> means the compiler applied that edit to a copy and the diagnostic went away. Apply a fix when it is <code>safe</code> or <code>likely</code> and <code>verified</code>.</p>",
         "diagnostics.html", "A real GG0301 document", None),
        ("A library you can query",
         "<p><code>gg api --json</code> lists every public symbol with its <code>module</code>, <code>name</code>, <code>kind</code>, <code>signature</code>, and <code>description</code>. Read a signature from the catalog instead of guessing a parameter mode.</p>",
         "spec.html#16-imports-and-the-library", "Imports and the library", None),
    ]
    blocks = []
    for i, (title, text, href, link_label, code) in enumerate(items, 1):
        right = code_window(code[1], code[0]) if code else ""
        cls = "split reveal" + (" flip" if i % 2 == 0 and code else "")
        if code:
            blocks.append(f'<div class="{cls}"><div><span class="why-num">0{i}</span><h3>{title}</h3>{text}'
                          f'<a class="spec-link" href="{href}">{link_label} {ICONS["arrow"]}</a></div>{right}</div>')
        else:
            blocks.append(f'<div class="split reveal"><div style="grid-column:1/-1;max-width:48rem"><span class="why-num">0{i}</span><h3>{title}</h3>{text}'
                          f'<a class="spec-link" href="{href}">{link_label} {ICONS["arrow"]}</a></div></div>')
    body = page_hero("Why Greengold", "Why this shape",
                     "Greengold keeps one spelling for each construct and puts ownership where you can see it, so a person and a language model are reading the same program.") + f"""
    <section class="section" style="padding-top:56px">
      <div class="wrap">
        {"".join(blocks)}
        <div class="callout reveal" style="margin-top:72px">{ICONS["info"]}<p>What this does not cover — <code>unsafe:</code>, <code>trust</code>, <code>--unchecked</code>, and threads — is listed under <a href="index.html#status">status</a>.</p></div>
      </div>
    </section>"""
    return layout("why", "why.html", "Why", "Why Greengold is shaped the way it is: one spelling for each construct, three ownership words, inferred mutability, and diagnostics that carry a checked fix.", body)


DATE_LONG = "13 October 2026"


def build_benchmarks(rows: list[dict]) -> str:
    def names(rs):
        return ", ".join(f'<a href="#{r["id"]}">{esc(r["title"])}</a>' for r in rs) or "None"

    def summary(key, name):
        group = lambda v: [r for r in rows if r["vs"][key]["verdict"] == v]
        return (f'<h3 class="summary-title reveal">Greengold vs. {name}</h3><div class="summary-cards">'
                f'<div class="summary-card faster reveal"><div class="stat-value">{len(group("faster"))}</div><p><strong>Faster than {name}.</strong> {names(group("faster"))}.</p></div>'
                f'<div class="summary-card within reveal"><div class="stat-value">{len(group("within"))}</div><p><strong>Within 5% of {name}.</strong> {names(group("within"))}.</p></div>'
                f'<div class="summary-card slower reveal"><div class="stat-value">{len(group("slower"))}</div><p><strong>More than 5% behind {name}.</strong> {names(group("slower"))}.</p></div></div>')

    chips = "".join(f'<span class="chip">{t}</span>' for t in (
        "AMD Ryzen 5 5600X · 6C/12T", "32 GB DDR4-3600", "Windows 11 Pro 26200",
        "g++ 15.2.0", "rustc 1.97.1 (stable)", "llvmlite 0.42.0"))

    overview = "".join(brow(r, "") for r in rows)
    pills = "".join(f'<a href="#{r["id"]}">{esc(r["title"])}</a>' for r in rows)

    cards = []
    for r in rows:
        res = r["res"]
        if r["higher"]:
            head = "<th>Build</th><th>Passes</th><th>Passes/s</th><th>Memory</th><th>Compile</th><th>Binary</th>"
        else:
            head = "<th>Build</th><th>Median</th><th>Mean</th><th>Memory</th><th>Compile</th><th>Binary</th>"
        trs = []
        for key, cls, name, flag in LANGS:
            m = res[key]
            first = f'{name} <span style="color:var(--muted);font-size:.8rem">{flag}</span>'
            if r["higher"]:
                cells = [f'{m["passes"]:,}', f'{m["passes_per_sec"]:,.0f}']
            else:
                cells = [fmt_ms(m["median_ms"]), fmt_ms(m["mean_ms"])]
            cells += [f'{m["peak_mem_mb"]:.2f} MB', f'{m["compile_time_s"]:.2f} s', f'{m["binary_size_kb"]:.1f} KB']
            trs.append(f'<tr class="{cls}"><td>{first}</td>' + "".join(f"<td>{c}</td>" for c in cells) + "</tr>")
        src_path = SITE / "benchmarks" / "src" / f'{r["id"]}.gg'
        src = src_path.read_text(encoding="utf-8")
        unit = "Completed passes in about 20 seconds. Longer is better." if r["higher"] else "Median of five runs. Shorter is faster."
        cards.append(f"""        <article class="workload reveal" id="{r["id"]}">
          <div class="workload-head"><h3><a href="#{r["id"]}">{esc(r["title"])}</a></h3>{verdict_badge(r)}</div>
          <p class="workload-desc">{r["desc"]}</p>
          <div class="workload-body">
            <div><div class="legend" style="margin-bottom:12px"><span>{unit}</span></div>{bars(r)}</div>
            <div class="table-scroll"><table class="mtable"><thead><tr>{head}</tr></thead><tbody>{"".join(trs)}</tbody></table></div>
          </div>
          <details class="src"><summary>{ICONS["chev"]} Greengold source</summary>{code_window(src, f'{r["id"]}.gg', extra_class="scroll")}</details>
          <div class="workload-foot">Sources: <a href="benchmarks/src/{r["id"]}.gg">{r["id"]}.gg</a><a href="benchmarks/src/{r["id"]}.cpp">{r["id"]}.cpp</a><a href="benchmarks/src/{r["id"]}.rs">{r["id"]}.rs</a></div>
        </article>""")

    body = page_hero("Benchmarks", "Greengold vs. C++ and Rust",
                     f"{len(rows)} workloads, measured on {DATE_LONG}. Greengold builds with <code>--release</code>, which keeps bounds checks and integer overflow traps. Kernels that opt out say so: <code>trust</code> skips a bounds check inside <code>unsafe:</code>, and <code>overflow: wrap</code> wraps instead of trapping. JSON and Trees use neither; Word count wraps only in its random-number generator. See <a href=\"https://github.com/Greengold-Lang/greengold-lang/blob/main/benchmarks/README.md\">benchmarks/README.md</a> for how to read the numbers.",
                     f'<div class="chip-row">{chips}</div>') + f"""
    <section class="section tight" style="padding-top:24px">
      <div class="wrap">
        {summary("cpp", "C++")}
        {summary("rust", "Rust")}
      </div>
    </section>

    <section class="section tight" id="overview">
      <div class="wrap">
        <div class="section-head reveal">
          <h2>Every workload at a glance</h2>
          <p>Each row is scaled to its slowest build. Each badge compares Greengold with that one language; a gap of 5% or less is treated as noise.</p>
        </div>
        <div class="bench-panel reveal">
          <div class="legend"><span><i class="lg-cpp"></i>C++ · g++ -O3</span><span><i class="lg-rust"></i>Rust · opt-level=3</span><span><i class="lg-gg"></i>Greengold · --release</span></div>
          <div class="overview-grid">{overview}</div>
        </div>
      </div>
    </section>

    <section class="section tight">
      <div class="wrap">
        <div class="section-head reveal">
          <h2>Workloads</h2>
          <p>Each program prints a result that is checked, so the work cannot be optimized away. Open a workload for the full numbers and the Greengold source.</p>
        </div>
        <nav class="toc-pills reveal" aria-label="Workloads" style="margin-bottom:28px">{pills}</nav>
        <div class="workloads">
{chr(10).join(cards)}
        </div>
      </div>
    </section>

    <section class="section tight">
      <div class="wrap">
        <div class="section-head reveal"><h2>Method</h2></div>
        <div class="method">
          <div class="panel reveal"><h3>{ICONS["flask"]} How it was measured</h3><ul class="list">
            <li>Timed programs report the median of five runs. The primes drag race is one run of about 20 seconds, scored by completed passes.</li>
            <li>Memory is peak working set. Compile time and binary size are from the same build.</li>
            <li>Raw numbers, including every printed output, are in <a href="benchmarks/data.json">benchmarks/data.json</a>.</li>
          </ul></div>
          <div class="panel reveal"><h3>{ICONS["cpu"]} Builds and machine</h3><ul class="list">
            <li><code>g++ -O3</code> (15.2.0), <code>rustc -C opt-level=3</code> (1.97.1 stable, 2026-07-14), <code>gg build --release</code> with Python 3.11.5 and llvmlite 0.42.0.</li>
            <li>AMD Ryzen 5 5600X, 6 cores and 12 threads, 32 GB DDR4-3600, Windows 11 Pro build 26200.</li>
            <li>Greengold sources use <code>hot fn</code>, <code>trust</code>, and <code>overflow: wrap</code> where the workload notes say so.</li>
          </ul></div>
        </div>
      </div>
    </section>"""
    return layout("benchmarks", "benchmarks.html", "Benchmarks",
                  f"Greengold, C++, and Rust on {len(rows)} workloads, measured on {DATE_LONG}.", body)


def build_diagnostics() -> str:
    src = (SITE / "diagnostics" / "use-after-consume.gg").read_text(encoding="utf-8").rstrip("\n")
    lines = []
    for i, line in enumerate(src.split("\n"), 1):
        cls = " hl" if i == 10 else (" hl2" if i in (4, 9) else "")
        lines.append(f'<span class="ln{cls}">{highlight_line(line) or " "}</span>')
    src_html = "".join(lines)
    text = (SITE / "diagnostics" / "use-after-consume.txt").read_text(encoding="utf-8")
    js = (SITE / "diagnostics" / "use-after-consume.json").read_text(encoding="utf-8")
    fields = [
        ("code · rule", "A stable code (<code>GG0301</code>) and a rule name. <code>gg explain GG0301</code> prints the long form."),
        ("span · labels", "Where the error is, plus labels for the definition, the move, and the parameter that caused it."),
        ("details", "<code>callee</code> and <code>parameter</code> name the signature that moved the value."),
        ("fixes", "Each fix has edits, an <code>applicability</code> (<code>safe</code>, <code>likely</code>, <code>manual</code>), and <code>verified</code>."),
        ("verified", "The compiler applied the edit to a copy, re-checked it, and the diagnostic went away."),
        ("manual", "A hint, not an edit. A person or a model has to decide what the program should do."),
    ]
    field_html = "".join(f'<div class="field reveal"><code>{a}</code><p>{b}</p></div>' for a, b in fields)
    src_win = code_window(src, "use-after-consume.gg", pre_html=f'<span class="lines">{src_html}</span>',
                          note="<code>finish</code> takes <code>c</code> as <code>consume</code> on line 9, "
                               "so reading <code>c.value</code> on line 10 is an error.")
    term_win = code_window("", "gg check use-after-consume.gg", extra_class="term",
                           pre_html='<span class="t-prompt">$ </span>gg check use-after-consume.gg\n' + highlight_terminal(text))
    json_win = code_window(js, "gg check use-after-consume.gg --json", lang="json", extra_class="scroll")
    body = page_hero("Diagnostics", "Diagnostics",
                     "<code>gg check</code> reports a use-after-consume error, in text for people and in JSON for tools. Both come from the same diagnostic.",
                     '<p>Files: <a href="diagnostics/use-after-consume.gg">use-after-consume.gg</a> · <a href="diagnostics/use-after-consume.txt">.txt</a> · <a href="diagnostics/use-after-consume.json">.json</a></p>') + f"""
    <section class="section tight" style="padding-top:24px">
      <div class="wrap">
        <div class="diag-grid">
          <div class="reveal">
            <h2 style="font-size:1.4rem;margin-bottom:14px">The program</h2>
            {src_win}
          </div>
          <div class="reveal">
            <h2 style="font-size:1.4rem;margin-bottom:14px">What a person sees</h2>
            {term_win}
          </div>
          <div class="full reveal">
            <h2 style="font-size:1.4rem;margin:18px 0 14px">What a tool sees</h2>
            {json_win}
          </div>
        </div>
      </div>
    </section>

    <section class="section tight">
      <div class="wrap">
        <div class="section-head reveal">
          <h2>Reading the document</h2>
          <p>The rule for tools is short: apply a fix only when its <code>applicability</code> is <code>safe</code> or <code>likely</code> and <code>verified</code> is true. Here, two fixes meet that bar and one is <code>manual</code>.</p>
        </div>
        <div class="fields">{field_html}</div>
      </div>
    </section>"""
    return layout("diagnostics", "diagnostics.html", "Diagnostics",
                  "A real Greengold use-after-consume diagnostic from gg check, in text and JSON, with verified fixes.", body)


def build_roadmap() -> str:
    v030 = [
        "LLVM is the only backend; the C99 backend is removed",
        "<code>var</code> removed; variables are mutable, <code>fixed</code> is inferred",
        "Inlay hints for inferred <code>fixed</code> in the language server",
        "Parameter modes inferred for heap values from the body",
        "<code>for x in xs:</code> lends elements when the body changes <code>x</code>",
        "Closures, and owned closures <code>Fn(A) -> R</code>",
        "<code>.clone()</code> and reference-counted <code>Shared[T]</code>",
        "<code>consume self</code> methods",
        "HashMap and HashSet with heap keys and values",
        "<code>List</code> <code>insert</code>, <code>remove</code>, <code>swap</code>, <code>swap_remove</code>",
        "<code>test</code> blocks, <code>require</code>, and <code>gg test --json</code>",
        "Borrowed <code>str</code> views are tracked against their owner",
    ]
    v031 = [
        "Control-flow borrow liveness (non-lexical borrows) across branches and loops",
        "Inter-procedural view-flow summaries and <code>fn drop(self: lend Self)</code> destructors",
        "Generic bodies checked against their bounds (<code>Copy</code>, <code>Key</code>, features) at declaration",
        "<code>dyn Feature</code> for dynamic dispatch through owned feature values",
        "Slices <code>[]T</code> stored in variables and structs, and returned from functions",
        "Capturing <code>Thread.spawn</code>, inferred <code>send</code>, <code>Arc[T]</code>, and blocking <code>Queue[T]</code>",
        "<code>gg api --lock</code> and <code>--check</code> for semver-checked inferred public APIs",
        "Normative spec, conformance suite, and <code>edition = \"2026\"</code> in <code>gg.toml</code>",
    ]
    v032 = [
        "Hardware atomic intrinsics with memory orderings and lock-free <code>Atomic[T]</code>",
        "<code>static</code> globals, constant array/struct literals, and <code>volatile_read</code> / <code>volatile_write</code>",
        "<code>union</code>, <code>packed struct</code>, <code>align(N) struct</code>, and inline <code>asm[T]</code>",
        "SIMD vector types (<code>f32x4</code>, <code>i32x8</code>, <code>u8x16</code>, ...) lowered to LLVM vectors",
        "<code>allocator alloc, resize, free</code> for a custom or <code>--no-std</code> heap",
        "<code>std.net</code> TCP sockets, <code>std.io</code> <code>File</code> streams, <code>target_os()</code>, and <code>weak extern</code>",
    ]
    v033 = [
        "<code>gg build -g</code> emits DWARF debug info for <code>gdb</code> and <code>lldb</code>",
        "Git and registry dependencies, <code>gg.lock</code>, and <code>gg fetch</code> / <code>update</code> / <code>publish</code>",
        "Cross-compilation (<code>--target</code>, <code>gg targets</code>), including <code>wasm32</code> and <code>cortex-m4</code>",
        "C++ interop with <code>gg bindgen --cpp</code> and <code>[native]</code> C/C++ sources in <code>gg.toml</code>",
        "Faster <code>gg check</code> and <code>gg build</code> via non-recursive AST walks and pickle snapshots",
        "<code>:=</code> removed in favor of <code>=</code>, and VS Code extension with <code>gg fix</code> and debugging",
    ]
    v04 = [
        "Installers for Windows, Linux, and macOS that need no Python, and a Windows setup program",
        "<code>gg update</code> replaces the installed compiler with the newest release; <code>gg update --deps</code> re-resolves dependencies",
        "Prebuilt <code>gg</code> for Windows x64, Linux x64 and arm64, and macOS arm64, with Zig inside for linking",
        "VS Code extension runs the installed <code>gg</code>; the <code>.vsix</code> is part of each release",
    ]
    v05 = [
        "Browser playground: live diagnostics, checked fixes, and <strong>Run</strong>, with the compiler running in your browser",
        "<code>wasm32-wasi</code> target: <code>print</code>, strings, <code>List</code>, and <code>HashMap</code> in WebAssembly",
        "<code>gg doctor</code>, <code>gg repl</code>, <code>gg run -e</code>, and <code>gg new --template</code>",
    ]
    nxt = [
        "An Intel Mac build (needs an <code>llvmlite</code> wheel for that platform)",
        "Freezing the <code>2026</code> edition for 1.0",
    ]
    paused = [
        "The lexer is written in Greengold and checked against the Python lexer",
        "The parser, type checker, and code generator stay in Python while the language settles",
    ]
    def ul(items):
        return "<ul class=\"ticks\">" + "".join(f"<li>{i}</li>" for i in items) + "</ul>"
    body = page_hero("Roadmap", "Roadmap",
                     f"Version {VERSION}. The compiler is written in Python and emits LLVM IR through <code>llvmlite</code>. Prebuilt downloads are on the <a href=\"https://github.com/Greengold-Lang/greengold-lang/releases/latest\">GitHub releases page</a>.", narrow=True) + f"""
    <section class="section tight" style="padding-top:24px">
      <div class="wrap narrow">
        <div class="timeline">
          <div class="milestone done reveal"><div class="panel"><h3>In 0.3.0 <span class="state done">shipped</span></h3>{ul(v030)}</div></div>
          <div class="milestone done reveal"><div class="panel"><h3>In 0.3.1 <span class="state done">shipped</span></h3>{ul(v031)}</div></div>
          <div class="milestone done reveal"><div class="panel"><h3>In 0.3.2 <span class="state done">shipped</span></h3>{ul(v032)}</div></div>
          <div class="milestone done reveal"><div class="panel"><h3>In 0.3.3 <span class="state done">shipped</span></h3>{ul(v033)}</div></div>
          <div class="milestone done reveal"><div class="panel"><h3>In 0.4.x <span class="state done">shipped</span></h3>{ul(v04)}</div></div>
          <div class="milestone done reveal"><div class="panel"><h3>In 0.5.0 <span class="state done">shipped</span></h3>{ul(v05)}</div></div>
          <div class="milestone next reveal"><div class="panel"><h3>Next <span class="state next">planned</span></h3>{ul(nxt)}</div></div>
          <div class="milestone paused reveal"><div class="panel"><h3>Self-hosting <span class="state paused">paused</span></h3>{ul(paused)}</div></div>
        </div>
        <div class="callout reveal" style="margin-top:40px">{ICONS["info"]}<p>Not in the language today, by design: lifetime names and written <code>Send</code>/<code>Share</code> bounds (thread safety is inferred on <code>send</code> parameters). See the <a href="spec.html#17-widths-precedence-and-rejected-forms">rejected forms</a>.</p></div>
      </div>
    </section>"""
    return layout("roadmap", "roadmap.html", "Roadmap",
                  f"Greengold {VERSION}: what shipped, what is next, and the state of self-hosting.", body)


def playground_version() -> str:
    """Hash of the playground scripts, so a changed script is never served from a stale cache."""
    import hashlib
    h = hashlib.sha256()
    for name in ("highlight.js", "editor.js", "playground.js", "worker.js", "toolchain.js", "runner.js"):
        h.update((SITE / "playground" / name).read_bytes())
    return h.hexdigest()[:10]


def build_learn() -> str:
    """The Learn app (website/learn/): lessons, an editor and the standard library reference. The page is only the frame;
    learn.js draws everything from website/learn/content/."""
    body = """    <div class="wrap">
      <div id="learn" class="learn">
        <aside class="learn-side" id="learn-side" aria-label="Contents"></aside>
        <section class="learn-main" id="learn-main" aria-live="polite"></section>
        <section class="learn-lab" id="learn-lab" hidden>
          <div class="pg-bar">
            <button type="button" class="btn btn-primary" id="lab-run"></button>
            <button type="button" class="btn btn-ghost" id="lab-stop" hidden></button>
            <button type="button" class="btn btn-ghost" id="lab-reset"></button>
            <span class="pg-status" id="lab-status" role="status" aria-live="polite"></span>
          </div>
          <div class="pg-progress" id="lab-progress" role="presentation" hidden><span></span></div>
          <div class="pg-pane lab-editor"><pre class="pg-gutter" id="lab-gutter" aria-hidden="true">1</pre>
            <div class="pg-code"><pre class="pg-hl" id="lab-hl" aria-hidden="true"></pre>
              <textarea class="pg-editor" id="lab-editor" spellcheck="false" autocapitalize="off" autocomplete="off" aria-label="Code"></textarea></div></div>
          <pre class="pg-out lab-out" id="lab-out" aria-label="Output"></pre>
          <div class="lab-verdict" id="lab-verdict" role="status" hidden></div>
        </section>
      </div>
    </div>
    <script src="playground/highlight.js"></script>
    <script src="playground/editor.js"></script>
    <script src="learn/ui.js"></script>
    <script src="learn/learn.js"></script>"""
    return layout("learn", "learn/index.html", "Learn",
                  "Learn Greengold step by step in your browser: lessons, runnable code, exercises, and the standard library.",
                  body, root="../", extra_head='  <link rel="stylesheet" href="learn/learn.css">\n')


def build_playground() -> str:
    body = page_hero("Playground", "Playground",
                     "Write Greengold, see errors and checked fixes as you type, and run the program, all in the browser. "
                     "The real compiler runs on your machine; nothing is uploaded.") + """
    <section class="section tight" style="padding-top:8px">
      <div class="wrap">
        <div class="pg-bar">
          <div class="pg-menu">
            <button type="button" class="btn btn-ghost" id="pg-examples-btn" aria-haspopup="listbox" aria-expanded="false" aria-controls="pg-examples">Examples
              <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M6 9l6 6 6-6"/></svg></button>
            <ul class="pg-list" id="pg-examples" role="listbox" aria-label="Examples" hidden></ul>
          </div>
          <button type="button" class="btn btn-ghost" id="pg-fix" title="Apply every verified fix">Fix</button>
          <button type="button" class="btn btn-ghost" id="pg-fixlikely" title="Also apply fixes that are probably what you meant">Fix (likely)</button>
          <button type="button" class="btn btn-ghost" id="pg-format">Format</button>
          <button type="button" class="btn btn-ghost" id="pg-share">Copy link</button>
          <button type="button" class="btn btn-primary" id="pg-run" title="Compile and run in the browser (Ctrl+Enter)">Run</button>
          <button type="button" class="btn btn-ghost" id="pg-stop" hidden>Stop</button>
          <div class="pg-seg" id="pg-mode" role="radiogroup" aria-label="Build mode">
            <button type="button" role="radio" aria-checked="true" data-mode="debug" title="Fast to build, with every runtime check">Debug</button>
            <button type="button" role="radio" aria-checked="false" data-mode="release" title="Optimized (LLVM -O3); bounds and overflow checks stay on">Release</button>
          </div>
          <span class="pg-status" id="pg-status" role="status" aria-live="polite">Loading…</span>
        </div>
        <div class="pg-progress" id="pg-progress" role="presentation" hidden><span></span></div>
        <div class="pg">
          <div class="pg-pane"><pre class="pg-gutter" id="pg-gutter" aria-hidden="true">1</pre>
            <div class="pg-code"><pre class="pg-hl" id="pg-hl" aria-hidden="true"></pre>
              <textarea class="pg-editor" id="pg-editor" spellcheck="false" autocapitalize="off" autocomplete="off" aria-label="Code"></textarea></div></div>
          <div class="pg-pane pg-right">
            <div class="pg-tabs" role="tablist">
              <button type="button" role="tab" id="pg-tab-diag" aria-selected="true">Diagnostics</button>
              <button type="button" role="tab" id="pg-tab-output" aria-selected="false">Output</button>
            </div>
            <pre class="pg-out" id="pg-out" aria-label="Diagnostics">Loading the compiler…</pre>
            <pre class="pg-out" id="pg-runout" aria-label="Program output" hidden></pre>
          </div>
        </div>
        <details class="pg-stdin"><summary>Input for the program (stdin)</summary>
          <textarea id="pg-stdin" spellcheck="false" rows="3" aria-label="Program input"></textarea></details>
        <p style="margin-top:16px">Programs run in your browser: <code>print</code>, strings, <code>List</code>, <code>HashMap</code>, and <code>input</code> work.
          Threads, tasks, sockets, and files do not; to use them, <a href="https://github.com/Greengold-Lang/greengold-lang#install">install gg</a>.
          The first Run downloads the compiler once (tens of MB; your browser keeps it).</p>
        <p class="pg-keys">Editor: <kbd>Ctrl</kbd>+<kbd>Enter</kbd> runs, <kbd>Tab</kbd> indents (<kbd>Shift</kbd>+<kbd>Tab</kbd> outdents), <kbd>Ctrl</kbd>+<kbd>/</kbd> comments lines, brackets and quotes close themselves, and <kbd>Esc</kbd> then <kbd>Tab</kbd> leaves the editor.</p>
      </div>
    </section>
    <script src="playground/highlight.js?v=@V@" defer></script>
    <script src="playground/editor.js?v=@V@" defer></script>
    <script src="playground/playground.js?v=@V@" defer></script>""".replace("@V@", playground_version())
    return layout("playground", "playground.html", "Playground",
                  "Try Greengold in the browser: live diagnostics, checked fixes, and explanations from the real compiler.", body)


def build_about() -> str:
    body = page_hero("About", "About",
                     "Greengold is designed by Umut Faruk Dilli: a systems language with C++ and Rust speed that stays friendly to read and to learn.", narrow=True) + f"""
    <section class="section tight" style="padding-top:24px">
      <div class="wrap narrow">
        <div class="profile reveal">
          <div class="avatar" aria-hidden="true">UF</div>
          <div>
            <h2>Umut Faruk Dilli</h2>
            <p>Designer of Greengold. Questions, feedback, and collaboration are welcome.</p>
          </div>
        </div>
        <div class="contact-grid">
          <button type="button" class="contact reveal" data-copy="founder@greengoldlang.com" title="Copy email address">{ICONS["mail"]}<div><span aria-live="polite">Email</span><strong>founder@greengoldlang.com</strong></div></button>
          <a class="contact reveal" href="https://www.linkedin.com/in/umutfarukdilli/">{ICONS["linkedin"]}<div><span>LinkedIn</span><strong>umutfarukdilli</strong></div></a>
          <a class="contact reveal" href="https://github.com/Greengold-Lang/greengold-lang">{ICONS["github"]}<div><span>Source code</span><strong>Greengold-Lang/greengold-lang</strong></div></a>
          <a class="contact reveal" href="https://www.patreon.com/greengoldlang" rel="noopener">{ICONS["heart"]}<div><span>Support the project</span><strong>patreon.com/greengoldlang</strong></div></a>
          <a class="contact reveal" href="https://github.com/UmutFarukDilli">{ICONS["github"]}<div><span>GitHub</span><strong>UmutFarukDilli</strong></div></a>
        </div>
      </div>
    </section>"""
    return layout("about", "about.html", "About",
                  "Greengold is designed by Umut Faruk Dilli. Contact: founder@greengoldlang.com.", body)


# --------------------------------------------------------------------------
# Spec rendering (the subset of Markdown that SPEC.md uses)
# --------------------------------------------------------------------------

def slug(text: str) -> str:
    text = re.sub(r"<[^>]+>", "", text).lower()
    text = re.sub(r"[^\w\- ]", "", text)
    return text.strip().replace(" ", "-")


def inline(text: str) -> str:
    parts = re.split(r"(`[^`]+`)", text)
    out = []
    for p in parts:
        if p.startswith("`") and p.endswith("`") and len(p) > 1:
            out.append(f"<code>{esc(p[1:-1])}</code>")
        else:
            p = esc(p)
            p = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r'<a href="\2">\1</a>', p)
            p = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", p)
            out.append(p)
    return "".join(out)


def render_spec(md: str) -> tuple[str, list]:
    lines = md.replace("\r\n", "\n").split("\n")
    out: list[str] = []
    toc: list = []
    para: list[str] = []
    i = 0
    intro_open = False

    def flush():
        if para:
            out.append(f"<p>{inline(' '.join(para))}</p>")
            para.clear()

    while i < len(lines):
        line = lines[i]
        if line.startswith("```"):
            flush()
            lang = line[3:].strip()
            j = i + 1
            buf = []
            while j < len(lines) and not lines[j].startswith("```"):
                buf.append(lines[j])
                j += 1
            src = "\n".join(buf)
            out.append(f'<figure class="code bare">{copy_button()}<pre><code>{highlight(src)}</code></pre></figure>' if lang == "gg"
                       else f'<figure class="code"><pre><code>{esc(src)}</code></pre></figure>')
            i = j + 1
            continue
        m = re.match(r"(#{1,3}) (.*)", line)
        if m:
            flush()
            level = len(m.group(1))
            text = m.group(2)
            if level == 1:
                out.append(f"<h1>{inline(text)}</h1>")
                out.append('<div class="intro">')
                intro_open = True
            else:
                if intro_open:
                    out.append("</div>")
                    intro_open = False
                hid = slug(text)
                nm = re.match(r"(\d+)\. (.*)", text)
                if level == 2 and nm:
                    inner = f'<span class="num">{nm.group(1)}.</span>{inline(nm.group(2))}'
                    toc.append([nm.group(1), nm.group(2), hid, []])
                else:
                    inner = inline(text)
                    if level == 3 and toc:
                        toc[-1][3].append((text, hid))
                out.append(f'<h{level} id="{hid}">{inner}<a class="anchor" href="#{hid}" aria-label="Link to this section">#</a></h{level}>')
            i += 1
            continue
        if line.startswith("- "):
            flush()
            items = []
            while i < len(lines) and lines[i].startswith("- "):
                items.append(f"<li>{inline(lines[i][2:])}</li>")
                i += 1
            out.append(f"<ul>{''.join(items)}</ul>")
            continue
        if line.startswith("|"):
            flush()
            rows = []
            while i < len(lines) and lines[i].startswith("|"):
                rows.append([c.strip() for c in lines[i].strip().strip("|").split("|")])
                i += 1
            head, body_rows = rows[0], [r for r in rows[2:]]
            t = "<table><thead><tr>" + "".join(f"<th>{inline(c)}</th>" for c in head) + "</tr></thead><tbody>"
            t += "".join("<tr>" + "".join(f"<td>{inline(c)}</td>" for c in r) + "</tr>" for r in body_rows)
            out.append(t + "</tbody></table>")
            continue
        if not line.strip():
            flush()
        else:
            para.append(line.strip())
        i += 1
    flush()
    if intro_open:
        out.append("</div>")
    return "\n".join(out), toc


def build_spec() -> str:
    md = SPEC.read_text(encoding="utf-8")
    doc, toc = render_spec(md)
    toc_items = []
    for num, title, hid, subs in toc:
        sub = ""
        if subs:
            sub = "<ol>" + "".join(f'<li><a href="#{s}"><span class="n"></span>{inline(t)}</a></li>' for t, s in subs) + "</ol>"
        toc_items.append(f'<li><a href="#{hid}"><span class="n">{num}</span><span>{inline(title)}</span></a>{sub}</li>')
    body = page_hero("Specification", "Specification",
                     "The whole language in one document: one example per feature, and the forms the compiler rejects.",
                     f'<div class="hero-actions" style="margin-top:22px"><a class="btn btn-ghost" href="spec.md">{ICONS["file"]} Plain text: spec.md</a></div>') + f"""
    <div class="wrap spec-layout">
      <details class="spec-toc" open>
        <summary>Contents {ICONS["chev"]}</summary>
        <div class="toc-body">
          <input class="toc-search" type="search" placeholder="Filter sections" aria-label="Filter sections">
          <ol>{"".join(toc_items)}</ol>
        </div>
      </details>
      <article class="spec-doc">
{doc}
      </article>
    </div>"""
    return layout("spec", "spec.html", "Specification",
                  "The Greengold language specification: syntax, ownership, types, and the forms the compiler rejects.", body)


# --------------------------------------------------------------------------

def main() -> None:
    rows = load_bench()
    pages = {
        "index.html": build_index(rows),
        "why.html": build_why(),
        "spec.html": build_spec(),
        "benchmarks.html": build_benchmarks(rows),
        "diagnostics.html": build_diagnostics(),
        "roadmap.html": build_roadmap(),
        "playground.html": build_playground(),
        "learn/index.html": build_learn(),
        "about.html": build_about(),
    }
    for name, text in pages.items():
        (SITE / name).write_text(text, encoding="utf-8", newline="\n")
    shutil.copyfile(SPEC, SITE / "spec.md")
    sitemap = ["<?xml version=\"1.0\" encoding=\"UTF-8\"?>",
               "<urlset xmlns=\"http://www.sitemaps.org/schemas/sitemap/0.9\">"]
    for path in ["", "why.html", "spec.html", "spec.md", "benchmarks.html", "playground.html", "learn/index.html", "diagnostics.html",
                 "roadmap.html", "about.html", "benchmarks/data.json"]:
        sitemap.append(f"  <url><loc>{DOMAIN}/{path}</loc><lastmod>{UPDATED}</lastmod></url>")
    sitemap.append("</urlset>")
    (SITE / "sitemap.xml").write_text("\n".join(sitemap) + "\n", encoding="utf-8", newline="\n")
    print("wrote", ", ".join(pages), "spec.md, sitemap.xml")


if __name__ == "__main__":
    main()
