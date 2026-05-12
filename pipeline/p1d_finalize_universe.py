"""
Phase 1D — Universe finalization.

By the end of 1C, `matched_universe.csv` already holds the deduped
universe with CIK resolution. PHASES.md's original 1D ("merge ETF
holdings on ticker, left-join CIK") was for a workflow where 1C was a
single-shot lookup; with the extended 1C-1+1C-3 staging we landed,
that merge is already done. 1D is now a *finalization* pass:

  1. Verify required columns are present
  2. Add (NULL) optional columns Phase 2A will populate
  3. Quality checks — CIK uniqueness, ticker uniqueness over non-null,
     foreign_filer / cusip distribution sanity
  4. Confirm `unmatched_final.csv` tickers haven't leaked back in
  5. Rename / re-emit as `raw_universe.csv` (canonical Phase 2 input)

Output
  data/universe/raw_universe.csv

This is the canonical universe handed to Phase 2 (Digital Economy
filter) and the evaluation base for the ARKK/WCLD re-decision
(D-ETF-Skip-Bot-Protected, trigger fired).
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

DATA_DIR = Path(__file__).parent.parent / "data" / "universe"

REQUIRED_COLS = [
    "cik", "ticker", "name", "cusip", "isin",
    "foreign_filer", "source_indices", "match_source",
]

# Optional columns that Phase 2A (yfinance / SEC submissions) populates.
# Pre-create them as NULL here so the schema is stable through Phase 2.
PHASE_2A_PLACEHOLDERS = [
    "gics_sector", "gics_industry_group", "gics_sub_industry",
    "sic", "sic_description",
    "market_cap_usd", "employees",
    "last_10k_date",
]


def finalize() -> dict:
    print("=== Phase 1D — Universe finalization ===\n")

    matched_path = DATA_DIR / "matched_universe.csv"
    unmatched_path = DATA_DIR / "unmatched_final.csv"
    raw_path = DATA_DIR / "raw_universe.csv"

    df = pd.read_csv(matched_path, dtype={"cik": str})
    unmatched = pd.read_csv(unmatched_path, dtype={"cik": str})
    print(f"loaded matched_universe.csv: {len(df):,} rows")
    print(f"loaded unmatched_final.csv:  {len(unmatched)} rows (excluded)\n")

    # [1] Required columns ----------------------------------------
    missing = [c for c in REQUIRED_COLS if c not in df.columns]
    if missing:
        raise AssertionError(f"Required columns missing: {missing}")
    print(f"[1] Required columns present: {REQUIRED_COLS}")

    # [2] Placeholder columns -------------------------------------
    added_placeholders = []
    for col in PHASE_2A_PLACEHOLDERS:
        if col not in df.columns:
            df[col] = None
            added_placeholders.append(col)
    print(f"[2] Phase 2A placeholders added: {added_placeholders}\n")

    # [3] Quality checks ------------------------------------------
    issues = []

    # CIK uniqueness
    if not df["cik"].is_unique:
        dup_count = (df["cik"].value_counts() > 1).sum()
        issues.append(f"  {dup_count} CIK duplicates")
    else:
        print("[3a] CIK uniqueness: OK")

    # Ticker uniqueness (only among non-null tickers)
    non_null_tickers = df.loc[df["ticker"].notna(), "ticker"]
    if not non_null_tickers.is_unique:
        dup_t = non_null_tickers.value_counts()
        dup_count = (dup_t > 1).sum()
        issues.append(f"  {dup_count} non-null ticker duplicates")
    else:
        print(
            f"[3b] Ticker uniqueness (over non-null): OK "
            f"({non_null_tickers.notna().sum():,} non-null, "
            f"{df['ticker'].isna().sum()} null)"
        )

    # Unmatched-ticker leakage
    overlap = (
        set(df["ticker"].dropna()) & set(unmatched["ticker"].dropna())
    )
    if overlap:
        issues.append(f"  Unmatched leaked back: {overlap}")
    else:
        print("[3c] Unmatched ticker leakage: none")

    # foreign_filer dtype + distribution
    ff_counts = df["foreign_filer"].fillna(0).astype(int).value_counts().to_dict()
    print(f"[3d] foreign_filer distribution: {ff_counts}")

    # cusip distribution (should be ~318 from VGT N-PORT-P)
    cusip_present = df["cusip"].notna().sum()
    print(f"[3e] cusip not-null: {cusip_present} (expected ~300 from VGT)")

    if issues:
        print("\nIssues:")
        for i in issues:
            print(i)
        raise AssertionError("1D quality checks failed; see above")

    # [4] Save raw_universe.csv -----------------------------------
    # Lock column order so Phase 2 downstream knows what to expect.
    final_cols = REQUIRED_COLS + PHASE_2A_PLACEHOLDERS
    df = df[final_cols]
    df.to_csv(raw_path, index=False)
    print(f"\n[4] Saved: {raw_path}")

    # [5] Report distributions ------------------------------------
    print("\n=== Distributions ===")
    print(f"\nmatch_source:")
    print(df["match_source"].value_counts().to_string())
    print(f"\nTop source_indices patterns (top 15):")
    print(df["source_indices"].value_counts().head(15).to_string())

    return {
        "raw_universe_rows": len(df),
        "unmatched_excluded": len(unmatched),
        "foreign_filer_count": int(df["foreign_filer"].fillna(0).astype(int).sum()),
        "cusip_present": int(cusip_present),
        "null_tickers": int(df["ticker"].isna().sum()),
    }


def main():
    summary = finalize()
    print("\n=== Phase 1D Summary ===")
    for k, v in summary.items():
        print(f"  {k}: {v:,}")


if __name__ == "__main__":
    main()
