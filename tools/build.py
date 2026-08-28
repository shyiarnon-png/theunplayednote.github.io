#!/usr/bin/env python3
"""Render the whole site from content/*.json.

Each piece is one file in content/ holding every language edition it has.
This script is the only thing that writes the published pages, so a piece
exists in exactly one place and the editions cannot drift apart.

  python3 tools/build.py            # write
  python3 tools/build.py --check    # write nothing, report what would change

--check is the safety net for the migration: it must report zero differences
against the pages that were hand-maintained before this script existed, and
exits 1 if it finds any. It reported 46 of 48 identical on the first clean
run. The other two carried a bare "&" in "R&D" that this script writes as
"&amp;", which is the correct markup and renders the same, so those two
pages were corrected rather than reproduced.
"""

import argparse
import glob
import html
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SITE = "https://theunplayednote.com"
NAME = "The Unplayed Note"

# Display name and writing direction per edition. Order here is the order the
# language nav renders in.
LANGS = {
    "en": {"label": "English", "dir": "ltr"},
    "fr": {"label": "Français", "dir": "ltr"},
    "es": {"label": "Español", "dir": "ltr"},
    "he": {"label": "עברית", "dir": "rtl"},
}


def load_content():
    """Every piece, ordered as the site orders them."""
    pieces = []
    for path in sorted(glob.glob(os.path.join(ROOT, "content", "*.json"))):
        with open(path, encoding="utf-8") as fh:
            piece = json.load(fh)
        piece["path"] = path
        pieces.append(piece)
    pieces.sort(key=lambda p: p["order"])
    return pieces


def attr(value):
    """Escape for a double-quoted HTML attribute value.

    Only the four characters that can break out of one. Python's
    html.escape(quote=True) also rewrites ' as &#x27;, which is safe but
    noisy inside a double-quoted attribute and is not what the pages carry.
    """
    return (value.replace("&", "&amp;").replace("<", "&lt;")
                 .replace(">", "&gt;").replace('"', "&quot;"))


def body(value):
    """Escape for HTML text content, leaving quotes alone as the source does."""
    return html.escape(value, quote=False)


def url_for(lang, slug):
    return f"{SITE}/{lang}/{slug}/"


def paragraphs(text):
    """A news excerpt is one string with blank lines between paragraphs."""
    return [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]


def render_lang_nav(piece, lang):
    out = []
    for other, meta in LANGS.items():
        ed = piece["editions"].get(other)
        if not ed or not ed.get("slug"):
            continue
        active = ' active' if other == lang else ''
        out.append(f'      <a class="lang-btn{active}" '
                   f'href="/{other}/{ed["slug"]}/">{meta["label"]}</a>')
    return "\n".join(out)


def render_article(ed):
    out = [
        f'      <div class="reader-source">{body(ed["tag"])}'
        f' &nbsp;&middot;&nbsp; {body(ed["source"])}</div>',
        f'      <h1 class="reader-title">{body(ed["title"])}</h1>',
        f'      <p class="reader-subtitle">{body(ed["subtitle"])}</p>',
        '      <div class="reader-news-block">',
        f'        <div class="news-source-line">{body(ed["news"]["source"])}</div>',
    ]
    for para in paragraphs(ed["news"]["text"]):
        out.append(f'      <p style="margin-bottom:0.8rem">{body(para)}</p>')
    out += ['      </div>', '      <div class="reader-body">']
    for para in ed["body"]:
        out.append(f'      <p>{body(para)}</p>')
    out.append('      </div>')
    return "\n".join(out)


def render_pager(pieces, piece, lang):
    """Previous and next piece within this language, by publication order.

    The nav lays its two slots out with space-between, so a missing end still
    emits an empty <span> to keep the surviving link on its own side.
    """
    have = [p for p in pieces if p["editions"].get(lang, {}).get("slug")]
    i = have.index(piece)
    slots = []
    if i > 0:
        prev = have[i - 1]["editions"][lang]
        slots.append(f'      <a href="/{lang}/{prev["slug"]}/" '
                     f'class="pager-link pager-prev">&larr; {body(prev["title"])}</a>')
    else:
        slots.append('      <span></span>')
    if i < len(have) - 1:
        nxt = have[i + 1]["editions"][lang]
        slots.append(f'      <a href="/{lang}/{nxt["slug"]}/" '
                     f'class="pager-link pager-next">{body(nxt["title"])} &rarr;</a>')
    else:
        slots.append('      <span></span>')
    return "    <nav class=\"article-pager\">\n" + "\n".join(slots) + "\n    </nav>"


def render_head(meta_block, piece, lang):
    ed = piece["editions"][lang]
    lines = [
        f'  <title>{body(ed["title"])} — {NAME}</title>',
        # The same text as og:description and the JSON-LD. Three
        # descriptions of one page that disagree is worse than one that is
        # short.
        f'  <meta name="description" content="{attr(meta_description(ed["subtitle"]))}">',
        '  <!-- rich-meta:start -->',
        meta_block,
        '  <!-- rich-meta:end -->',
        f'  <link rel="canonical" href="{url_for(lang, ed["slug"])}">',
    ]
    for other in LANGS:
        alt = piece["editions"].get(other)
        if alt and alt.get("slug"):
            lines.append(f'  <link rel="alternate" hreflang="{other}" '
                         f'href="{url_for(other, alt["slug"])}">')
    return "\n".join(lines)


# Google renders roughly 155 to 160 characters of a description before it
# truncates, and a description cut mid-word by the search engine reads worse
# than one the site cut deliberately. Subtitles here run to 233 characters.
DESC_LIMIT = 160

# Sentence end followed by a space. Hebrew uses the same full stop.
SENTENCE_END = re.compile(r"(?<=[.!?])\s+")


def meta_description(subtitle):
    """A description that fits, built from whole sentences where it can.

    The subtitle stays intact on the page. This only governs the meta tag.
    Preferring whole sentences matters because these subtitles are aphoristic
    and a cut one loses the turn it was built around.
    """
    text = " ".join(subtitle.split())
    if len(text) <= DESC_LIMIT:
        return text

    kept = ""
    for sentence in SENTENCE_END.split(text):
        candidate = (kept + " " + sentence).strip()
        if len(candidate) > DESC_LIMIT:
            break
        kept = candidate
    if kept:
        return kept

    # One sentence, too long by itself. Cut on a word and say so with an
    # ellipsis rather than pretending it ended.
    cut = text[:DESC_LIMIT - 1]
    space = cut.rfind(" ")
    if space > DESC_LIMIT * 0.6:
        cut = cut[:space]
    return cut.rstrip(" ,;:") + "\u2026"


def render_sitemap(pieces):
    """The sitemap, generated rather than maintained.

    It is accurate today because it has been kept by hand. That stops being
    true the first time a piece is published by something other than a human
    editing this file, which is exactly what the portal does.

    lastmod is the piece's published date. The site has no separate revision
    date, and inventing one that moves on every rebuild would train crawlers
    to ignore the field.
    """
    lines = ['<?xml version="1.0" encoding="UTF-8"?>',
             '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"',
             '        xmlns:xhtml="http://www.w3.org/1999/xhtml">',
             '  <url>', f'    <loc>{SITE}/</loc>', '  </url>']

    for piece in pieces:
        published = [l for l in LANGS if piece["editions"].get(l, {}).get("slug")]
        for lang in published:
            lines.append('  <url>')
            lines.append(f'    <loc>{url_for(lang, piece["editions"][lang]["slug"])}</loc>')
            for other in published:
                href = url_for(other, piece["editions"][other]["slug"])
                lines.append(f'    <xhtml:link rel="alternate" hreflang="{other}" '
                             f'href="{href}"/>')
            lines.append(f'    <lastmod>{piece["published"]}</lastmod>')
            lines.append('  </url>')

    lines.append('</urlset>')
    return "\n".join(lines) + "\n"


def render_robots():
    """robots.txt, generated so it cannot fall out of step with the sitemap.

    Everything is allowed. og/ holds the share card images, which are meant
    to be fetched by scrapers rather than indexed as pages, so they are
    disallowed for the general crawler and nothing else is.
    """
    return (
        "User-agent: *\n"
        "Allow: /\n"
        "Disallow: /og/\n"
        "\n"
        f"Sitemap: {SITE}/sitemap.xml\n"
    )


def render_page(template, pieces, piece, lang, ui, meta_block):
    ed = piece["editions"][lang]
    strings = ui[lang]
    lang_attr = f'lang="{lang}"'
    if LANGS[lang]["dir"] == "rtl":
        lang_attr += ' dir="rtl"'
    out = template
    for token, value in (
        ("{{LANG_ATTR}}", lang_attr),
        ("{{HEAD}}", render_head(meta_block, piece, lang)),
        ("{{LANG_NAV}}", render_lang_nav(piece, lang)),
        ("{{ARTICLE}}", render_article(ed)),
        ("{{PAGER}}", render_pager(pieces, piece, lang)),
        ("{{TAGLINE}}", body(strings["tagline"])),
        ("{{BACK_BTN}}", body(strings["backBtn"])),
        ("{{SUBSCRIBE_TEXT}}", body(strings["subscribeText"])),
        ("{{SUBSCRIBE_BTN}}", body(strings["subscribeBtn"])),
    ):
        assert token in out, f"template lost {token}"
        out = out.replace(token, value)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true",
                    help="compare against what is on disk, write nothing")
    args = ap.parse_args()

    sys.path.insert(0, os.path.join(ROOT, "tools"))
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "meta", os.path.join(ROOT, "tools", "enrich-meta.py"))
    meta = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(meta)

    with open(os.path.join(ROOT, "templates", "article.html"), encoding="utf-8") as fh:
        template = fh.read()
    # The page chrome (tagline, back link, subscribe box) is localized, and
    # the home page's script already carries those strings for every edition.
    with open(os.path.join(ROOT, "templates", "ui.json"), encoding="utf-8") as fh:
        ui = json.load(fh)

    pieces = load_content()
    changed, same, missing = [], [], []
    for piece in pieces:
        for lang, ed in piece["editions"].items():
            if not ed.get("slug"):
                continue
            page = {
                "lang": lang,
                "title": ed["title"],
                "desc": meta_description(ed["subtitle"]),
                "tag": ed["tag"],
                "citation": ed["source"],
                "url": url_for(lang, ed["slug"]),
                "date": piece["published"],
                "date_full": True,
                "alternates": [o for o in LANGS if o != lang
                               and piece["editions"].get(o, {}).get("slug")],
                "body": "\n\n".join(paragraphs(ed["news"]["text"]) + ed["body"]),
            }
            out = render_page(template, pieces, piece, lang, ui,
                              meta.build_article_block(page))
            path = os.path.join(ROOT, lang, ed["slug"], "index.html")
            existing = None
            if os.path.exists(path):
                with open(path, encoding="utf-8") as fh:
                    existing = fh.read()
            rel = os.path.relpath(path, ROOT)
            if existing is None:
                missing.append(rel)
            elif existing == out:
                same.append(rel)
            else:
                changed.append((rel, existing, out))
            if not args.check:
                os.makedirs(os.path.dirname(path), exist_ok=True)
                with open(path, "w", encoding="utf-8") as fh:
                    fh.write(out)

    for rel, text in (("sitemap.xml", render_sitemap(pieces)),
                      ("robots.txt", render_robots())):
        path = os.path.join(ROOT, rel)
        existing = None
        if os.path.exists(path):
            with open(path, encoding="utf-8") as fh:
                existing = fh.read()
        if existing is None:
            missing.append(rel)
        elif existing == text:
            same.append(rel)
        else:
            changed.append((rel, existing, text))
        if not args.check:
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(text)

    print(f"identical {len(same)}   differs {len(changed)}   new {len(missing)}")
    for rel, old, new in changed[:5]:
        print(f"\n--- {rel}")
        import difflib
        diff = difflib.unified_diff(old.split("\n"), new.split("\n"),
                                    "on disk", "generated", lineterm="", n=1)
        for line in list(diff)[:24]:
            print("   " + line[:150])
    for rel in missing:
        print(f"   new: {rel}")
    return 1 if (args.check and (changed or missing)) else 0


if __name__ == "__main__":
    sys.exit(main())
