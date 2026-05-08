"""
Phase 1A — Broad-index holdings (IWV / IJH / IJR).

Downloads three iShares ETFs that together cover the U.S. listed-equity
universe approximated by Russell 3000 + S&P 400/600:
  - IWV : iShares Russell 3000 ETF
  - IJH : iShares Core S&P Mid-Cap ETF
  - IJR : iShares Core S&P Small-Cap ETF

Outputs
  data/universe/{etf}_holdings_YYYYMMDD.csv      raw, gitignored
  data/universe/broad_indices_combined.csv       normalized, committed

Combined-CSV schema
  ticker                stock ticker (uppercase, trimmed)
  name                  iShares-reported security name
  sector_ishares        GICS sector label as iShares writes it
  etf_market_value_usd  iShares' position size in USD = ETF AUM × weight%.
                        ⚠ NOT the company's own market cap. Real
                        market_cap_usd is fetched in Phase 2A via yfinance.
  weight_pct            weight in source ETF (%)
  source_index          'IWV' | 'IJH' | 'IJR'
  data_as_of            'Fund Holdings as of' date from iShares header
                        (YYYY-MM-DD); falls back to download date.

Same ticker can appear under multiple source_index values (long format).
Phase 1D dedupes after combining with 1B thematic ETFs.

Resilience
  - HTTP failure → fall back to most recent local cache file for that
    ETF; raise only if no cache exists.
  - Header row detected dynamically (`startswith("Ticker,Name,Sector")`)
    so iShares column-order changes don't silently break us.
  - Asset Class != Equity rows (Cash, FX, Futures) are dropped.
"""

import io
import re
import datetime
from pathlib import Path

import pandas as pd
import requests

DATA_DIR = Path(__file__).parent.parent / "data" / "universe"
DATA_DIR.mkdir(parents=True, exist_ok=True)

# Identify ourselves to iShares — generic crawlers occasionally get 403.
USER_AGENT = (
    "Mozilla/5.0 (compatible; DigitalEconomyResearch/2.0; "
    "sunghun.kim@calvin.edu)"
)
HEADERS = {"User-Agent": USER_AGENT}

ETFS = {
    "IWV": {
        "name": "iShares Russell 3000 ETF",
        "url": (
            "https://www.ishares.com/us/products/239714/"
            "ishares-russell-3000-etf/1467271812596.ajax"
            "?fileType=csv&fileName=IWV_holdings&dataType=fund"
        ),
    },
    "IJH": {
        "name": "iShares Core S&P Mid-Cap ETF",
        "url": (
            "https://www.ishares.com/us/products/239763/"
            "ishares-core-sp-midcap-etf/1467271812596.ajax"
            "?fileType=csv&fileName=IJH_holdings&dataType=fund"
        ),
    },
    "IJR": {
        "name": "iShares Core S&P Small-Cap ETF",
        "url": (
            "https://www.ishares.com/us/products/239774/"
            "ishares-core-sp-smallcap-etf/1467271812596.ajax"
            "?fileType=csv&fileName=IJR_holdings&dataType=fund"
        ),
    },
}

ASOF_PATTERN = re.compile(r'Fund Holdings as of[,\s]+"?([0-9A-Za-z/, -]+?)"?[\r\n]')


def find_header_row(text: str) -> int:
    """First line that begins with 'Ticker,Name,' — covers both schemas
    iShares ships (IWV: Ticker,Name,Sector,...; IJH/IJR: Ticker,Name,Type,
    Sector,...)."""
    for i, line in enumerate(text.splitlines()):
        # BOM or quote-wrapped first cell can prefix the line.
        cleaned = line.lstrip("﻿").lstrip('"')
        if cleaned.startswith("Ticker,Name,") or cleaned.startswith("Ticker\",\"Name"):
            return i
    raise ValueError("header row starting with 'Ticker,Name,' not found")


def extract_asof(text: str, fallback: str) -> str:
    """Pull 'Fund Holdings as of, DD/Mon/YYYY' from the metadata block."""
    m = ASOF_PATTERN.search(text)
    if not m:
        return fallback
    raw = m.group(1).strip().strip('"')
    for fmt in ("%d/%b/%Y", "%Y-%m-%d", "%m/%d/%Y"):
        try:
            return datetime.datetime.strptime(raw, fmt).date().isoformat()
        except ValueError:
            continue
    return fallback


def latest_cached(etf: str) -> Path | None:
    files = sorted(DATA_DIR.glob(f"{etf.lower()}_holdings_*.csv"))
    return files[-1] if files else None


def download(etf: str) -> tuple[str, str]:
    """Return (csv_text, data_as_of_iso). Today's cache hit short-circuits."""
    today = datetime.date.today().strftime("%Y%m%d")
    cache_path = DATA_DIR / f"{etf.lower()}_holdings_{today}.csv"

    if cache_path.exists():
        text = cache_path.read_text(encoding="utf-8")
        return text, extract_asof(text, today)

    try:
        r = requests.get(ETFS[etf]["url"], headers=HEADERS, timeout=30)
        r.raise_for_status()
        text = r.text
        cache_path.write_text(text, encoding="utf-8")
        return text, extract_asof(text, today)
    except Exception as e:
        print(f"  [{etf}] download failed: {e}")
        fb = latest_cached(etf)
        if fb is None:
            raise RuntimeError(f"{etf}: no cached fallback available") from e
        text = fb.read_text(encoding="utf-8")
        as_of = extract_asof(text, fb.stem.split("_")[-1])
        print(f"  [{etf}] using cached {fb.name} (as_of={as_of})")
        return text, as_of


def parse(csv_text: str, source: str, data_as_of: str) -> pd.DataFrame:
    skip = find_header_row(csv_text)
    df = pd.read_csv(io.StringIO(csv_text), skiprows=skip)

    # Equities only — drop Cash, FX hedges, futures, treasuries, etc.
    if "Asset Class" in df.columns:
        df = df[df["Asset Class"].astype(str).str.strip().str.lower() == "equity"]

    # Drop rows without a real ticker.
    df = df.dropna(subset=["Ticker"])
    df = df[~df["Ticker"].astype(str).str.strip().isin(["", "-"])]

    # Locate the slightly-variant column names iShares uses.
    # Market Value: same across IWV/IJH/IJR.
    mv_col = next((c for c in df.columns if "Market Value" in c), None)
    # Weight: IWV uses "Weight (%)", IJH/IJR use "Market Weight". Both
    # fund-level weights; "Notional Weight" is the futures-overlay
    # variant we don't want.
    w_col = next(
        (c for c in df.columns
         if "Weight" in c and "Notional" not in c),
        None,
    )

    out = pd.DataFrame({
        "ticker": df["Ticker"].astype(str).str.strip().str.upper(),
        "name": df["Name"].astype(str).str.strip(),
        "sector_ishares": df["Sector"].astype(str).str.strip(),
        "etf_market_value_usd": pd.to_numeric(
            df[mv_col].astype(str).str.replace(r"[$,]", "", regex=True),
            errors="coerce",
        ) if mv_col else pd.NA,
        "weight_pct": pd.to_numeric(
            df[w_col].astype(str).str.replace("%", "").str.strip(),
            errors="coerce",
        ) if w_col else pd.NA,
    })
    out["source_index"] = source
    out["data_as_of"] = data_as_of
    return out.reset_index(drop=True)


def main():
    frames = []
    for etf, meta in ETFS.items():
        print(f"[{etf}] {meta['name']}")
        text, as_of = download(etf)
        df = parse(text, etf, as_of)
        aum = df["etf_market_value_usd"].sum(skipna=True) / 1e9
        print(f"  -> {len(df)} equity rows, ${aum:.1f}B AUM, as_of {as_of}")
        frames.append(df)

    combined = pd.concat(frames, ignore_index=True)
    out_path = DATA_DIR / "broad_indices_combined.csv"
    combined.to_csv(out_path, index=False)

    print()
    print("=== Phase 1A summary ===")
    print(f"Total rows (long format):    {len(combined)}")
    print(f"Distinct tickers:            {combined['ticker'].nunique()}")
    print()
    print("Per source:")
    counts = combined.groupby("source_index").size()
    for src, n in counts.items():
        print(f"  {src}: {n}")
    print()
    print("Sector distribution (long format, all sources):")
    sec = combined.groupby("sector_ishares").size().sort_values(ascending=False)
    for s, n in sec.items():
        print(f"  {s:<32} {n}")
    print()
    print(f"Output: {out_path}")


if __name__ == "__main__":
    main()
