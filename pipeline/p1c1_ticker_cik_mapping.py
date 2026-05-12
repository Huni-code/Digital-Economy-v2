"""
Phase 1C-1 — Ticker → CIK mapping via SEC company_tickers.json + classify
unresolved entries.

Inputs
  data/universe/broad_indices_combined.csv      (Phase 1A output)
  data/universe/etf_thematic_combined.csv       (Phase 1B output)
  data/universe/manual_ticker_cik_overrides.csv (operator overrides)
  data/cache/company_tickers.json               (SEC, 7-day cache)

Outputs
  data/universe/matched_universe.csv     ticker resolved to CIK
  data/universe/unmatched_initial.csv    failures + classification

What this does
  1. Loads 1A + 1B long-format rows, dedups on ticker.
     Aggregates source_index → source_indices (semicolon-joined) and
     foreign_filer (any-true). cusip/isin kept (first non-null).
  2. Refreshes SEC company_tickers.json if cache is stale (>7 days).
  3. Auto-matches ticker → (cik, name_sec). cik zero-padded to 10 chars.
  4. Applies manual_ticker_cik_overrides.csv on top of auto-matches.
  5. Classifies unmatched rows into 4 buckets — see classify_unmatched().

Branching decision after this script:
  - foreign_cins + foreign_adr ≥ 10 → run 1C-3 (SEC name search)
  - likely_recent_ipo ≥ 5         → run 1C-4 (recent IPO resolution)
  - typo_or_unknown ≤ 5 only      → manual overrides + stop
"""

from __future__ import annotations

import datetime
import json
from pathlib import Path

import pandas as pd
import requests

DATA_DIR = Path(__file__).parent.parent / "data" / "universe"
CACHE_DIR = Path(__file__).parent.parent / "data" / "cache"
CACHE_DIR.mkdir(parents=True, exist_ok=True)

USER_AGENT = (
    "Mozilla/5.0 (compatible; DigitalEconomyResearch/2.0; "
    "sunghun.kim@calvin.edu)"
)
HEADERS = {"User-Agent": USER_AGENT}

SEC_TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
SEC_TICKERS_CACHE = CACHE_DIR / "company_tickers.json"
CACHE_MAX_AGE_DAYS = 7

OVERRIDES_CSV = DATA_DIR / "manual_ticker_cik_overrides.csv"


def fetch_sec_ticker_map() -> dict[str, dict]:
    """Cache-aware fetch of SEC's ticker → CIK index.

    Returns dict keyed by uppercase ticker:
      {ticker: {"cik": "0000320193", "name": "Apple Inc."}}
    """
    needs_refresh = True
    if SEC_TICKERS_CACHE.exists():
        age_days = (
            datetime.datetime.now().timestamp()
            - SEC_TICKERS_CACHE.stat().st_mtime
        ) / 86400
        if age_days < CACHE_MAX_AGE_DAYS:
            needs_refresh = False
            print(f"  using cache (age {age_days:.1f}d)")

    if needs_refresh:
        print(f"  downloading {SEC_TICKERS_URL}")
        r = requests.get(SEC_TICKERS_URL, headers=HEADERS, timeout=30)
        r.raise_for_status()
        SEC_TICKERS_CACHE.write_text(r.text, encoding="utf-8")

    raw = json.loads(SEC_TICKERS_CACHE.read_text(encoding="utf-8"))
    # SEC returns a dict-of-rows shape: {"0": {"cik_str": ..., "ticker": ..., "title": ...}}
    return {
        row["ticker"].upper(): {
            "cik": str(row["cik_str"]).zfill(10),
            "name": row["title"],
        }
        for row in raw.values()
    }


def load_combined_universe() -> pd.DataFrame:
    """Concat 1A + 1B long-format rows, dedup on ticker.

    Keeps NULL-ticker rows alive — VGT's N-PORT-P emits ~19 holdings
    whose CUSIP is foreign-CINS (G/M/N/Y prefix) and whose OpenFIGI
    lookup failed during Phase 1B (US-listing-only filter). Those rows
    have a CUSIP but no ticker; they belong in the universe so Phase
    1C-3 can resolve them via SEC name search.

    Aggregation (ticker-present rows only):
      - source_index → source_indices (semicolon-joined, sorted)
      - foreign_filer → max (any source flagging it wins)
      - cusip / isin / name → first non-null
    """
    broad = pd.read_csv(DATA_DIR / "broad_indices_combined.csv")
    thematic = pd.read_csv(DATA_DIR / "etf_thematic_combined.csv")
    raw = pd.concat([broad, thematic], ignore_index=True)

    has_ticker = raw["ticker"].notna() & (raw["ticker"].astype(str).str.strip() != "")
    with_t = raw[has_ticker].copy()
    no_t = raw[~has_ticker].copy()

    with_t["ticker"] = with_t["ticker"].astype(str).str.strip().str.upper()

    def first_non_null(series):
        for v in series:
            if pd.notna(v) and str(v).strip() != "":
                return v
        return None

    def join_sources(series):
        return ";".join(sorted({str(v) for v in series if pd.notna(v)}))

    grouped = (
        with_t.groupby("ticker", as_index=False)
        .agg({
            "name": first_non_null,
            "cusip": first_non_null,
            "isin": first_non_null,
            "foreign_filer": "max",
            "source_index": join_sources,
        })
        .rename(columns={"source_index": "source_indices"})
    )

    # Bring NULL-ticker rows in, deduped on CUSIP (their primary id).
    if len(no_t):
        no_t["source_indices"] = no_t["source_index"]
        # Keep only the columns grouped already has, in the same order.
        keep_cols = ["ticker", "name", "cusip", "isin",
                     "foreign_filer", "source_indices"]
        no_t = no_t[keep_cols].drop_duplicates(subset=["cusip", "name"])
        grouped = pd.concat([grouped, no_t], ignore_index=True)

    return grouped


def _ticker_variants(ticker: str) -> list[str]:
    """Try class-share variants when SEC's exact ticker doesn't match.

    iShares writes class shares concatenated (BRKB, BFA, HEIA), SEC's
    `company_tickers.json` writes them with a hyphen (BRK-B, BF-A,
    HEI-A). Generate the alternate forms for fallback lookup.

    Length ≥ 3 covers 2-letter-base names like BF (Brown Forman) →
    BFA/BFB → BF-A/BF-B; ≥ 4 would have missed those.
    """
    variants = [ticker]
    if len(ticker) >= 3 and ticker[-1] in "AB":
        head, tail = ticker[:-1], ticker[-1]
        variants.append(f"{head}-{tail}")
        variants.append(f"{head}.{tail}")
    return variants


def apply_manual_overrides(matched: pd.DataFrame, overrides_path: Path) -> pd.DataFrame:
    if not overrides_path.exists():
        return matched
    overrides = pd.read_csv(overrides_path)
    if overrides.empty:
        return matched

    overrides["ticker"] = overrides["ticker"].astype(str).str.strip().str.upper()
    overrides["cik"] = overrides["cik"].astype(str).str.zfill(10)
    over_map = dict(zip(overrides["ticker"], overrides["cik"]))
    name_map = dict(zip(overrides["ticker"], overrides["name"]))

    applied = 0
    for i, row in matched.iterrows():
        if pd.isna(row["cik"]) and row["ticker"] in over_map:
            matched.at[i, "cik"] = over_map[row["ticker"]]
            matched.at[i, "name_sec"] = name_map[row["ticker"]]
            matched.at[i, "match_source"] = "manual_override"
            applied += 1
    if applied:
        print(f"  manual overrides applied: {applied}")
    return matched


def classify_unmatched(unmatched: pd.DataFrame) -> pd.DataFrame:
    """Bucket each unmatched row for downstream 1C-3 / 1C-4 routing."""
    cats = []
    for _, row in unmatched.iterrows():
        cusip = str(row.get("cusip") or "").strip()
        if cusip and cusip.lower() != "nan" and cusip[0].isalpha():
            cats.append("foreign_cins")
            continue
        if int(row.get("foreign_filer") or 0) == 1:
            cats.append("foreign_adr")
            continue
        src = str(row.get("source_indices") or "")
        broad_present = any(b in src for b in ("IWV", "IJH", "IJR"))
        if not broad_present:
            cats.append("likely_recent_ipo")
            continue
        cats.append("typo_or_unknown")
    out = unmatched.copy()
    out["unmatched_category"] = cats
    return out


def main():
    print("=== Phase 1C-1: Ticker -> CIK mapping ===")
    print()
    print("[1] SEC company_tickers.json")
    sec_map = fetch_sec_ticker_map()
    print(f"  {len(sec_map):,} ticker entries loaded")
    print()

    print("[2] Load combined universe (broad + thematic, deduped)")
    universe = load_combined_universe()
    print(f"  {len(universe):,} distinct tickers")
    print()

    print("[3] Auto-match (with class-share variant fallback)")

    def resolve(t):
        if pd.isna(t) or not str(t).strip():
            return None, None, None
        for v in _ticker_variants(str(t)):
            hit = sec_map.get(v)
            if hit:
                source = "sec_auto" if v == t else f"sec_variant:{v}"
                return hit["cik"], hit["name"], source
        return None, None, None

    resolved = universe["ticker"].apply(resolve)
    universe["cik"] = [r[0] for r in resolved]
    universe["name_sec"] = [r[1] for r in resolved]
    universe["match_source"] = [r[2] for r in resolved]
    auto_matched = universe["cik"].notna().sum()
    variant_matched = sum(
        1 for r in resolved if r[2] and r[2].startswith("sec_variant")
    )
    print(f"  auto-matched: {auto_matched:,} / {len(universe):,}")
    if variant_matched:
        print(f"  ...of which class-share variant fallback: {variant_matched}")
    print()

    print("[4] Manual overrides")
    universe = apply_manual_overrides(universe, OVERRIDES_CSV)
    print()

    matched = universe[universe["cik"].notna()].copy()
    unmatched = universe[universe["cik"].isna()].copy()

    print("[5] Classify unmatched")
    unmatched = classify_unmatched(unmatched)
    print()

    matched_path = DATA_DIR / "matched_universe.csv"
    unmatched_path = DATA_DIR / "unmatched_initial.csv"
    matched.to_csv(matched_path, index=False)
    unmatched.to_csv(unmatched_path, index=False)

    total = len(matched) + len(unmatched)
    print("=== Summary ===")
    print(f"  Universe total:  {total:,}")
    print(f"  Matched:         {len(matched):,} ({len(matched)/total*100:.1f}%)")
    print(f"  Unmatched:       {len(unmatched):,} ({len(unmatched)/total*100:.1f}%)")
    print()
    print("Unmatched breakdown:")
    print(unmatched["unmatched_category"].value_counts().to_string())
    print()
    print("Sample unmatched rows per category:")
    for cat in unmatched["unmatched_category"].unique():
        sub = unmatched[unmatched["unmatched_category"] == cat].head(10)
        print(f"\n[{cat}] ({len(unmatched[unmatched['unmatched_category']==cat])} total)")
        print(sub[["ticker", "name", "cusip", "source_indices"]].to_string(index=False))
    print()
    print(f"Outputs:")
    print(f"  {matched_path}")
    print(f"  {unmatched_path}")


if __name__ == "__main__":
    main()
