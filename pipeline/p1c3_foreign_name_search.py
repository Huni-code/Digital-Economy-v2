"""
Phase 1C-3 — Resolve unmatched foreign / digit-CUSIP rows via SEC EDGAR
company-name search.

Trigger: 1C-2 reported `foreign_cins + foreign_adr ≥ 10` (currently 15,
plus 4 `likely_recent_ipo` digit-CUSIP rows whose OpenFIGI US-listing
filter rejected the only available match). These 19 holdings have a
company name but no SEC ticker hit; SEC's full-text search resolves
them by name → CIK.

Inputs
  data/universe/unmatched_initial.csv   (Phase 1C-1 output)
  data/universe/matched_universe.csv    (resolved rows, will be appended to)

Outputs
  data/universe/matched_universe.csv    appended with newly-resolved rows
  data/universe/unmatched_final.csv     still-unresolved (after 1C-1+1C-3)
  data/cache/edgar_company_search/{slug}.json  per-name cached response

SEC EDGAR API
  GET https://efts.sec.gov/LATEST/search-index?q=<name>
  Returns top-ranked filer matches, each with ciks[] and display_names[].
  Rate limit: SEC requests ≤10 req/sec; we run at ~5 req/sec (0.2s sleep).

Quality control
  - The top-ranked hit's display_name must share at least one
    meaningful (non-suffix) token with the query name. Avoids picking
    "Apple Hospitality REIT" when searching for "Apple Inc".
  - For names like "PLC", "Ltd", "Inc" — those are stripped before
    matching since they're noise.
"""

from __future__ import annotations

import datetime
import json
import re
import time
from pathlib import Path

import pandas as pd
import requests

DATA_DIR = Path(__file__).parent.parent / "data" / "universe"
CACHE_DIR = Path(__file__).parent.parent / "data" / "cache" / "edgar_company_search"
CACHE_DIR.mkdir(parents=True, exist_ok=True)

USER_AGENT = (
    "Mozilla/5.0 (compatible; DigitalEconomyResearch/2.0; "
    "sunghun.kim@calvin.edu)"
)
HEADERS = {"User-Agent": USER_AGENT}

SEC_SEARCH_URL = "https://efts.sec.gov/LATEST/search-index"

# Common corporate suffixes / generic tokens that shouldn't be the sole
# basis for accepting a search hit.
_NOISE_TOKENS = {
    "INC", "CORP", "LTD", "PLC", "LLC", "NV", "SA", "AG", "AB",
    "GROUP", "HOLDINGS", "HOLDING", "COMPANY", "CO",
    "TECHNOLOGIES", "TECHNOLOGY", "TECH",
    "INTERNATIONAL", "INDUSTRIES", "ENTERPRISES",
    "THE", "AND", "AN", "A", "OF",
    "CLASS", "ORDINARY", "SHARES", "STOCK", "ADR", "REIT",
    "CORPORATION", "LIMITED",
}

# Categories that 1C-3 attempts to resolve. typo_or_unknown handled separately.
_RESOLVE_CATEGORIES = {"foreign_cins", "foreign_adr", "likely_recent_ipo"}


def _slug(s: str) -> str:
    return re.sub(r"[^A-Za-z0-9]+", "_", s.strip().lower()).strip("_")[:80]


def _clean_query(name: str) -> str:
    """Drop punctuation; trim common suffixes for a focused full-text query.

    Replaces `&` with space (SEC search misparses `&` as URL param sep
    in some paths; "Alpha & Omega" → "Alpha Omega").
    """
    s = re.sub(r"[.,()/&]+", " ", str(name))
    s = re.sub(r"\s+", " ", s).strip()
    # Drop trailing corporate suffix so the search ranks on distinctive head
    s = re.sub(
        r"\s+\b(Inc|Corp|Corporation|Ltd|Limited|PLC|LLC|NV|SA|AG|Holdings?|Group)\b\.?$",
        "",
        s,
        flags=re.IGNORECASE,
    )
    return s.strip()


_DISPLAY_TAIL_TICKER = re.compile(r"\s*\([A-Z]{1,6}\)\s*$")
_DISPLAY_TAIL_CIK = re.compile(r"\s*\(CIK\s+\d+\)\s*$", re.IGNORECASE)


def _clean_display(display: str) -> str:
    """Strip trailing '(TICKER) (CIK NNNNNNNN)' SEC adds to display names.
    Without this the parens-metadata pollutes the token set
    ('Elastic N.V. (ESTC) (CIK 0001707753)' picks up ESTC and CIK as
    matchable tokens)."""
    s = display
    s = _DISPLAY_TAIL_CIK.sub("", s)
    s = _DISPLAY_TAIL_TICKER.sub("", s)
    return s.strip()


def _tokens(s: str) -> set[str]:
    """Meaningful tokens: letters-only, length ≥ 2, not in noise set.
    Length filter drops 'N' / 'V' fragments from 'N.V.' splits so that
    'Elastic N.V.' tokenizes to {ELASTIC} (not {ELASTIC, N, V})."""
    return {
        t.upper() for t in re.findall(r"[A-Za-z]+", s)
        if len(t) >= 2 and t.upper() not in _NOISE_TOKENS
    }


def load_active_cik_set(tickers_cache: Path) -> set[str]:
    """Load CIK set from company_tickers.json — these are 'active filers
    with a ticker' per SEC. Used to prefer search hits that correspond
    to a currently-listed entity (filters out defunct entities like
    'Elastic Networks Inc' and subsidiaries like 'NXP B.V.')."""
    if not tickers_cache.exists():
        return set()
    raw = json.loads(tickers_cache.read_text(encoding="utf-8"))
    return {str(row["cik_str"]).zfill(10) for row in raw.values()}


def search_sec_by_name(
    name: str,
    active_ciks: set[str],
    sleep_s: float = 0.2,
) -> dict | None:
    """SEC EDGAR full-text search → best filer match.

    Two-pass selection over the top 25 hits:
      Pass 1 (preferred): token overlap AND cik ∈ `active_ciks`
        (the cik appears in company_tickers.json = active filer with
        a ticker). Avoids picking defunct entities / subsidiaries.
      Pass 2 (fallback): token overlap alone.

    Returns {"cik": "...", "display_name": "...", "match_source":
    "edgar_search:active|fallback"} or None.
    """
    cache_path = CACHE_DIR / f"{_slug(name)}.json"
    if cache_path.exists():
        data = json.loads(cache_path.read_text(encoding="utf-8"))
    else:
        query = _clean_query(name)
        if not query:
            return None
        try:
            r = requests.get(
                SEC_SEARCH_URL,
                params={"q": query},
                headers=HEADERS,
                timeout=20,
            )
            r.raise_for_status()
            data = r.json()
        except Exception as e:
            print(f"  [{name}] search error: {e}")
            return None
        cache_path.write_text(json.dumps(data), encoding="utf-8")
        time.sleep(sleep_s)

    hits = data.get("hits", {}).get("hits", [])
    if not hits:
        return None

    our_tokens = _tokens(name)
    if not our_tokens:
        return None

    # Score each candidate by Jaccard similarity between meaningful
    # tokens. Active-filer membership is a secondary tiebreaker.
    # Search top 50 hits (Flex Ltd was at #18 — top 25 wasn't enough).
    candidates = []
    seen_ciks = set()
    for h in hits[:50]:
        src = h.get("_source", {})
        for cik, disp in zip(src.get("ciks", []), src.get("display_names", [])):
            cik_padded = str(cik).zfill(10)
            if cik_padded in seen_ciks:
                continue
            hit_tokens = _tokens(_clean_display(disp))
            inter = our_tokens & hit_tokens
            if not inter:
                continue
            union = our_tokens | hit_tokens
            jaccard = len(inter) / len(union) if union else 0.0
            candidates.append({
                "cik": cik_padded,
                "display_name": disp,
                "jaccard": jaccard,
                "is_active": cik_padded in active_ciks,
            })
            seen_ciks.add(cik_padded)

    if not candidates:
        return None

    # Rank: higher Jaccard wins; ties broken by active-filer flag.
    candidates.sort(key=lambda c: (-c["jaccard"], not c["is_active"]))
    best = candidates[0]
    return {
        "cik": best["cik"],
        "display_name": best["display_name"],
        "match_source": (
            f"edgar_search:j={best['jaccard']:.2f}"
            f":{'active' if best['is_active'] else 'inactive'}"
        ),
    }


def main():
    print("=== Phase 1C-3: SEC EDGAR name-search resolver ===")
    print()

    matched_path = DATA_DIR / "matched_universe.csv"
    unmatched_path = DATA_DIR / "unmatched_initial.csv"
    final_path = DATA_DIR / "unmatched_final.csv"

    # dtype={'cik': str}: pandas would otherwise parse all-digit CIK
    # values to int64 and drop the leading-zero padding, which then
    # breaks the dedup groupby across re-runs.
    matched = pd.read_csv(matched_path, dtype={"cik": str})
    unmatched = pd.read_csv(unmatched_path, dtype={"cik": str})
    print(f"  matched rows in:   {len(matched):,}")
    print(f"  unmatched rows in: {len(unmatched):,}")
    print()

    targets = unmatched[unmatched["unmatched_category"].isin(_RESOLVE_CATEGORIES)].copy()
    untargeted = unmatched[~unmatched["unmatched_category"].isin(_RESOLVE_CATEGORIES)].copy()
    print(f"  targeting categories {_RESOLVE_CATEGORIES}: {len(targets)} rows")
    print(f"  passing through (typo_or_unknown etc.): {len(untargeted)} rows")
    print()

    print("[search] querying SEC EDGAR (~0.2s each, cached after first run)")
    tickers_cache = (
        Path(__file__).parent.parent / "data" / "cache" / "company_tickers.json"
    )
    active_ciks = load_active_cik_set(tickers_cache)
    print(f"  active CIK set ({len(active_ciks):,}) loaded for Pass 1 preference")
    results = []
    resolved_count = 0
    for i, row in enumerate(targets.itertuples(index=False), 1):
        name = getattr(row, "name", None)
        if not name or pd.isna(name):
            results.append(None)
            continue
        hit = search_sec_by_name(str(name), active_ciks)
        results.append(hit)
        if hit:
            resolved_count += 1
        tag = (hit["match_source"].split("edgar_search:")[-1] if hit else "no-match")
        print(f"  [{i:>2}/{len(targets)}] {name[:42]:<42} -> "
              f"{(hit['cik'] + ' ' + hit['display_name'][:30] + ' [' + tag + ']') if hit else 'NO MATCH'}")

    targets = targets.reset_index(drop=True).copy()
    targets["cik"] = [r["cik"] if r else None for r in results]
    targets["name_sec"] = [r["display_name"] if r else None for r in results]
    targets["match_source"] = [r["match_source"] if r else None for r in results]

    newly_resolved = targets[targets["cik"].notna()].copy()
    still_unresolved = targets[targets["cik"].isna()].copy()
    print()
    print(f"  resolved: {len(newly_resolved)} / {len(targets)}")
    print()

    # Append newly resolved to matched_universe.csv (align columns first)
    if len(newly_resolved):
        for c in matched.columns:
            if c not in newly_resolved.columns:
                newly_resolved[c] = None
        for c in ("unmatched_category",):
            if c in newly_resolved.columns:
                newly_resolved = newly_resolved.drop(columns=[c])
        newly_resolved = newly_resolved[matched.columns]
        matched_out = pd.concat([matched, newly_resolved], ignore_index=True)
    else:
        matched_out = matched.copy()

    # Dedup by CIK — same company can land twice (e.g., Accenture comes in
    # via IGV with ticker=ACN AND via VGT with ticker=None+CUSIP G1151C101).
    # Both end up with cik=0001467373 after 1C-1+1C-3; merge them.
    def _first_non_null(series):
        for v in series:
            if pd.notna(v) and str(v).strip() != "":
                return v
        return None

    def _join_sources(series):
        parts = set()
        for v in series:
            if pd.isna(v):
                continue
            for p in str(v).split(";"):
                p = p.strip()
                if p:
                    parts.add(p)
        return ";".join(sorted(parts)) if parts else None

    def _prefer_sec_auto(series):
        # Order: sec_auto > sec_variant > manual_override > edgar_search
        priority = {"sec_auto": 0, "manual_override": 1}
        best = None
        best_pri = 99
        for v in series:
            if pd.isna(v):
                continue
            v = str(v)
            pri = priority.get(v, 2 if v.startswith("sec_variant") else 3)
            if pri < best_pri:
                best, best_pri = v, pri
        return best

    # Ensure CIK is string with 10-char zero-padding before grouping
    # (pandas may have auto-converted on read).
    matched_out["cik"] = matched_out["cik"].apply(
        lambda c: str(c).zfill(10) if pd.notna(c) else None
    )

    before = len(matched_out)
    matched_out = (
        matched_out.groupby("cik", as_index=False, dropna=False)
        .agg({
            "ticker": _first_non_null,
            "name": _first_non_null,
            "cusip": _first_non_null,
            "isin": _first_non_null,
            "foreign_filer": "max",
            "source_indices": _join_sources,
            "name_sec": _first_non_null,
            "match_source": _prefer_sec_auto,
        })
    )
    after = len(matched_out)
    print(f"  CIK-dedup: {before:,} -> {after:,} rows ({before - after} merged)")

    matched_out.to_csv(matched_path, index=False)
    print(f"  wrote {matched_path.name}")

    # unmatched_final.csv = still_unresolved from 1C-3 + untargeted from 1C-1
    final_unmatched = pd.concat([still_unresolved, untargeted], ignore_index=True)
    # Annotate why each remains unresolved
    final_unmatched["resolution_reason"] = final_unmatched.apply(
        lambda r: (
            "edgar_no_match" if r["unmatched_category"] in _RESOLVE_CATEGORIES
            else r["unmatched_category"]
        ),
        axis=1,
    )
    final_unmatched.to_csv(final_path, index=False)

    print()
    print("=== Summary ===")
    print(f"  matched_universe.csv now: {len(matched_out):,} rows")
    print(f"  unmatched_final.csv: {len(final_unmatched)} rows")
    if len(final_unmatched):
        print()
        print("  Final unmatched (after 1C-1+1C-3) by reason:")
        print(final_unmatched["resolution_reason"].value_counts().to_string())
        print()
        print("  Final unmatched names:")
        print(final_unmatched[["ticker", "name", "cusip",
                               "resolution_reason"]].to_string(index=False))


if __name__ == "__main__":
    main()
