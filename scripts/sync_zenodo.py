#!/usr/bin/env python3
"""Audit and synchronize the SAE corpus with Zenodo.

Public operations:
  * map every catalogue page to its Zenodo concept and latest version;
  * save daily views/downloads history;
  * replace SAE version DOIs on the website with concept DOIs.

Authenticated operation:
  * prepend the standard self-as-an-end.net line to the latest published
    version's Zenodo description when it is missing.

The remote operation is deliberately opt-in and reads the access token only
from ZENODO_ACCESS_TOKEN. Tokens are never written to disk or placed in URLs.
"""

from __future__ import annotations

import argparse
import csv
import difflib
import html
import json
import os
import re
import subprocess
import sys
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
API_ROOT = "https://zenodo.org/api"
AUTHOR_ORCID = "0009-0009-9583-0018"
USER_AGENT = "self-as-an-end Zenodo maintenance/1.0"
DOI_RE = re.compile(r"10\.5281/zenodo\.\d+", re.I)
DESCRIPTION_PREFIX = "full bilingual text and framework available at self-as-an-end.net"
DESCRIPTION_BANNER = (
    '<p><strong>Full bilingual text and framework available at&nbsp;'
    '<a href="https://self-as-an-end.net/">self-as-an-end.net</a></strong></p>'
)

# Four DOI strings in article bibliographies resolve to unrelated authors'
# deposits. The surrounding citation identifies the intended SAE work.
KNOWN_DOI_CORRECTIONS = {
    "10.5281/zenodo.18842458": "10.5281/zenodo.18914682",  # ZFCρ Paper I
    "10.5281/zenodo.18866551": "10.5281/zenodo.19381111",  # ZFCρ Paper 50
    "10.5281/zenodo.19023418": "10.5281/zenodo.19024385",  # ZFCρ Paper XVIII
    "10.5281/zenodo.20307821": "10.5281/zenodo.20340595",  # SAE QM Paper 3
    "10.5281/zenodo.21466722": "10.5281/zenodo.21538494",  # SAE Mathematics Paper 5
}

HISTORY_FIELDS = [
    "snapshot_date",
    "captured_at",
    "href",
    "title",
    "concept_doi",
    "latest_version_doi",
    "latest_record_id",
    "views",
    "unique_views",
    "downloads",
    "unique_downloads",
    "version_views",
    "version_unique_views",
    "version_downloads",
    "version_unique_downloads",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--audit", action="store_true", help="print the current Zenodo/site audit")
    parser.add_argument(
        "--snapshot",
        action="store_true",
        help="write data/zenodo-current.json, data/zenodo-audit.json, and the daily statistics row set",
    )
    parser.add_argument(
        "--update-site-dois",
        action="store_true",
        help="replace SAE version DOIs with concept DOIs and rebuild generated page metadata",
    )
    parser.add_argument(
        "--apply-descriptions",
        action="store_true",
        help="update and republish missing Zenodo description banners (requires token and confirmation flag)",
    )
    parser.add_argument(
        "--confirm-remote-write",
        action="store_true",
        help="required safety acknowledgement for --apply-descriptions",
    )
    parser.add_argument(
        "--records-file",
        type=Path,
        help="read a cached JSON array of Zenodo records instead of fetching the public API",
    )
    parser.add_argument("--delay", type=float, default=0.35, help="seconds between Zenodo requests")
    args = parser.parse_args()
    if not any((args.audit, args.snapshot, args.update_site_dois, args.apply_descriptions)):
        parser.error("choose at least one action")
    if args.apply_descriptions and not args.confirm_remote_write:
        parser.error("--apply-descriptions also requires --confirm-remote-write")
    return args


def normalize_doi(value: Any) -> str:
    text = str(value or "").strip().lower()
    text = re.sub(r"^https?://(?:dx\.)?doi\.org/", "", text)
    return text.rstrip("/.,; ")


def total_value(value: Any) -> int:
    if isinstance(value, dict):
        value = value.get("value", 0)
    return int(value or 0)


def request_json(
    url: str,
    *,
    method: str = "GET",
    token: str = "",
    payload: dict[str, Any] | None = None,
    attempts: int = 4,
) -> Any:
    headers = {"Accept": "application/json", "User-Agent": USER_AGENT}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    body = None
    if payload is not None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        headers["Content-Type"] = "application/json"

    for attempt in range(attempts):
        request = urllib.request.Request(url, data=body, headers=headers, method=method)
        try:
            with urllib.request.urlopen(request, timeout=90) as response:
                raw = response.read()
                return json.loads(raw) if raw else None
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")[:1200]
            if exc.code not in {409, 429, 500, 502, 503, 504} or attempt + 1 == attempts:
                raise RuntimeError(f"Zenodo {method} {url} failed ({exc.code}): {detail}") from exc
        except (TimeoutError, urllib.error.URLError) as exc:
            if attempt + 1 == attempts:
                raise RuntimeError(f"Zenodo {method} {url} failed: {exc}") from exc
        time.sleep(1.5 * (attempt + 1))
    raise AssertionError("unreachable")


def fetch_all_versions(delay: float) -> list[dict[str, Any]]:
    query = f'creators.orcid:"{AUTHOR_ORCID}"'
    records: list[dict[str, Any]] = []
    page = 1
    while True:
        params = urllib.parse.urlencode(
            {
                "q": query,
                "size": 25,  # Zenodo's anonymous-request maximum.
                "page": page,
                "all_versions": "true",
                "sort": "mostrecent",
            }
        )
        data = request_json(f"{API_ROOT}/records/?{params}")
        hits = data.get("hits", {}).get("hits", [])
        records.extend(hits)
        total = total_value(data.get("hits", {}).get("total", 0))
        print(f"Fetched Zenodo page {page}: {len(records)}/{total}", flush=True)
        if not hits or len(records) >= total:
            break
        page += 1
        time.sleep(delay)
    return records


def load_records(args: argparse.Namespace) -> list[dict[str, Any]]:
    if args.records_file:
        value = json.loads(args.records_file.read_text(encoding="utf-8"))
        if isinstance(value, dict):
            value = value.get("records") or value.get("hits", {}).get("hits")
        if not isinstance(value, list):
            raise ValueError("--records-file must contain a JSON array of Zenodo records")
        return value
    return fetch_all_versions(args.delay)


def normalize_title(value: str) -> str:
    value = html.unescape(re.sub(r"<[^>]+>", " ", value or ""))
    value = unicodedata.normalize("NFKC", value).casefold()
    return re.sub(r"[^a-z0-9\u3400-\u9fff]+", " ", value).strip()


def first_description_text(description: str) -> str:
    match = re.search(r"<p\b[^>]*>(.*?)</p>", description or "", re.I | re.S)
    fragment = match.group(1) if match else (description or "").split("\n", 1)[0]
    fragment = html.unescape(re.sub(r"<[^>]+>", " ", fragment))
    return re.sub(r"\s+", " ", fragment).strip().casefold()


def has_description_banner(description: str) -> bool:
    return first_description_text(description).startswith(DESCRIPTION_PREFIX)


def catalogue_entries() -> list[dict[str, Any]]:
    data = json.loads((ROOT / "papers.json").read_text(encoding="utf-8"))
    return [item for item in data if str(item.get("href", "")).startswith("papers/")]


def index_records(
    records: list[dict[str, Any]],
) -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]], dict[str, list[dict[str, Any]]]]:
    versions_by_doi: dict[str, dict[str, Any]] = {}
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for record in records:
        doi = normalize_doi(record.get("doi"))
        concept = normalize_doi(record.get("conceptdoi"))
        if doi:
            versions_by_doi[doi] = record
        if concept:
            groups[concept].append(record)

    latest_by_concept = {
        concept: max(values, key=lambda record: int(record.get("id") or record.get("recid") or 0))
        for concept, values in groups.items()
    }
    return versions_by_doi, latest_by_concept, groups


def match_pages(
    entries: list[dict[str, Any]], records: list[dict[str, Any]]
) -> tuple[dict[str, dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    versions_by_doi, latest_by_concept, _groups = index_records(records)
    entries_by_href: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for entry in entries:
        entries_by_href[str(entry["href"])].append(entry)

    mapping: dict[str, dict[str, Any]] = {}
    unmatched: list[dict[str, Any]] = []
    ambiguous: list[dict[str, Any]] = []

    for href, page_entries in entries_by_href.items():
        title = str(page_entries[0].get("title") or "").strip()
        current_dois = sorted({normalize_doi(item.get("doi")) for item in page_entries if normalize_doi(item.get("doi"))})
        concepts: set[str] = set()
        for doi in current_dois:
            corrected_doi = normalize_doi(KNOWN_DOI_CORRECTIONS.get(doi, doi))
            if corrected_doi in latest_by_concept:
                concepts.add(corrected_doi)
            elif corrected_doi in versions_by_doi:
                concepts.add(normalize_doi(versions_by_doi[corrected_doi].get("conceptdoi")))

        matched_by = "doi"
        if not concepts:
            page_title = normalize_title(title)
            prefix_matches = []
            for concept, record in latest_by_concept.items():
                record_title = normalize_title(str(record.get("metadata", {}).get("title") or record.get("title") or ""))
                if record_title == page_title or record_title.startswith(page_title + " "):
                    prefix_matches.append(concept)
            if len(prefix_matches) == 1:
                concepts.add(prefix_matches[0])
                matched_by = "title-prefix"

        if len(concepts) != 1:
            candidates = []
            page_title = normalize_title(title)
            for concept, record in latest_by_concept.items():
                record_title = normalize_title(str(record.get("metadata", {}).get("title") or record.get("title") or ""))
                score = difflib.SequenceMatcher(None, page_title, record_title).ratio()
                if score >= 0.45:
                    candidates.append(
                        {
                            "score": round(score, 4),
                            "concept_doi": concept,
                            "title": record.get("metadata", {}).get("title") or record.get("title"),
                        }
                    )
            problem = {
                "href": href,
                "title": title,
                "current_dois": current_dois,
                "concept_candidates": sorted(concepts),
                "title_candidates": sorted(candidates, key=lambda item: item["score"], reverse=True)[:5],
            }
            (unmatched if not concepts else ambiguous).append(problem)
            continue

        concept = concepts.pop()
        latest = latest_by_concept[concept]
        mapping[href] = {
            "href": href,
            "title": title,
            "catalogue_entries": len(page_entries),
            "current_dois": current_dois,
            "concept_doi": concept,
            "latest_version_doi": normalize_doi(latest.get("doi")),
            "latest_record_id": int(latest.get("id") or latest.get("recid")),
            "matched_by": matched_by,
            "record": latest,
        }

    return mapping, unmatched, ambiguous


def audit(records: list[dict[str, Any]], entries: list[dict[str, Any]]) -> dict[str, Any]:
    mapping, unmatched, ambiguous = match_pages(entries, records)
    concepts = [item["concept_doi"] for item in mapping.values()]
    duplicate_concepts = sorted({value for value in concepts if concepts.count(value) > 1})
    missing_banners = [
        {
            "href": item["href"],
            "concept_doi": item["concept_doi"],
            "latest_version_doi": item["latest_version_doi"],
            "latest_record_id": item["latest_record_id"],
            "title": item["record"].get("metadata", {}).get("title") or item["title"],
        }
        for item in mapping.values()
        if not has_description_banner(str(item["record"].get("metadata", {}).get("description") or ""))
    ]
    site_doi_changes = sum(
        1
        for item in mapping.values()
        for doi in item["current_dois"]
        if doi != item["concept_doi"]
    )
    return {
        "record_versions": len(records),
        "zenodo_concepts": len({normalize_doi(record.get("conceptdoi")) for record in records}),
        "catalogue_entries": len(entries),
        "unique_pages": len({str(item.get("href")) for item in entries}),
        "mapped_pages": len(mapping),
        "unmatched_pages": unmatched,
        "ambiguous_pages": ambiguous,
        "duplicate_concepts": duplicate_concepts,
        "description_banners_present": len(mapping) - len(missing_banners),
        "description_banners_missing": len(missing_banners),
        "missing_description_records": missing_banners,
        "catalogue_dois_needing_concept_update": site_doi_changes,
        "mapping": mapping,
    }


def public_record(item: dict[str, Any]) -> dict[str, Any]:
    record = item["record"]
    metadata = record.get("metadata", {})
    stats = record.get("stats", {})
    return {
        "href": item["href"],
        "catalogue_title": item["title"],
        "zenodo_title": metadata.get("title") or record.get("title"),
        "concept_doi": item["concept_doi"],
        "latest_version_doi": item["latest_version_doi"],
        "latest_record_id": item["latest_record_id"],
        "matched_by": item["matched_by"],
        "description_has_banner": has_description_banner(str(metadata.get("description") or "")),
        "stats": {key: int(value or 0) for key, value in stats.items()},
    }


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def markdown_cell(value: Any) -> str:
    return str(value or "").replace("|", "\\|").replace("\n", " ")


def write_stats_summary(
    path: Path,
    captured_at: str,
    rows: list[dict[str, Any]],
    previous_by_concept: dict[str, dict[str, str]],
) -> None:
    def paper_link(row: dict[str, Any]) -> str:
        return f"[{markdown_cell(row['title'])}](../{row['href']})"

    def ranking(title: str, metric: str) -> list[str]:
        lines = [f"## {title}", "", "| Rank | Paper | Views | Downloads |", "| ---: | --- | ---: | ---: |"]
        for rank, row in enumerate(sorted(rows, key=lambda value: int(value[metric]), reverse=True)[:20], start=1):
            lines.append(f"| {rank} | {paper_link(row)} | {row['views']} | {row['downloads']} |")
        return lines + [""]

    lines = [
        "# Zenodo attention snapshot",
        "",
        f"Captured at `{captured_at}`. Counts are concept-wide Zenodo totals.",
        "",
    ]
    lines.extend(ranking("Most viewed", "views"))
    lines.extend(ranking("Most downloaded", "downloads"))

    if previous_by_concept:
        growth_rows = []
        for row in rows:
            previous = previous_by_concept.get(str(row["concept_doi"]), {})
            growth_rows.append(
                {
                    **row,
                    "views_delta": int(row["views"]) - int(previous.get("views") or 0),
                    "downloads_delta": int(row["downloads"]) - int(previous.get("downloads") or 0),
                }
            )
        lines.extend(
            [
                "## Growth since the previous snapshot",
                "",
                "| Paper | Δ Views | Δ Downloads |",
                "| --- | ---: | ---: |",
            ]
        )
        for row in sorted(
            growth_rows,
            key=lambda value: (value["views_delta"] + value["downloads_delta"], value["views_delta"]),
            reverse=True,
        )[:20]:
            lines.append(f"| {paper_link(row)} | {row['views_delta']:+d} | {row['downloads_delta']:+d} |")
        lines.append("")
    else:
        lines.extend(
            [
                "## Growth since the previous snapshot",
                "",
                "This is the first snapshot; growth rankings will appear after the next capture date.",
                "",
            ]
        )

    path.write_text("\n".join(lines), encoding="utf-8")


def write_snapshot(report: dict[str, Any]) -> None:
    if report["unmatched_pages"] or report["ambiguous_pages"] or report["duplicate_concepts"]:
        raise RuntimeError("cannot write snapshot until page-to-concept mapping errors are resolved")

    captured = datetime.now(timezone.utc).replace(microsecond=0)
    captured_at = captured.isoformat().replace("+00:00", "Z")
    snapshot_date = captured.date().isoformat()
    current = sorted(
        (public_record(item) for item in report["mapping"].values()),
        key=lambda item: item["href"],
    )

    data_dir = ROOT / "data"
    write_json(
        data_dir / "zenodo-current.json",
        {"captured_at": captured_at, "records": current},
    )
    write_json(
        data_dir / "zenodo-audit.json",
        {
            key: value
            for key, value in report.items()
            if key not in {"mapping"}
        }
        | {"captured_at": captured_at},
    )

    history_path = data_dir / "zenodo-stats.csv"
    existing: list[dict[str, str]] = []
    if history_path.exists():
        with history_path.open(encoding="utf-8", newline="") as handle:
            existing = [row for row in csv.DictReader(handle) if row.get("snapshot_date") != snapshot_date]
    previous_date = max((row["snapshot_date"] for row in existing), default="")
    previous_by_concept = {
        row["concept_doi"]: row for row in existing if row.get("snapshot_date") == previous_date
    }

    rows: list[dict[str, Any]] = []
    for item in current:
        stats = item["stats"]
        rows.append(
            {
                "snapshot_date": snapshot_date,
                "captured_at": captured_at,
                "href": item["href"],
                "title": item["catalogue_title"],
                "concept_doi": item["concept_doi"],
                "latest_version_doi": item["latest_version_doi"],
                "latest_record_id": item["latest_record_id"],
                "views": stats.get("views", 0),
                "unique_views": stats.get("unique_views", 0),
                "downloads": stats.get("downloads", 0),
                "unique_downloads": stats.get("unique_downloads", 0),
                "version_views": stats.get("version_views", 0),
                "version_unique_views": stats.get("version_unique_views", 0),
                "version_downloads": stats.get("version_downloads", 0),
                "version_unique_downloads": stats.get("version_unique_downloads", 0),
            }
        )

    all_rows = existing + [{key: str(row.get(key, "")) for key in HISTORY_FIELDS} for row in rows]
    all_rows.sort(key=lambda row: (row["snapshot_date"], row["concept_doi"]))
    history_path.parent.mkdir(parents=True, exist_ok=True)
    with history_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=HISTORY_FIELDS)
        writer.writeheader()
        writer.writerows(all_rows)
    write_stats_summary(data_dir / "zenodo-stats-summary.md", captured_at, rows, previous_by_concept)
    print(f"Saved {len(rows)} Zenodo statistics rows for {snapshot_date}.")


def replacement_map(records: list[dict[str, Any]]) -> dict[str, str]:
    replacements = {
        normalize_doi(record.get("doi")): normalize_doi(record.get("conceptdoi"))
        for record in records
        if normalize_doi(record.get("doi")) and normalize_doi(record.get("conceptdoi"))
    }
    replacements.update({normalize_doi(key): normalize_doi(value) for key, value in KNOWN_DOI_CORRECTIONS.items()})
    return {key: value for key, value in replacements.items() if key != value}


def substitute_dois(source: str, replacements: dict[str, str]) -> tuple[str, int]:
    count = 0

    def replace(match: re.Match[str]) -> str:
        nonlocal count
        old = normalize_doi(match.group(0))
        new = replacements.get(old)
        if not new:
            return match.group(0)
        count += 1
        return new

    return DOI_RE.sub(replace, source), count


def update_site_dois(report: dict[str, Any], records: list[dict[str, Any]]) -> None:
    if report["unmatched_pages"] or report["ambiguous_pages"] or report["duplicate_concepts"]:
        raise RuntimeError("cannot update the site until page-to-concept mapping errors are resolved")

    mapping = report["mapping"]
    catalogue_path = ROOT / "papers.json"
    catalogue = json.loads(catalogue_path.read_text(encoding="utf-8"))
    catalogue_updates = 0
    for item in catalogue:
        href = str(item.get("href") or "")
        if href not in mapping:
            continue
        concept = mapping[href]["concept_doi"]
        if normalize_doi(item.get("doi")) != concept:
            item["doi"] = concept
            catalogue_updates += 1
    catalogue_path.write_text(json.dumps(catalogue, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    replacements = replacement_map(records)
    changed_files = 0
    replacements_made = 0
    html_paths = sorted(ROOT.glob("*.html")) + sorted((ROOT / "papers").glob("*.html"))
    for path in html_paths:
        source = path.read_text(encoding="utf-8")
        rendered, count = substitute_dois(source, replacements)
        if rendered != source:
            path.write_text(rendered, encoding="utf-8")
            changed_files += 1
            replacements_made += count

    subprocess.run(
        [sys.executable, "-B", str(ROOT / "scripts" / "build_site_metadata.py"), "--write"],
        cwd=ROOT,
        check=True,
    )
    print(
        f"Updated {catalogue_updates} papers.json entries and replaced {replacements_made} DOI occurrence(s) "
        f"across {changed_files} HTML file(s)."
    )


def update_one_description(record_id: int, token: str) -> str:
    base = f"{API_ROOT}/deposit/depositions/{record_id}"
    deposition = request_json(base, token=token)
    description = str(deposition.get("metadata", {}).get("description") or "")
    if has_description_banner(description):
        return "skipped"

    if deposition.get("state") == "done":
        deposition = request_json(f"{base}/actions/edit", method="POST", token=token)
    elif deposition.get("state") != "inprogress":
        raise RuntimeError(f"record {record_id} is in unsupported deposition state {deposition.get('state')!r}")

    metadata = dict(deposition.get("metadata") or {})
    if has_description_banner(str(metadata.get("description") or "")):
        return "skipped"
    metadata["description"] = DESCRIPTION_BANNER + "\n" + str(metadata.get("description") or "").lstrip()

    try:
        request_json(base, method="PUT", token=token, payload={"metadata": metadata})
        request_json(f"{base}/actions/publish", method="POST", token=token)
    except Exception:
        try:
            request_json(f"{base}/actions/discard", method="POST", token=token)
        except Exception:
            pass
        raise
    return "updated"


def apply_descriptions(report: dict[str, Any], delay: float) -> None:
    token = os.environ.get("ZENODO_ACCESS_TOKEN", "").strip()
    if not token:
        raise RuntimeError("ZENODO_ACCESS_TOKEN is not set")
    if report["unmatched_pages"] or report["ambiguous_pages"] or report["duplicate_concepts"]:
        raise RuntimeError("cannot update Zenodo until page-to-concept mapping errors are resolved")

    targets = [
        item
        for item in sorted(report["mapping"].values(), key=lambda value: value["latest_record_id"])
        if not has_description_banner(str(item["record"].get("metadata", {}).get("description") or ""))
    ]
    data_dir = ROOT / "data"
    log_path = data_dir / "zenodo-description-log.csv"
    log_fields = ["updated_at", "latest_record_id", "concept_doi", "latest_version_doi", "href", "status"]
    existing: list[dict[str, str]] = []
    if log_path.exists():
        with log_path.open(encoding="utf-8", newline="") as handle:
            existing = list(csv.DictReader(handle))

    for position, item in enumerate(targets, start=1):
        status = update_one_description(item["latest_record_id"], token)
        timestamp = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
        existing.append(
            {
                "updated_at": timestamp,
                "latest_record_id": str(item["latest_record_id"]),
                "concept_doi": item["concept_doi"],
                "latest_version_doi": item["latest_version_doi"],
                "href": item["href"],
                "status": status,
            }
        )
        log_path.parent.mkdir(parents=True, exist_ok=True)
        with log_path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=log_fields)
            writer.writeheader()
            writer.writerows(existing)
        print(f"Description {position}/{len(targets)}: {item['latest_record_id']} {status}", flush=True)
        time.sleep(delay)
    print(f"Description update complete: {len(targets)} target record(s).")


def print_summary(report: dict[str, Any]) -> None:
    print(
        "Zenodo audit: "
        f"{report['unique_pages']} unique pages, {report['zenodo_concepts']} concepts, "
        f"{report['record_versions']} versions, {report['mapped_pages']} mapped."
    )
    print(
        "Description banner: "
        f"{report['description_banners_present']} present, {report['description_banners_missing']} missing."
    )
    print(f"Catalogue DOI values needing concept migration: {report['catalogue_dois_needing_concept_update']}.")
    print(
        "Mapping issues: "
        f"{len(report['unmatched_pages'])} unmatched, {len(report['ambiguous_pages'])} ambiguous, "
        f"{len(report['duplicate_concepts'])} duplicate concepts."
    )


def main() -> int:
    args = parse_args()
    records = load_records(args)
    entries = catalogue_entries()
    report = audit(records, entries)
    print_summary(report)

    if args.snapshot:
        write_snapshot(report)
    if args.update_site_dois:
        update_site_dois(report, records)
    if args.apply_descriptions:
        apply_descriptions(report, args.delay)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
