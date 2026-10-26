#!/usr/bin/env python3
"""Compare Zenodo attention across SAE series after correcting for publication age.

The report distinguishes lifetime attention from recent momentum:

* lifetime rates divide concept-wide totals by paper-days of exposure;
* recent rates divide changes since a historical snapshot by the paper-days
  actually exposed during that interval;
* momentum is the recent rate divided by the lifetime rate.

Publication dates come from Zenodo concept histories when ``--records-file``
is supplied.  The resulting cache makes later reports reproducible without a
network request.  Exact dates embedded in paper HTML are used as a fallback.
"""

from __future__ import annotations

import argparse
import csv
import importlib.util
import json
import re
import statistics
from collections import defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data"
DATE_CACHE = DATA_DIR / "zenodo-publication-dates.csv"
REPORT_CSV = DATA_DIR / "zenodo-series-analysis.csv"
REPORT_MD = DATA_DIR / "zenodo-series-analysis.md"
DATE_FIELDS = ["concept_doi", "first_publication_date", "latest_publication_date", "versions"]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--records-file",
        type=Path,
        help="cached JSON array returned by the Zenodo records API, including all versions",
    )
    parser.add_argument(
        "--recent-days",
        type=int,
        default=7,
        help="target lookback interval for current momentum (default: 7)",
    )
    parser.add_argument(
        "--write",
        action="store_true",
        help="write the publication-date cache plus CSV and Markdown reports",
    )
    return parser.parse_args()


def normalize_doi(value: Any) -> str:
    text = str(value or "").strip().lower()
    text = re.sub(r"^https?://(?:dx\.)?doi\.org/", "", text)
    return text.rstrip("/.,; ")


def parse_day(value: str) -> date:
    return date.fromisoformat(value[:10])


def load_index_locations() -> dict[str, dict[str, Any]]:
    path = ROOT / "scripts" / "build_site_metadata.py"
    spec = importlib.util.spec_from_file_location("build_site_metadata", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    locations, _groups = module.index_structure()
    return locations


def load_stats() -> tuple[list[dict[str, str]], date, datetime]:
    with (DATA_DIR / "zenodo-stats.csv").open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    if not rows:
        raise RuntimeError("data/zenodo-stats.csv is empty")

    latest_day = max(parse_day(row["snapshot_date"]) for row in rows)
    latest_rows = [row for row in rows if parse_day(row["snapshot_date"]) == latest_day]
    latest_capture = max(datetime.fromisoformat(row["captured_at"].replace("Z", "+00:00")) for row in latest_rows)
    return rows, latest_day, latest_capture


def choose_baseline(
    rows: list[dict[str, str]], latest_capture: datetime, recent_days: int
) -> tuple[date, datetime]:
    captures: dict[date, datetime] = {}
    for row in rows:
        day = parse_day(row["snapshot_date"])
        captured = datetime.fromisoformat(row["captured_at"].replace("Z", "+00:00"))
        captures[day] = max(captures.get(day, captured), captured)

    target = latest_capture.date() - timedelta(days=recent_days)
    candidates = [day for day in captures if day <= target]
    if not candidates:
        baseline_day = min(captures)
    else:
        baseline_day = max(candidates)
    return baseline_day, captures[baseline_day]


def zenodo_date_rows(records_file: Path) -> dict[str, dict[str, str]]:
    value = json.loads(records_file.read_text(encoding="utf-8"))
    if isinstance(value, dict):
        value = value.get("records") or value.get("hits", {}).get("hits")
    if not isinstance(value, list):
        raise ValueError("--records-file must contain a JSON array of Zenodo records")

    grouped: dict[str, list[date]] = defaultdict(list)
    for record in value:
        concept = normalize_doi(record.get("conceptdoi") or record.get("doi"))
        metadata = record.get("metadata") or {}
        raw_day = metadata.get("publication_date") or str(record.get("created") or "")[:10]
        if concept and re.fullmatch(r"\d{4}-\d{2}-\d{2}", raw_day or ""):
            grouped[concept].append(parse_day(raw_day))

    return {
        concept: {
            "concept_doi": concept,
            "first_publication_date": min(days).isoformat(),
            "latest_publication_date": max(days).isoformat(),
            "versions": str(len(days)),
        }
        for concept, days in grouped.items()
    }


def load_date_cache(records_file: Path | None) -> dict[str, dict[str, str]]:
    cached: dict[str, dict[str, str]] = {}
    if DATE_CACHE.exists():
        with DATE_CACHE.open(encoding="utf-8", newline="") as handle:
            cached = {normalize_doi(row["concept_doi"]): row for row in csv.DictReader(handle)}
    if records_file:
        cached.update(zenodo_date_rows(records_file))
    return cached


def html_publication_date(href: str) -> date | None:
    source = (ROOT / href).read_text(encoding="utf-8")
    match = re.search(
        r'<meta\s+name=["\']citation_publication_date["\']\s+content=["\']([^"\']+)',
        source,
        re.I,
    )
    if match and re.fullmatch(r"\d{4}-\d{2}-\d{2}", match.group(1)):
        return parse_day(match.group(1))
    return None


def number(row: dict[str, str], key: str) -> int:
    return int(row.get(key) or 0)


def f2(value: float) -> str:
    return f"{value:.2f}"


def build_analysis(args: argparse.Namespace) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    rows, latest_day, latest_capture = load_stats()
    baseline_day, baseline_capture = choose_baseline(rows, latest_capture, args.recent_days)
    current = {normalize_doi(row["concept_doi"]): row for row in rows if parse_day(row["snapshot_date"]) == latest_day}
    baseline = {
        normalize_doi(row["concept_doi"]): row
        for row in rows
        if parse_day(row["snapshot_date"]) == baseline_day
    }
    locations = load_index_locations()
    dates = load_date_cache(args.records_file)
    first_snapshot_day = min(parse_day(row["snapshot_date"]) for row in rows)
    history: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in rows:
        history[normalize_doi(row["concept_doi"])].append(row)
    for concept_rows in history.values():
        concept_rows.sort(key=lambda row: row["captured_at"])

    paper_rows: list[dict[str, Any]] = []
    missing_dates: list[str] = []
    for concept, row in current.items():
        href = row["href"]
        location = locations.get(href)
        if not location:
            raise RuntimeError(f"{href} is missing from the index hierarchy")

        cached = dates.get(concept, {})
        raw_release = cached.get("first_publication_date", "")
        release = parse_day(raw_release) if re.fullmatch(r"\d{4}-\d{2}-\d{2}", raw_release) else html_publication_date(href)
        if release is None:
            missing_dates.append(concept)
            continue

        previous = baseline.get(concept, {})
        lifetime_days = max(1, (latest_day - release).days + 1)
        if release <= baseline_day:
            recent_days = max(0.001, (latest_capture - baseline_capture).total_seconds() / 86400)
        else:
            recent_days = max(1, (latest_day - release).days + 1)

        paper_rows.append(
            {
                "concept_doi": concept,
                "series": location["series"],
                "domain": location["domain"],
                "release": release,
                "lifetime_days": lifetime_days,
                "recent_days": recent_days,
                "views": number(row, "views"),
                "downloads": number(row, "downloads"),
                "recent_views": number(row, "views") - number(previous, "views"),
                "recent_downloads": number(row, "downloads") - number(previous, "downloads"),
            }
        )

    if missing_dates:
        raise RuntimeError(
            f"missing exact first-publication dates for {len(missing_dates)} concept(s); "
            "supply a current --records-file"
        )

    grouped: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in paper_rows:
        grouped[(row["domain"], row["series"])].append(row)

    output: list[dict[str, Any]] = []
    for (domain, series), members in grouped.items():
        paper_days = sum(row["lifetime_days"] for row in members)
        recent_paper_days = sum(row["recent_days"] for row in members)
        views = sum(row["views"] for row in members)
        downloads = sum(row["downloads"] for row in members)
        recent_views = sum(row["recent_views"] for row in members)
        recent_downloads = sum(row["recent_downloads"] for row in members)
        view_rate = 100 * views / paper_days
        download_rate = 100 * downloads / paper_days
        recent_view_rate = 100 * recent_views / recent_paper_days
        recent_download_rate = 100 * recent_downloads / recent_paper_days
        median_age = statistics.median(row["lifetime_days"] for row in members)
        if median_age < 14:
            age_band = "new (<14d)"
        elif median_age < 30:
            age_band = "developing (14–29d)"
        else:
            age_band = "mature (≥30d)"

        cohort: dict[str, float | int] = {}
        for window in (7, 14, 30):
            samples: list[tuple[int, int]] = []
            for paper in members:
                release = paper["release"]
                target = release + timedelta(days=window)
                if release < first_snapshot_day or target > latest_day:
                    continue
                candidates = [
                    row
                    for row in history[paper["concept_doi"]]
                    if target <= parse_day(row["snapshot_date"]) <= target + timedelta(days=1)
                ]
                if not candidates:
                    continue
                sample = min(candidates, key=lambda row: row["captured_at"])
                samples.append((number(sample, "views"), number(sample, "downloads")))
            cohort[f"cohort_{window}d_papers"] = len(samples)
            cohort[f"cohort_{window}d_avg_views"] = (
                sum(sample[0] for sample in samples) / len(samples) if samples else 0
            )
            cohort[f"cohort_{window}d_avg_downloads"] = (
                sum(sample[1] for sample in samples) / len(samples) if samples else 0
            )
        output.append(
            {
                "domain": domain,
                "series": series,
                "papers": len(members),
                "first_release": min(row["release"] for row in members).isoformat(),
                "last_release": max(row["release"] for row in members).isoformat(),
                "median_age_days": round(median_age, 1),
                "age_band": age_band,
                "paper_days": round(paper_days, 3),
                "views": views,
                "downloads": downloads,
                "downloads_per_100_views": 100 * downloads / views if views else 0,
                "views_per_100_paper_days": view_rate,
                "downloads_per_100_paper_days": download_rate,
                "median_views_per_100_paper_days": statistics.median(
                    100 * row["views"] / row["lifetime_days"] for row in members
                ),
                "median_downloads_per_100_paper_days": statistics.median(
                    100 * row["downloads"] / row["lifetime_days"] for row in members
                ),
                "recent_views": recent_views,
                "recent_downloads": recent_downloads,
                "recent_views_per_100_paper_days": recent_view_rate,
                "recent_downloads_per_100_paper_days": recent_download_rate,
                "view_momentum": recent_view_rate / view_rate if view_rate else 0,
                "download_momentum": recent_download_rate / download_rate if download_rate else 0,
                **cohort,
            }
        )

    output.sort(key=lambda row: (row["downloads_per_100_paper_days"], row["views_per_100_paper_days"]), reverse=True)
    meta = {
        "latest_day": latest_day.isoformat(),
        "latest_capture": latest_capture.isoformat(),
        "baseline_day": baseline_day.isoformat(),
        "baseline_capture": baseline_capture.isoformat(),
        "interval_days": (latest_capture - baseline_capture).total_seconds() / 86400,
        "paper_count": len(paper_rows),
        "series_count": len(output),
        "date_cache": dates,
    }
    return output, meta


def write_csv(rows: list[dict[str, Any]]) -> None:
    fields = list(rows[0])
    with REPORT_CSV.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def write_markdown(rows: list[dict[str, Any]], meta: dict[str, Any]) -> None:
    eligible = [row for row in rows if row["papers"] >= 3]
    mature = [row for row in eligible if row["median_age_days"] >= 30]
    early = [row for row in eligible if row["median_age_days"] < 30]
    by_views = sorted(mature, key=lambda row: row["views_per_100_paper_days"], reverse=True)
    by_downloads = sorted(mature, key=lambda row: row["downloads_per_100_paper_days"], reverse=True)
    by_recent = sorted(eligible, key=lambda row: row["recent_downloads_per_100_paper_days"], reverse=True)
    by_momentum = sorted(
        [row for row in eligible if row["downloads"] >= 10 and row["median_age_days"] >= 14],
        key=lambda row: row["download_momentum"],
        reverse=True,
    )
    by_early = sorted(early, key=lambda row: row["downloads_per_100_paper_days"], reverse=True)
    cohort_7 = sorted(
        [row for row in eligible if row["cohort_7d_papers"] >= 3],
        key=lambda row: row["cohort_7d_avg_downloads"],
        reverse=True,
    )

    lines = [
        "# Zenodo series age-adjusted analysis",
        "",
        f"Latest snapshot: `{meta['latest_capture']}`. Recent comparison: `{meta['baseline_capture']}` to "
        f"`{meta['latest_capture']}` ({meta['interval_days']:.2f} days).",
        "",
        "Rates are concept-wide counts per 100 paper-days. A paper published today contributes one paper-day. "
        "Momentum is the recent rate divided by the lifetime rate; values above 1 indicate acceleration. "
        "Long-run rankings require at least three papers and a median age of 30 days. Early-signal and cohort "
        "tables are kept separate. The CSV contains every catalogue series, including per-paper medians.",
        "",
    ]

    def table(title: str, values: list[dict[str, Any]], rate_key: str, rate_label: str) -> None:
        lines.extend(
            [
                f"## {title}",
                "",
                f"| Series | Papers | First–latest release | {rate_label} | Views | Downloads | D/V |",
                "| --- | ---: | --- | ---: | ---: | ---: | ---: |",
            ]
        )
        for row in values[:15]:
            lines.append(
                f"| {row['series']} | {row['papers']} | {row['first_release']}–{row['last_release']} | "
                f"{f2(row[rate_key])} | {row['views']} | {row['downloads']} | "
                f"{f2(row['downloads_per_100_views'])}% |"
            )
        lines.append("")

    table("Highest mature-series lifetime view rate", by_views, "views_per_100_paper_days", "Views / 100 paper-days")
    table(
        "Highest mature-series lifetime download rate",
        by_downloads,
        "downloads_per_100_paper_days",
        "Downloads / 100 paper-days",
    )
    table(
        "Highest recent download rate",
        by_recent,
        "recent_downloads_per_100_paper_days",
        "Recent downloads / 100 paper-days",
    )

    table(
        "New and developing series: early download signal",
        by_early,
        "downloads_per_100_paper_days",
        "Downloads / 100 paper-days",
    )

    lines.extend(
        [
            "## Approximately 7, 14, and 30 days after publication",
            "",
            "Only papers released on or after the first stored snapshot are eligible. Counts use the first "
            "snapshot on the target day or the following day, so they are cohort indicators rather than "
            "exact clocks. Each cell is `eligible papers; average views / average downloads`.",
            "",
            "| Series | ~7d | ~14d | ~30d |",
            "| --- | ---: | ---: | ---: |",
        ]
    )

    def cohort_cell(row: dict[str, Any], window: int) -> str:
        papers = row[f"cohort_{window}d_papers"]
        if not papers:
            return "—"
        return (
            f"{papers}; {f2(row[f'cohort_{window}d_avg_views'])} / "
            f"{f2(row[f'cohort_{window}d_avg_downloads'])}"
        )

    for row in cohort_7[:15]:
        lines.append(
            f"| {row['series']} | {cohort_cell(row, 7)} | {cohort_cell(row, 14)} | "
            f"{cohort_cell(row, 30)} |"
        )
    lines.append("")

    lines.extend(
        [
            "## Fastest download momentum",
            "",
            "| Series | Papers | Recent Δ downloads | Lifetime rate | Recent rate | Momentum |",
            "| --- | ---: | ---: | ---: | ---: | ---: |",
        ]
    )
    for row in by_momentum[:15]:
        lines.append(
            f"| {row['series']} | {row['papers']} | {row['recent_downloads']:+d} | "
            f"{f2(row['downloads_per_100_paper_days'])} | "
            f"{f2(row['recent_downloads_per_100_paper_days'])} | {f2(row['download_momentum'])}× |"
        )
    lines.extend(["", f"Full machine-readable table: [{REPORT_CSV.name}]({REPORT_CSV.name})", ""])
    REPORT_MD.write_text("\n".join(lines), encoding="utf-8")


def write_date_cache(rows: dict[str, dict[str, str]]) -> None:
    with DATE_CACHE.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=DATE_FIELDS)
        writer.writeheader()
        writer.writerows(rows[key] for key in sorted(rows))


def main() -> None:
    args = parse_args()
    rows, meta = build_analysis(args)
    print(
        f"Analyzed {meta['paper_count']} papers in {meta['series_count']} series; "
        f"recent interval {meta['interval_days']:.2f} days."
    )
    if args.write:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        write_date_cache(meta["date_cache"])
        write_csv(rows)
        write_markdown(rows, meta)
        print(f"Wrote {DATE_CACHE.relative_to(ROOT)}, {REPORT_CSV.relative_to(ROOT)}, and {REPORT_MD.relative_to(ROOT)}.")
    else:
        for row in rows[:15]:
            print(
                f"{row['series']}: {row['downloads_per_100_paper_days']:.2f} lifetime and "
                f"{row['recent_downloads_per_100_paper_days']:.2f} recent downloads / 100 paper-days"
            )


if __name__ == "__main__":
    main()
