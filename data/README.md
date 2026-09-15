# Zenodo maintenance data

`scripts/sync_zenodo.py` keeps the SAE website's Zenodo links and usage history auditable.

## Files

- `zenodo-current.json` — latest public Zenodo metadata and statistics for every SAE paper.
- `zenodo-audit.json` — mapping and Description-banner exceptions from the latest run.
- `zenodo-stats.csv` — one row per paper per UTC date. Re-running on the same date replaces that date's rows instead of duplicating them.
- `zenodo-stats-summary.md` — current top-viewed/top-downloaded rankings and, after a second capture date, growth since the previous snapshot.
- `zenodo-description-log.csv` — created only when authenticated Description updates are applied.

The statistics contain both concept-wide totals (`views`, `downloads`, and unique variants) and the latest-version counters (`version_*`).

## Commands

Audit without writing:

```bash
python3 -B scripts/sync_zenodo.py --audit
```

Capture or refresh today's statistics:

```bash
python3 -B scripts/sync_zenodo.py --snapshot
```

Migrate site citations to concept DOIs and rebuild generated metadata:

```bash
python3 -B scripts/sync_zenodo.py --update-site-dois
```

Updating published Zenodo descriptions requires a personal access token with `deposit:write` and `deposit:actions`. Keep the token only in the environment—never add it to this repository:

```bash
export ZENODO_ACCESS_TOKEN='...'
python3 -B scripts/sync_zenodo.py --apply-descriptions --confirm-remote-write
unset ZENODO_ACCESS_TOKEN
```

Only the latest published version for each concept is changed. Historical versions remain untouched.
