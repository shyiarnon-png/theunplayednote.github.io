#!/usr/bin/env python3
"""Inject rich social / structured metadata into every page of the site.

Idempotent: the injected block is fenced by <!-- rich-meta:start --> ... :end,
so re-running after adding new articles rewrites rather than duplicates.

  python3 tools/enrich-meta.py           # write
  python3 tools/enrich-meta.py --dry-run # preview

Existing <title> and <meta name="description"> are treated as the source of
truth and are never rewritten.

Publication dates come from tools/published.json, keyed by the English slug
and shared with that piece's fr/es translations. When a piece is missing from
the registry the date is inherited from the news line it cites, which is the
original article's date rather than this one's. Every piece must end up with
a date: the script refuses to write if any page has none.

Adding a piece: add its English slug and publication date to
tools/published.json, then re-run.
"""

import argparse
import glob
import html
import json
import os
import re
import sys

SITE = "https://theunplayednote.com"
NAME = "The Unplayed Note"
SUBSTACK = "https://theunplayednote.substack.com"
OG_IMAGE = f"{SITE}/og/the-unplayed-note.png"

OG_LOCALE = {"en": "en_US", "fr": "fr_FR", "es": "es_ES", "he": "he_IL"}
LANGS = ("en", "fr", "es", "he")

START = "  <!-- rich-meta:start -->"
END = "  <!-- rich-meta:end -->"
BLOCK_RE = re.compile(re.escape(START) + r".*?" + re.escape(END) + r"\n", re.S)

MONTHS = {m: i for i, m in enumerate(
    ["january", "february", "march", "april", "may", "june", "july",
     "august", "september", "october", "november", "december"], 1)}

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PUBLISHED = os.path.join(ROOT, "tools", "published.json")


def slug_of(url):
    return url.rstrip("/").rsplit("/", 1)[-1] if url else None


def text_of(pattern, source, group=1):
    m = re.search(pattern, source, re.S)
    return re.sub(r"\s+", " ", m.group(group)).strip() if m else None


def paragraphs_in(source, start_class, stop_before=None):
    """Plain-text <p> contents of one block, in document order."""
    pattern = r'class="' + start_class + r'".*?'
    pattern += r"(?=" + stop_before + r")" if stop_before else r"</div>"
    block = re.search(pattern, source, re.S)
    if not block:
        return []
    out = []
    for m in re.finditer(r"<p[^>]*>(.*?)</p>", block.group(0), re.S):
        txt = html.unescape(re.sub(r"<[^>]+>", "", m.group(1)))
        txt = re.sub(r"\s+", " ", txt).strip()
        if txt:
            out.append(txt)
    return out


def article_body(source):
    """The prose an extractor should see: the news excerpt then the essay.

    xscout's `_extract_from_html` tries trafilatura, then schema.org
    `articleBody`, then paragraph density. trafilatura handles this template
    today, but articleBody is the documented fallback and costs one field.
    """
    news = paragraphs_in(source, "reader-news-block", r'<div class="reader-body"')
    body = paragraphs_in(source, "reader-body")
    return "\n\n".join(news + body)


def parse_en_date(source_line):
    """'Times of Israel / JTA - May 28, 2026' -> ('2026-05-28', True).

    Falls back to month ('2026-05', False) or year ('2026', False) precision.
    """
    tail = source_line.rsplit("·", 1)[-1]
    m = re.search(r"([A-Za-z]+)\s+(\d{1,2}),\s*(\d{4})", tail)
    if m and m.group(1).lower() in MONTHS:
        return f"{m.group(3)}-{MONTHS[m.group(1).lower()]:02d}-{int(m.group(2)):02d}", True
    m = re.search(r"([A-Za-z]+)\s+(\d{4})", tail)
    if m and m.group(1).lower() in MONTHS:
        return f"{m.group(2)}-{MONTHS[m.group(1).lower()]:02d}", False
    m = re.search(r"(\d{4})", tail)
    return (m.group(1), False) if m else (None, False)


def jsonld(payload):
    body = json.dumps(payload, ensure_ascii=False, indent=2)
    # A literal '<' inside <script> can terminate the element early.
    body = body.replace("<", "\\u003c")
    return "\n".join("  " + line for line in
                     ['<script type="application/ld+json">'] + body.splitlines() + ["</script>"])


def publisher():
    return {
        "@type": "Organization",
        "name": NAME,
        "url": SITE + "/",
        "logo": {"@type": "ImageObject", "url": OG_IMAGE, "width": 1200, "height": 630},
    }


def read_page(path):
    with open(path, encoding="utf-8") as fh:
        return fh.read()


def write_page(path, source, block, dry_run):
    """Replace or insert the fenced block directly after the description tag."""
    source = BLOCK_RE.sub("", source)
    anchor = re.search(r'^[ \t]*<meta name="description"[^>]*>\n', source, re.M)
    if not anchor:
        raise SystemExit(f"{path}: no <meta name=\"description\"> to anchor to")
    out = source[:anchor.end()] + START + "\n" + block + "\n" + END + "\n" + source[anchor.end():]
    if out == source:
        return False
    if not dry_run:
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(out)
    return True


def common_head(title, desc, url, lang, alternates, og_type):
    """Tags shared by the home page and every article page."""
    lines = [
        f'  <meta name="author" content="{NAME}">',
        '  <meta name="robots" content="index, follow, max-snippet:-1, max-image-preview:large">',
        '  <meta name="theme-color" content="#f7f5f0">',
        f'  <link rel="alternate" type="application/rss+xml" title="{NAME}" href="{SUBSTACK}/feed">',
        '',
        '  <link rel="icon" href="/favicon.ico" sizes="any">',
        '  <link rel="icon" type="image/png" sizes="32x32" href="/icons/favicon-32.png">',
        '  <link rel="icon" type="image/png" sizes="16x16" href="/icons/favicon-16.png">',
        '  <link rel="apple-touch-icon" href="/icons/apple-touch-icon.png">',
        '',
        f'  <meta property="og:type" content="{og_type}">',
        f'  <meta property="og:site_name" content="{NAME}">',
        f'  <meta property="og:title" content="{title}">',
        f'  <meta property="og:description" content="{desc}">',
        f'  <meta property="og:url" content="{url}">',
        f'  <meta property="og:locale" content="{OG_LOCALE[lang]}">',
    ]
    lines += [f'  <meta property="og:locale:alternate" content="{OG_LOCALE[a]}">'
              for a in alternates]
    lines += [
        f'  <meta property="og:image" content="{OG_IMAGE}">',
        '  <meta property="og:image:type" content="image/png">',
        '  <meta property="og:image:width" content="1200">',
        '  <meta property="og:image:height" content="630">',
        f'  <meta property="og:image:alt" content="{NAME}">',
        '',
        '  <meta name="twitter:card" content="summary_large_image">',
        f'  <meta name="twitter:title" content="{title}">',
        f'  <meta name="twitter:description" content="{desc}">',
        f'  <meta name="twitter:image" content="{OG_IMAGE}">',
        f'  <meta name="twitter:image:alt" content="{NAME}">',
    ]
    return lines


def build_article_block(page):
    title, desc = page["title"], page["desc"]
    lines = common_head(title, desc, page["url"], page["lang"], page["alternates"], "article")

    article = [
        '',
        f'  <meta property="article:section" content="{page["tag"]}">',
        f'  <meta property="article:publisher" content="{SUBSTACK}">',
    ]
    if page["date_full"]:
        article.insert(1, f'  <meta property="article:published_time" content="{page["date"]}">')
    lines += article

    ld = {
        "@context": "https://schema.org",
        "@type": "NewsArticle",
        "headline": html.unescape(title),
        "description": html.unescape(desc),
        "url": page["url"],
        "mainEntityOfPage": {"@type": "WebPage", "@id": page["url"]},
        "inLanguage": page["lang"],
        "articleSection": html.unescape(page["tag"]),
        "isAccessibleForFree": True,
        "image": [OG_IMAGE],
        "author": {"@type": "Organization", "name": NAME, "url": SITE + "/"},
        "publisher": publisher(),
    }
    # Year-only precision ("2026") is legal ISO 8601 but trips Google's
    # rich-results validator, so it is dropped rather than published.
    if page["date"] and len(page["date"]) >= 7:
        ld["datePublished"] = page["date"]
    if page["citation"]:
        ld["citation"] = html.unescape(page["citation"])
    if page["body"]:
        ld["articleBody"] = page["body"]
        ld["wordCount"] = len(page["body"].split())
    return "\n".join(lines + ["", jsonld(ld)])


def build_home_block(title, desc):
    lines = common_head(title, desc, SITE + "/", "en", ["fr", "es"], "website")
    # The home page ships no canonical of its own; the article pages already have one.
    lines[0:0] = [
        f'  <link rel="canonical" href="{SITE}/">',
        f'  <link rel="alternate" hreflang="x-default" href="{SITE}/">',
    ]
    ld = {
        "@context": "https://schema.org",
        "@graph": [
            {
                "@type": "WebSite",
                "@id": SITE + "/#website",
                "url": SITE + "/",
                "name": NAME,
                "description": html.unescape(desc),
                "inLanguage": ["en", "fr", "es"],
                "publisher": {"@id": SITE + "/#organization"},
            },
            {
                "@type": "Organization",
                "@id": SITE + "/#organization",
                "name": NAME,
                "url": SITE + "/",
                "description": "An independent publication.",
                "logo": {"@type": "ImageObject", "url": OG_IMAGE, "width": 1200, "height": 630},
                "sameAs": [SUBSTACK],
            },
            {
                "@type": "Blog",
                "@id": SITE + "/#blog",
                "url": SITE + "/",
                "name": NAME,
                "description": html.unescape(desc),
                "inLanguage": ["en", "fr", "es"],
                "publisher": {"@id": SITE + "/#organization"},
            },
        ],
    }
    return "\n".join(lines + ["", jsonld(ld)])


def collect(path):
    source = read_page(path)
    lang = path.split(os.sep)[-3]
    raw_title = text_of(r"<title>(.*?)</title>", source)
    title = re.split(r"\s+[—–-]\s+" + re.escape(NAME) + r"\s*$", raw_title)[0]
    desc = text_of(r'<meta name="description" content="(.*?)"\s*>', source)
    canonical = text_of(r'<link rel="canonical" href="(.*?)"', source)
    hreflangs = dict(re.findall(r'<link rel="alternate" hreflang="(\w+)" href="(.*?)"', source))

    source_line = text_of(r'class="reader-source"[^>]*>(.*?)</div>', source) or ""
    parts = [p.strip() for p in source_line.split("&nbsp;&middot;&nbsp;")]
    tag = parts[0] if parts else ""
    citation = parts[1] if len(parts) > 1 else ""

    return {
        "path": path, "lang": lang, "title": title, "desc": desc, "tag": tag,
        "citation": citation, "body": article_body(source),
        "url": canonical or f"{SITE}/{lang}/{path.split(os.sep)[-2]}/",
        "en_url": hreflangs.get("en"),
        "alternates": [l for l in LANGS if l != lang and l in hreflangs],
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    os.chdir(ROOT)

    pages = [collect(p) for p in sorted(glob.glob(os.path.join("*", "*", "index.html")))]

    with open(PUBLISHED, encoding="utf-8") as fh:
        published = json.load(fh)

    # The English edition carries the datable news line; translations inherit
    # whatever their English original resolved to.
    fallback = {page["url"]: parse_en_date(page["citation"])
                for page in pages if page["lang"] == "en"}

    undated = []
    for page in pages:
        en_url = page["en_url"] or page["url"]
        recorded = published.get(slug_of(en_url))
        page["date"], page["date_full"] = (
            (recorded, True) if recorded else fallback.get(en_url, (None, False)))
        if not page["date"]:
            undated.append(page["path"])
        elif not recorded:
            print(f"  note: {page['path']} falls back to the news line date "
                  f"({page['date']}); add {slug_of(en_url)} to published.json",
                  file=sys.stderr)
    if undated:
        raise SystemExit("no date for:\n  " + "\n  ".join(undated))

    changed = []
    for page in pages:
        if write_page(page["path"], read_page(page["path"]),
                      build_article_block(page), args.dry_run):
            changed.append(page["path"])

    home = read_page("index.html")
    home_title = text_of(r"<title>(.*?)</title>", home)
    home_desc = text_of(r'<meta name="description" content="(.*?)"\s*>', home)
    if write_page("index.html", home, build_home_block(home_title, home_desc), args.dry_run):
        changed.append("index.html")

    verb = "would update" if args.dry_run else "updated"
    print(f"{verb} {len(changed)} page(s)")


if __name__ == "__main__":
    main()
