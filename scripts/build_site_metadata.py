#!/usr/bin/env python3
"""Generate and validate machine-readable metadata for self-as-an-end.net.

The site intentionally keeps its complete publication catalogue on one page.
This script treats papers.json as the catalogue source of truth and keeps each
paper's head metadata plus sitemap.xml synchronized with that catalogue.
"""

from __future__ import annotations

import argparse
import hashlib
import html
import json
import re
import subprocess
import sys
from datetime import date
from pathlib import Path
from typing import Any
from xml.etree import ElementTree as ET


ROOT = Path(__file__).resolve().parents[1]
BASE_URL = "https://self-as-an-end.net"
AUTHOR_NAME = "Han Qin"
AUTHOR_ALTERNATE_NAME = "秦汉"
AUTHOR_ORCID = "https://orcid.org/0009-0009-9583-0018"
METADATA_VERSION = "1"
START_MARKER = "<!-- SAE:machine-metadata:start -->"
END_MARKER = "<!-- SAE:machine-metadata:end -->"
STATIC_URLS = ["/", "/guide.html", "/framework.html", "/about.html", "/endacc.html"]
EXTRA_PAPERS = [
    {
        "num": "FS",
        "href": "papers/fixed-selected.html",
        "title": "Fixed and Selected: Four Essays on Higher-Order Structural Constraints",
        "doi": "",
        "subtitle": "固与选：高阶结构对低阶自由度的封闭",
        "lang": "EN / ZH",
    }
]

META_NAMES = {
    "description",
    "author",
    "sae:content_hash",
    "sae:metadata_version",
    "citation_title",
    "citation_author",
    "citation_publication_date",
    "citation_doi",
    "citation_abstract_html_url",
    "citation_keywords",
}
OG_PROPERTIES = {"og:type", "og:title", "og:description", "og:url"}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--write", action="store_true", help="update paper metadata and sitemap.xml")
    mode.add_argument("--check", action="store_true", help="validate generated files without editing")
    return parser.parse_args()


def load_catalogue() -> list[dict[str, Any]]:
    data = json.loads((ROOT / "papers.json").read_text(encoding="utf-8"))
    if not isinstance(data, list):
        raise ValueError("papers.json must contain a JSON array")

    # Some works intentionally appear in more than one section of the homepage.
    # The first entry contains the fuller bibliographic title in those cases.
    unique: dict[str, dict[str, Any]] = {}
    for item in data:
        href = str(item.get("href", ""))
        if href.startswith("papers/") and href.endswith(".html"):
            unique.setdefault(href, item)
    for item in EXTRA_PAPERS:
        unique.setdefault(item["href"], item)
    return list(unique.values())


def attribute(tag: str, name: str) -> str | None:
    match = re.search(rf"\b{re.escape(name)}\s*=\s*([\"'])(.*?)\1", tag, re.I | re.S)
    return html.unescape(match.group(2)).strip() if match else None


def existing_meta(source: str, name: str) -> str | None:
    for tag in re.findall(r"<meta\b[^>]*>", source, re.I | re.S):
        if (attribute(tag, "name") or "").lower() == name.lower():
            return attribute(tag, "content")
    return None


def existing_json_ld(source: str) -> list[dict[str, Any]]:
    objects: list[dict[str, Any]] = []
    pattern = r"<script\b[^>]*type\s*=\s*([\"'])application/ld\+json\1[^>]*>(.*?)</script>"
    for match in re.finditer(pattern, source, re.I | re.S):
        try:
            value = json.loads(match.group(2))
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            objects.append(value)
        elif isinstance(value, list):
            objects.extend(item for item in value if isinstance(item, dict))
    return objects


def first_json_value(objects: list[dict[str, Any]], key: str) -> Any:
    for item in objects:
        value = item.get(key)
        if value:
            return value
    return None


def plain_text(fragment: str) -> str:
    fragment = re.sub(r"<(script|style)\b.*?</\1>", " ", fragment, flags=re.I | re.S)
    fragment = re.sub(r"<br\s*/?>", " ", fragment, flags=re.I)
    fragment = re.sub(r"<[^>]+>", " ", fragment)
    fragment = html.unescape(fragment)
    fragment = fragment.replace("**", "").replace("__", "")
    return re.sub(r"\s+", " ", fragment).strip()


def extract_abstract(source: str) -> str | None:
    candidates: list[str] = []
    patterns = [
        r"<(?:div|section)\b[^>]*class\s*=\s*([\"'])[^\"']*\babstract(?:-box)?\b[^\"']*\1[^>]*>(.*?)</(?:div|section)>",
        # Handles an abstract box whose label is a nested <div> before the
        # actual paragraph (the generic container pattern stops at that label).
        r"<(?:div|section)\b[^>]*class\s*=\s*([\"'])[^\"']*\babstract(?:-box)?\b[^\"']*\1[^>]*>.*?<p\b[^>]*>(.*?)</p>",
        r"<h[1-4]\b[^>]*>\s*Abstract\s*</h[1-4]>(.*?)(?=<h[1-4]\b|</article>|</main>)",
    ]
    for pattern in patterns:
        match = re.search(pattern, source, re.I | re.S)
        if match:
            candidates.append(match.group(match.lastindex or 1))

    for candidate in candidates:
        paragraphs = re.findall(r"<p\b[^>]*>(.*?)</p>", candidate, re.I | re.S)
        pieces: list[str] = []
        for paragraph in paragraphs:
            text = plain_text(paragraph)
            if re.match(r"^(keywords?|关键词)\s*[:：]", text, re.I):
                break
            if text and text != "---":
                pieces.append(text)
        value = " ".join(pieces) if pieces else plain_text(candidate)
        value = re.split(r"\s+(?:Keywords?|关键词)\s*[:：]", value, maxsplit=1, flags=re.I)[0].strip()
        if len(value) >= 40:
            return value[:6000]
    return None


def truncate_words(value: str, limit: int = 220) -> str:
    value = re.sub(r"\s+", " ", value).strip()
    if len(value) <= limit:
        return value
    clipped = value[: limit + 1]
    boundary = max(clipped.rfind(" "), clipped.rfind("。"), clipped.rfind("，"), clipped.rfind(";"))
    if boundary >= int(limit * 0.65):
        clipped = clipped[:boundary]
    else:
        clipped = clipped[:limit]
    return clipped.rstrip(" ,;，。") + "…"


def remove_managed_metadata(source: str) -> str:
    source = re.sub(
        rf"\s*{re.escape(START_MARKER)}.*?{re.escape(END_MARKER)}\s*",
        "\n",
        source,
        flags=re.S,
    )

    def keep_meta(match: re.Match[str]) -> str:
        tag = match.group(0)
        name = (attribute(tag, "name") or "").lower()
        prop = (attribute(tag, "property") or "").lower()
        return "" if name in META_NAMES or prop in OG_PROPERTIES else tag

    source = re.sub(r"<meta\b[^>]*>\s*", keep_meta, source, flags=re.I | re.S)
    source = re.sub(
        r"<link\b(?=[^>]*\brel\s*=\s*([\"'])canonical\1)[^>]*>\s*",
        "",
        source,
        flags=re.I | re.S,
    )
    source = re.sub(
        r"<script\b[^>]*type\s*=\s*([\"'])application/ld\+json\1[^>]*>.*?</script>\s*",
        "",
        source,
        flags=re.I | re.S,
    )
    return source


def git_date(path: Path, oldest: bool = False) -> str | None:
    relative = path.relative_to(ROOT).as_posix()
    command = ["git", "log", "--follow", "--format=%cs", "--", relative]
    result = subprocess.run(command, cwd=ROOT, text=True, capture_output=True, check=False)
    dates = [line.strip() for line in result.stdout.splitlines() if line.strip()]
    if not dates:
        return None
    return dates[-1] if oldest else dates[0]


def normalize_date(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    value = value.strip().replace("/", "-")
    match = re.match(r"^(\d{4})(?:-(\d{1,2})(?:-(\d{1,2}))?)?", value)
    if not match:
        return None
    year, month, day = match.groups()
    if not month:
        return year
    if not day:
        return f"{year}-{int(month):02d}"
    return f"{year}-{int(month):02d}-{int(day):02d}"


def language_codes(value: Any) -> list[str]:
    text = str(value or "").upper()
    codes: list[str] = []
    if "EN" in text:
        codes.append("en")
    if "ZH" in text:
        codes.append("zh-Hans")
    return codes or ["en", "zh-Hans"]


def previous_metadata(source: str) -> dict[str, Any]:
    objects = existing_json_ld(source)
    return {
        "title": existing_meta(source, "citation_title") or first_json_value(objects, "headline"),
        "description": existing_meta(source, "description"),
        "abstract": first_json_value(objects, "abstract"),
        "datePublished": existing_meta(source, "citation_publication_date")
        or first_json_value(objects, "datePublished"),
        "dateModified": first_json_value(objects, "dateModified"),
        "doi": existing_meta(source, "citation_doi"),
        "keywords": existing_meta(source, "keywords") or first_json_value(objects, "keywords"),
        "contentHash": existing_meta(source, "sae:content_hash"),
        "metadataVersion": existing_meta(source, "sae:metadata_version"),
        "license": first_json_value(objects, "license"),
    }


def metadata_for(item: dict[str, Any], source: str, path: Path) -> tuple[dict[str, Any], str]:
    previous = previous_metadata(source)
    stripped = remove_managed_metadata(source)
    # Hash only the document body. Head formatting and regenerated machine
    # metadata must not make a second run look like a content revision.
    body_match = re.search(r"<body\b.*", stripped, re.I | re.S)
    hash_source = body_match.group(0) if body_match else stripped
    content_hash = hashlib.sha256(hash_source.encode("utf-8")).hexdigest()

    title = str(previous["title"] or item.get("title") or path.stem).strip()
    subtitle = str(item.get("subtitle") or "").strip()
    alternative_title = subtitle.split(" — ", 1)[0].strip() if subtitle else ""
    if len(alternative_title) > 240 or alternative_title == title:
        alternative_title = ""

    abstract = (
        extract_abstract(source)
        or str(previous["abstract"] or "")
        or str(previous["description"] or "")
        or subtitle
        or title
    )
    description_source = abstract
    description = truncate_words(description_source)
    doi = str(previous["doi"] or item.get("doi") or "").strip()

    published = normalize_date(previous["datePublished"]) or git_date(path, oldest=True) or str(date.today().year)
    modified = normalize_date(previous["dateModified"]) or git_date(path) or date.today().isoformat()
    if previous["contentHash"] != content_hash or previous["metadataVersion"] != METADATA_VERSION:
        modified = date.today().isoformat()

    keyword_value = previous["keywords"]
    if isinstance(keyword_value, list):
        keywords = [str(value).strip() for value in keyword_value if str(value).strip()]
    elif keyword_value:
        keywords = [value.strip() for value in re.split(r"[,;]", str(keyword_value)) if value.strip()]
    else:
        keywords = ["Self-as-an-End", "SAE", "Han Qin", "秦汉"]

    canonical = f"{BASE_URL}/{item['href']}"
    license_url = previous["license"]
    if not license_url and re.search(r"CC BY 4\.0|creativecommons\.org/licenses/by/4\.0", source, re.I):
        license_url = "https://creativecommons.org/licenses/by/4.0/"

    data: dict[str, Any] = {
        "title": title,
        "alternativeTitle": alternative_title,
        "abstract": abstract,
        "description": description,
        "doi": doi,
        "published": published,
        "modified": modified,
        "keywords": keywords,
        "canonical": canonical,
        "languages": language_codes(item.get("lang")),
        "contentHash": content_hash,
        "license": license_url,
    }
    return data, stripped


def json_ld(data: dict[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = {
        "@context": "https://schema.org",
        "@type": "ScholarlyArticle",
        "headline": data["title"],
        "description": data["description"],
        "abstract": data["abstract"],
        "author": {
            "@type": "Person",
            "name": AUTHOR_NAME,
            "alternateName": AUTHOR_ALTERNATE_NAME,
            "sameAs": AUTHOR_ORCID,
        },
        "datePublished": data["published"],
        "dateModified": data["modified"],
        "url": data["canonical"],
        "mainEntityOfPage": data["canonical"],
        "isPartOf": {"@type": "CreativeWorkSeries", "name": "Self-as-an-End Corpus", "url": BASE_URL},
        "keywords": data["keywords"],
        "inLanguage": data["languages"],
    }
    if data["alternativeTitle"]:
        result["alternativeHeadline"] = data["alternativeTitle"]
    if data["doi"]:
        result["identifier"] = {
            "@type": "PropertyValue",
            "propertyID": "DOI",
            "value": data["doi"],
        }
        result["sameAs"] = f"https://doi.org/{data['doi']}"
        result["publisher"] = {"@type": "Organization", "name": "Zenodo", "url": "https://zenodo.org"}
    if data["license"]:
        result["license"] = data["license"]
    return result


def escape_attr(value: Any) -> str:
    return html.escape(str(value), quote=True)


def metadata_block(data: dict[str, Any]) -> str:
    lines = [
        f"  {START_MARKER}",
        f'  <meta name="sae:metadata_version" content="{METADATA_VERSION}">',
        f'  <meta name="sae:content_hash" content="{data["contentHash"]}">',
        f'  <meta name="description" content="{escape_attr(data["description"])}">',
        f'  <meta name="author" content="{AUTHOR_NAME} ({AUTHOR_ALTERNATE_NAME})">',
        '  <meta property="og:type" content="article">',
        f'  <meta property="og:title" content="{escape_attr(data["title"])}">',
        f'  <meta property="og:description" content="{escape_attr(data["description"])}">',
        f'  <meta property="og:url" content="{data["canonical"]}">',
        f'  <link rel="canonical" href="{data["canonical"]}">',
        f'  <meta name="citation_title" content="{escape_attr(data["title"])}">',
        '  <meta name="citation_author" content="Qin, Han">',
        f'  <meta name="citation_publication_date" content="{data["published"]}">',
    ]
    if data["doi"]:
        lines.append(f'  <meta name="citation_doi" content="{escape_attr(data["doi"])}">')
    lines.extend(
        [
            f'  <meta name="citation_abstract_html_url" content="{data["canonical"]}">',
            f'  <meta name="citation_keywords" content="{escape_attr("; ".join(data["keywords"]))}">',
            '  <script type="application/ld+json">',
            "  " + json.dumps(json_ld(data), ensure_ascii=False, indent=2).replace("\n", "\n  "),
            "  </script>",
            f"  {END_MARKER}",
        ]
    )
    return "\n".join(lines)


def render_paper(item: dict[str, Any], source: str, path: Path) -> tuple[str, dict[str, Any]]:
    data, stripped = metadata_for(item, source, path)
    if not re.search(r"</head\s*>", stripped, re.I):
        raise ValueError(f"{path.relative_to(ROOT)} has no closing </head>")
    replacement = "\n" + metadata_block(data) + "\n</head>"
    rendered = re.sub(r"\s*</head\s*>", lambda _match: replacement, stripped, count=1, flags=re.I)
    return rendered, data


def static_lastmod(relative_url: str) -> str:
    filename = "index.html" if relative_url == "/" else relative_url.lstrip("/")
    return git_date(ROOT / filename) or date.today().isoformat()


def render_sitemap(catalogue: list[dict[str, Any]], paper_data: dict[str, dict[str, Any]]) -> str:
    ET.register_namespace("", "http://www.sitemaps.org/schemas/sitemap/0.9")
    namespace = "{http://www.sitemaps.org/schemas/sitemap/0.9}"
    root = ET.Element(namespace + "urlset")
    for relative_url in STATIC_URLS:
        url = ET.SubElement(root, namespace + "url")
        ET.SubElement(url, namespace + "loc").text = BASE_URL + relative_url
        ET.SubElement(url, namespace + "lastmod").text = static_lastmod(relative_url)
    for item in catalogue:
        href = item["href"]
        url = ET.SubElement(root, namespace + "url")
        ET.SubElement(url, namespace + "loc").text = f"{BASE_URL}/{href}"
        ET.SubElement(url, namespace + "lastmod").text = paper_data[href]["modified"]
    ET.indent(root, space="  ")
    return '<?xml version="1.0" encoding="UTF-8"?>\n' + ET.tostring(root, encoding="unicode") + "\n"


def validate(catalogue: list[dict[str, Any]]) -> list[str]:
    errors: list[str] = []
    expected_urls = {f"{BASE_URL}/{item['href']}" for item in catalogue}

    for item in catalogue:
        path = ROOT / item["href"]
        if not path.is_file():
            errors.append(f"missing paper file: {item['href']}")
            continue
        source = path.read_text(encoding="utf-8")
        canonical = f"{BASE_URL}/{item['href']}"
        try:
            rendered, _data = render_paper(item, source, path)
            if rendered != source:
                errors.append(f"{item['href']}: generated metadata is out of date; run with --write")
        except ValueError as exc:
            errors.append(str(exc))
        for required in ("citation_title", "citation_author", "citation_publication_date"):
            if not existing_meta(source, required):
                errors.append(f"{item['href']}: missing {required}")
        if existing_meta(source, "citation_abstract_html_url") != canonical:
            errors.append(f"{item['href']}: citation URL does not match canonical URL")
        if not re.search(rf"<link\b[^>]*rel=[\"']canonical[\"'][^>]*href=[\"']{re.escape(canonical)}[\"']", source, re.I):
            errors.append(f"{item['href']}: missing or incorrect canonical link")
        objects = existing_json_ld(source)
        scholarly = [value for value in objects if value.get("@type") == "ScholarlyArticle"]
        if len(scholarly) != 1:
            errors.append(f"{item['href']}: expected exactly one valid ScholarlyArticle JSON-LD object")
        elif scholarly[0].get("url") != canonical:
            errors.append(f"{item['href']}: JSON-LD URL does not match canonical URL")

    try:
        tree = ET.parse(ROOT / "sitemap.xml")
        actual_urls = {element.text or "" for element in tree.getroot().iter() if element.tag.endswith("loc")}
        missing = sorted(expected_urls - actual_urls)
        unexpected_papers = sorted(
            url for url in actual_urls - expected_urls if url.startswith(f"{BASE_URL}/papers/")
        )
        if missing:
            errors.append(f"sitemap.xml is missing {len(missing)} paper URL(s)")
        if unexpected_papers:
            errors.append(f"sitemap.xml contains {len(unexpected_papers)} uncatalogued paper URL(s)")
    except (ET.ParseError, OSError) as exc:
        errors.append(f"invalid sitemap.xml: {exc}")
    return errors


def main() -> int:
    args = parse_args()
    catalogue = load_catalogue()

    if args.write:
        paper_data: dict[str, dict[str, Any]] = {}
        changed = 0
        for item in catalogue:
            path = ROOT / item["href"]
            if not path.is_file():
                raise FileNotFoundError(item["href"])
            source = path.read_text(encoding="utf-8")
            rendered, data = render_paper(item, source, path)
            paper_data[item["href"]] = data
            if rendered != source:
                path.write_text(rendered, encoding="utf-8")
                changed += 1

        sitemap = render_sitemap(catalogue, paper_data)
        sitemap_path = ROOT / "sitemap.xml"
        if sitemap_path.read_text(encoding="utf-8") != sitemap:
            sitemap_path.write_text(sitemap, encoding="utf-8")
        print(f"Updated metadata for {changed} paper page(s); sitemap has {len(catalogue) + len(STATIC_URLS)} URLs.")

    errors = validate(catalogue)
    if errors:
        for error in errors:
            print(f"ERROR: {error}", file=sys.stderr)
        return 1
    print(f"Metadata validation passed for {len(catalogue)} unique paper URLs.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
