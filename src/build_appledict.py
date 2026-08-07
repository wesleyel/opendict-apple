#!/usr/bin/env python3
"""Convert Open Dictionary distribution.jsonl(.gz) into Apple Dictionary XML.

Input contract: distribution_entry_v5
  https://github.com/ahpxex/open-dictionary/blob/main/docs/export_contracts.md

Usage:
  python3 build_appledict.py --inspect distribution.jsonl.gz
  python3 build_appledict.py distribution.jsonl.gz -o OpenDictionary.xml
  python3 build_appledict.py distribution.jsonl.gz -o test.xml --limit 500
"""

from __future__ import annotations

import argparse
import gzip
import io
import json
import re
import sys
from xml.sax.saxutils import escape, quoteattr

NS = (
    '<d:dictionary xmlns="http://www.w3.org/1999/xhtml" '
    'xmlns:d="http://www.apple.com/DTDs/DictionaryService-1.0.rng">'
)

PRIORITY_LABEL = {"core": "核心", "common": "常用", "rare": "生僻"}
PRIORITY_ORDER = {"core": 0, "common": 1, "rare": 2}

# Referenced from Info.plist as DCSDictionaryFrontMatterReferenceID. Carries the
# CC BY-SA 4.0 attribution required for redistributing the dictionary data.
FRONT_MATTER_ID = "front_back_matter"
FRONT_MATTER_TITLE = "Open Dictionary"

# Only these tags are treated as region markers on pronunciations.
US_TAGS = {"us", "general-american", "generalamerican", "ga", "american"}
UK_TAGS = {"uk", "received-pronunciation", "receivedpronunciation", "rp", "british"}


def open_maybe_gzip(path: str) -> io.TextIOBase:
    if path == "-":
        return sys.stdin
    if path.endswith(".gz"):
        return io.TextIOWrapper(gzip.open(path, "rb"), encoding="utf-8")
    return open(path, encoding="utf-8")


# --- defensive field extraction -------------------------------------------
# The JSONL contract pins the fields we care about most (headword, pos_groups,
# meanings, examples). Sub-object shapes for forms / pronunciations / relations
# are less pinned down, so probe a few plausible key names rather than assuming.

_TEXT_KEYS = ("text", "value", "form", "ipa", "word", "term", "headword", "note", "label")
_TAG_KEYS = ("tags", "tag", "labels", "qualifiers")

# XML 1.0 forbids most control characters, and escape() will not save us: they
# are illegal as raw codepoints, not merely as markup. The upstream data is
# almost clean (v2.0 carries a single U+0014 across 84k entries), but one such
# character makes the whole document unparseable, so strip them at the single
# point where data-derived text enters the document.
_INVALID_XML = re.compile(
    "[^\u0009\u000a\u000d\u0020-\ud7ff\ue000-\ufffd\U00010000-\U0010ffff]"
)
stripped_chars = 0


def _clean(s: str) -> str:
    global stripped_chars
    cleaned = _INVALID_XML.sub("", s)
    stripped_chars += len(s) - len(cleaned)
    return cleaned.strip()


def as_text(v) -> str:
    if v is None:
        return ""
    if isinstance(v, str):
        return _clean(v)
    if isinstance(v, (int, float)):
        return str(v)
    if isinstance(v, dict):
        for k in _TEXT_KEYS:
            if isinstance(v.get(k), str) and v[k].strip():
                return _clean(v[k])
        return ""
    if isinstance(v, list):
        return ", ".join(t for t in (as_text(i) for i in v) if t)
    return ""


def as_tags(v) -> list[str]:
    if not isinstance(v, dict):
        return []
    for k in _TAG_KEYS:
        raw = v.get(k)
        if isinstance(raw, str):
            return [raw]
        if isinstance(raw, list):
            return [t for t in (as_text(i) for i in raw) if t]
    return []


def is_word(s: str) -> bool:
    """Wiktextract writes '-' (427 times in v2.0, plus one '#') where a form
    does not exist. Indexing those yields a null search key, and displaying
    them yields a bare dash in the entry body."""
    return any(ch.isalnum() for ch in s)


def region_of(pron: dict) -> str:
    tags = {t.lower().replace(" ", "-") for t in as_tags(pron)}
    for key in ("region", "accent", "variety"):
        if isinstance(pron.get(key), str):
            tags.add(pron[key].lower().replace(" ", "-"))
    if tags & US_TAGS:
        return "US"
    if tags & UK_TAGS:
        return "UK"
    return ""


# --- XML helpers -----------------------------------------------------------

_ID_BAD = re.compile(r"[^A-Za-z0-9_.-]")


def make_id(raw: str, seen: set[str]) -> str:
    base = "e_" + _ID_BAD.sub("_", raw or "x")
    ident, n = base, 1
    while ident in seen:
        n += 1
        ident = f"{base}_{n}"
    seen.add(ident)
    return ident


def el(tag: str, text: str, cls: str = "") -> str:
    if not text:
        return ""
    attr = f' class="{cls}"' if cls else ""
    return f"<{tag}{attr}>{escape(text)}</{tag}>"


def index(value: str, title: str, priority: int = 0) -> str:
    if not value:
        return ""
    p = f' d:priority="{priority}"' if priority else ""
    return f"<d:index d:value={quoteattr(value)} d:title={quoteattr(title)}{p}/>"


# --- entry rendering -------------------------------------------------------


def render_pos_group(g: dict, min_priority: int) -> str:
    out = []
    pos = as_text(g.get("pos")) or "—"
    if g.get("proper_name"):
        pos += " · 专名"
    out.append(el("h2", pos, "pos"))

    prons = []
    for p in g.get("pronunciations") or []:
        ipa = as_text(p)
        if not ipa:
            continue
        r = region_of(p) if isinstance(p, dict) else ""
        prons.append(f"{r} /{ipa.strip('/')}/" if r else f"/{ipa.strip('/')}/")
    if prons:
        out.append(el("div", "  ".join(prons), "pron"))

    out.append(el("div", as_text(g.get("summary")), "possum"))

    forms = []
    for f in g.get("forms") or []:
        t = as_text(f)
        if not is_word(t):
            continue
        tags = as_tags(f) if isinstance(f, dict) else []
        forms.append(f"{t}（{'/'.join(tags)}）" if tags else t)
    if forms:
        out.append(el("div", "变形：" + "，".join(forms), "forms"))

    out.append(el("div", as_text(g.get("usage_note")), "usage"))

    senses = []
    for m in g.get("meanings") or []:
        prio = (as_text(m.get("priority")) or "common").lower()
        if PRIORITY_ORDER.get(prio, 1) > min_priority:
            continue
        s = [f'<li class="sense {escape(prio)}">']
        s.append(el("span", PRIORITY_LABEL.get(prio, prio), f"prio {prio}"))
        s.append(el("span", as_text(m.get("short_gloss")), "gloss"))
        s.append(el("div", as_text(m.get("learner_explanation")), "expl"))
        s.append(el("div", as_text(m.get("usage_note")), "musage"))
        exs = []
        for ex in m.get("examples") or []:
            if not isinstance(ex, dict):
                continue
            en, zh = as_text(ex.get("text")), as_text(ex.get("translation"))
            if not en:
                continue
            exs.append("<li>" + el("span", en, "en") + el("span", zh, "tr") + "</li>")
        if exs:
            s.append('<ul class="examples">' + "".join(exs) + "</ul>")
        s.append("</li>")
        senses.append("".join(s))

    if not senses:  # contract: never render an entry group empty due to filtering
        return ""
    out.append('<ol class="senses">' + "".join(senses) + "</ol>")
    return '<div class="posgroup">' + "".join(x for x in out if x) + "</div>"


def render_relations(g: dict) -> str:
    rows = []
    for r in g.get("relations") or []:
        if not isinstance(r, dict):
            continue
        kind = as_text(r.get("relation") or r.get("type") or r.get("kind"))
        targets = r.get("targets") or r.get("words") or r.get("terms") or r.get("target")
        text = as_text(targets)
        if text:
            rows.append(f"{kind}：{text}" if kind else text)
    return el("div", "　".join(rows), "rel")


def render_entry(e: dict, ident: str, min_priority: int) -> str:
    headword = as_text(e.get("headword"))
    if not headword:
        return ""

    body = []
    body.append(el("h1", headword, "hw"))
    body.append(el("div", as_text(e.get("headword_summary")), "summary"))
    hook = as_text(e.get("memory_hook"))
    if hook:
        body.append(
            '<div class="hook"><span class="label">记忆主线</span>'
            + escape(hook)
            + "</div>"
        )

    groups = [render_pos_group(g, min_priority) for g in e.get("pos_groups") or []]
    groups = [g for g in groups if g]
    if not groups:  # fall back to showing everything rather than an empty entry
        groups = [g for g in (render_pos_group(g, 2) for g in e.get("pos_groups") or []) if g]
    if not groups:
        return ""
    body.extend(groups)

    for g in e.get("pos_groups") or []:
        body.append(render_relations(g))

    ety = as_text(e.get("etymology_note"))
    if not ety:
        ety = " ".join(t for t in (as_text(x) for x in e.get("etymologies") or []) if t)
    if ety:
        body.append('<div class="ety"><span class="label">词源</span>' + escape(ety) + "</div>")

    notes = [as_text(n) for n in e.get("study_notes") or []]
    notes = [n for n in notes if n]
    if notes:
        body.append(
            '<div class="notes"><span class="label">学习提示</span><ul>'
            + "".join("<li>" + escape(n) + "</li>" for n in notes)
            + "</ul></div>"
        )

    # Index: headword first, inflected forms at lower priority so the lemma wins.
    idx = [index(headword, headword)]
    norm = as_text(e.get("normalized_headword"))
    if norm and norm != headword:
        idx.append(index(norm, headword, 2))
    seen_forms = {headword.lower(), norm.lower()}
    for g in e.get("pos_groups") or []:
        for f in g.get("forms") or []:
            t = as_text(f)
            if is_word(t) and t.lower() not in seen_forms:
                seen_forms.add(t.lower())
                idx.append(index(t, f"{t} → {headword}", 2))

    return (
        f"<d:entry id={quoteattr(ident)} d:title={quoteattr(headword)}>"
        + "".join(idx)
        + "".join(x for x in body if x)
        + "</d:entry>\n"
    )


def render_front_matter(source_tag: str) -> str:
    link = "https://github.com/ahpxex/open-dictionary"
    cc = "https://creativecommons.org/licenses/by-sa/4.0/"
    rows = [
        f'<h1 class="hw">{escape(FRONT_MATTER_TITLE)}</h1>',
        el("div", f"数据版本 {source_tag}" if source_tag else "", "summary"),
        '<div class="notes"><span class="label">来源</span><ul>',
        f'<li>词条数据由 <a href="{link}">ahpxex/open-dictionary</a> 生成，'
        "以 Wiktextract 快照为源，经词频筛选与 LLM 结构化生成。</li>",
        "<li>原始内容 © Wiktionary 贡献者。</li>",
        f'<li>词典数据以 <a href="{cc}">CC BY-SA 4.0</a> 授权；'
        "再分发或二次加工须以相同许可发布并保留署名。</li>",
        "<li>转换脚本 MIT 授权。Dictionary Development Kit 为 Apple 所有，"
        "仅用于构建，未随本词典分发。</li>",
        "</ul></div>",
    ]
    return (
        f'<d:entry id="{FRONT_MATTER_ID}" d:title={quoteattr(FRONT_MATTER_TITLE)}>'
        + index(FRONT_MATTER_TITLE, FRONT_MATTER_TITLE)
        + "".join(r for r in rows if r)
        + "</d:entry>\n"
    )


# --- main ------------------------------------------------------------------


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("input", help="distribution.jsonl or distribution.jsonl.gz ('-' for stdin)")
    ap.add_argument("-o", "--output", default="OpenDictionary.xml")
    ap.add_argument("--limit", type=int, default=0, help="only convert the first N entries (test builds)")
    ap.add_argument(
        "--min-priority",
        choices=("core", "common", "rare"),
        default="rare",
        help="lowest sense priority to include (default: rare = everything)",
    )
    ap.add_argument("--source-tag", default="", help="upstream release tag, shown on the front matter page")
    ap.add_argument("--no-front-matter", action="store_true", help="omit the attribution front matter entry")
    ap.add_argument("--inspect", action="store_true", help="dump the first entry's raw JSON and exit")
    args = ap.parse_args()

    if args.inspect:
        with open_maybe_gzip(args.input) as fh:
            for line in fh:
                line = line.strip()
                if line:
                    print(json.dumps(json.loads(line), ensure_ascii=False, indent=2))
                    return 0
        print("empty input", file=sys.stderr)
        return 1

    min_priority = PRIORITY_ORDER[args.min_priority]
    seen_ids: set[str] = set()
    written = read = skipped = 0

    with open_maybe_gzip(args.input) as fh, open(args.output, "w", encoding="utf-8") as out:
        out.write('<?xml version="1.0" encoding="UTF-8"?>\n')
        out.write(NS + "\n")
        if not args.no_front_matter:
            out.write(render_front_matter(args.source_tag))
            seen_ids.add(FRONT_MATTER_ID)
        for line in fh:
            line = line.strip()
            if not line:
                continue
            read += 1
            try:
                e = json.loads(line)
            except json.JSONDecodeError:
                skipped += 1
                continue
            ident = make_id(as_text(e.get("entry_id")) or as_text(e.get("headword")), seen_ids)
            xml = render_entry(e, ident, min_priority)
            if xml:
                out.write(xml)
                written += 1
            else:
                skipped += 1
            if args.limit and written >= args.limit:
                break
            if written and written % 10000 == 0:
                print(f"  … {written} entries", file=sys.stderr)
        out.write("</d:dictionary>\n")

    print(
        f"read={read} written={written} skipped={skipped} "
        f"stripped_control_chars={stripped_chars} -> {args.output}",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
