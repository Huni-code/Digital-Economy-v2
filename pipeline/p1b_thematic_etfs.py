"""
Phase 1B — Thematic ETF holdings (13 ETFs across 8 issuers).

Universe-expansion supplement to Phase 1A's broad indices. Picks up
sector/theme exposures broad-index GICS classification underrepresents
(cloud, cybersecurity, fintech, gaming, robotics, etc.).

The 13 ETFs land across 8 issuers with different CSV formats and
download patterns, so this script is organized as a registry of
per-issuer FETCHER functions. Each fetcher returns (csv_text,
data_as_of) and a corresponding PARSER turns the text into our
normalized schema.

Wave 1 — iShares family (verified URL pattern from Phase 1A):
  IGV   iShares Expanded Tech-Software Sector ETF
  SOXX  iShares Semiconductor ETF

Wave 2 — heterogeneous single-issuer (TBD):
  XLK (SSGA), VGT (Vanguard), SKYY (First Trust),
  WCLD (WisdomTree), ARKK (ARK)

Wave 3 — family URL-pattern verification (TBD):
  IBUY / HACK / GAMR (Amplify, ex-ETFMG)
  FINX / SOCL / BOTZ (Global X)

Output (per ticker)
  data/universe/{etf}_holdings_YYYYMMDD.{csv,xlsx,html}   raw, gitignored
Output (combined across all defined waves)
  data/universe/etf_thematic_combined.csv                  committed

Combined-CSV schema (same as 1A's broad_indices_combined.csv)
  ticker, name, sector_ishares, etf_market_value_usd, weight_pct,
  source_index, data_as_of

⚠ etf_market_value_usd is the ETF's position size, NOT the company's
market cap. Phase 2A fetches real market_cap_usd via yfinance.
"""

import io
import re
import datetime
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import pandas as pd
import requests

from _helpers import (
    is_valid_equity_ticker,
    normalize_currency,
    normalize_weight_pct,
)

DATA_DIR = Path(__file__).parent.parent / "data" / "universe"
DATA_DIR.mkdir(parents=True, exist_ok=True)

USER_AGENT = (
    "Mozilla/5.0 (compatible; DigitalEconomyResearch/2.0; "
    "sunghun.kim@calvin.edu)"
)
HEADERS = {"User-Agent": USER_AGENT}

ASOF_PATTERN = re.compile(r'Fund Holdings as of[,\s]+"?([0-9A-Za-z/, -]+?)"?[\r\n]')


# ────────────────────────────────────────────────────────────────────
# Common helpers (shared with p1a; duplicated here so 1A stays
# untouched while 1B evolves)
# ────────────────────────────────────────────────────────────────────

def find_ishares_header_row(text: str) -> int:
    """iShares CSVs prefix the holdings table with 5-10 metadata rows.
    Find the first line that starts with 'Ticker,Name,' — handles both
    IWV-style (Ticker,Name,Sector,...) and IJH/IJR-style
    (Ticker,Name,Type,Sector,...) variants."""
    for i, line in enumerate(text.splitlines()):
        cleaned = line.lstrip("﻿").lstrip('"')
        if cleaned.startswith("Ticker,Name,") or cleaned.startswith('Ticker","Name'):
            return i
    raise ValueError("header row starting with 'Ticker,Name,' not found")


def extract_asof(text: str, fallback: str) -> str:
    m = ASOF_PATTERN.search(text)
    if not m:
        return fallback
    raw = m.group(1).strip().strip('"')
    for fmt in ("%d/%b/%Y", "%Y-%m-%d", "%m/%d/%Y", "%b %d, %Y"):
        try:
            return datetime.datetime.strptime(raw, fmt).date().isoformat()
        except ValueError:
            continue
    return fallback


def latest_cached(etf: str) -> Path | None:
    files = sorted(DATA_DIR.glob(f"{etf.lower()}_holdings_*.csv"))
    return files[-1] if files else None


def http_get_with_cache(etf: str, url: str) -> tuple[str, str]:
    """Today's-cache short-circuit; HTTP on miss; fallback to most-recent
    cache on HTTP failure. Returns (text, data_as_of_iso_or_yyyymmdd)."""
    today = datetime.date.today().strftime("%Y%m%d")
    cache_path = DATA_DIR / f"{etf.lower()}_holdings_{today}.csv"

    if cache_path.exists():
        text = cache_path.read_text(encoding="utf-8")
        return text, extract_asof(text, today)

    try:
        r = requests.get(url, headers=HEADERS, timeout=30)
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


# ────────────────────────────────────────────────────────────────────
# Issuer-specific parsers
# ────────────────────────────────────────────────────────────────────

def parse_ishares(csv_text: str, source: str, data_as_of: str) -> pd.DataFrame:
    """iShares CSV → normalized DataFrame. Same logic that drove 1A,
    refactored through _helpers + canonical schema."""
    skip = find_ishares_header_row(csv_text)
    df = pd.read_csv(io.StringIO(csv_text), skiprows=skip)

    if "Asset Class" in df.columns:
        df = df[df["Asset Class"].astype(str).str.strip().str.lower() == "equity"]
    df["Ticker"] = df["Ticker"].astype(str).str.strip().str.upper()
    df = df[df["Ticker"].apply(is_valid_equity_ticker)]

    mv_col = next((c for c in df.columns if "Market Value" in c), None)
    w_col = next(
        (c for c in df.columns if "Weight" in c and "Notional" not in c),
        None,
    )

    out = pd.DataFrame({
        "ticker": df["Ticker"].values,
        "name": df["Name"].astype(str).str.strip().values,
        "sector_ishares": df["Sector"].astype(str).str.strip().values,
        "etf_market_value_usd": (
            df[mv_col].apply(normalize_currency).values if mv_col else pd.NA
        ),
        "weight_pct": (
            df[w_col].apply(normalize_weight_pct).values if w_col else pd.NA
        ),
    })
    out["source_index"] = source
    out["classification_raw"] = None
    out["source_classification"] = None
    out["data_as_of"] = data_as_of
    return out[SCHEMA_COLS].reset_index(drop=True)


# ────────────────────────────────────────────────────────────────────
# SSGA (State Street SPDR) — xlsx with metadata header, no Asset Class
# ────────────────────────────────────────────────────────────────────

# Date in row 3 of SSGA xlsx looks like 'As of 08-May-2026'.
SSGA_ASOF_RE = re.compile(r"As of\s+([0-9A-Za-z-]+)")

# First Trust HTML body carries 'as of 5/8/2026'.
FT_ASOF_RE = re.compile(r"[Aa]s of\s+(\d{1,2}/\d{1,2}/\d{4})")

# Schema columns every Phase 1 parser must emit (order locked).
SCHEMA_COLS = [
    "ticker", "name", "sector_ishares", "etf_market_value_usd",
    "weight_pct", "source_index", "classification_raw",
    "source_classification", "data_as_of",
]


def _ssga_extract_asof(rows: list, fallback: str) -> str:
    """Scan first 5 rows for 'As of <DD-MMM-YYYY>' and normalize to ISO."""
    for row in rows[:5]:
        for cell in row:
            if cell is None:
                continue
            m = SSGA_ASOF_RE.search(str(cell))
            if not m:
                continue
            raw = m.group(1).strip()
            for fmt in ("%d-%b-%Y", "%Y-%m-%d", "%m/%d/%Y"):
                try:
                    return datetime.datetime.strptime(raw, fmt).date().isoformat()
                except ValueError:
                    continue
    return fallback


def parse_ssga_xlsx(xlsx_bytes_or_text, source: str, data_as_of: str) -> pd.DataFrame:
    """SSGA SPDR xlsx parser. Differences vs iShares:
      - xlsx not csv (openpyxl via pandas.read_excel)
      - Single sheet named 'holdings'
      - Header at row 5: Name, Ticker, Identifier, SEDOL, Weight, Sector,
        Shares Held, Local Currency
      - Sector column is '-' placeholder for single-sector ETFs (XLK)
      - No Market Value column → etf_market_value_usd stays NaN
      - No Asset Class column → use ticker regex + shares_held > 0 to
        filter out cash sweeps, futures, USD overlays
    """
    if isinstance(xlsx_bytes_or_text, str):
        xlsx_bytes_or_text = xlsx_bytes_or_text.encode("latin-1", errors="ignore")

    # Read raw without header so we can locate header row and refresh
    # data_as_of from row 3 metadata.
    raw = pd.read_excel(
        io.BytesIO(xlsx_bytes_or_text),
        sheet_name="holdings",
        header=None,
        engine="openpyxl",
    )

    # Refresh data_as_of from xlsx metadata if available.
    head_rows = raw.head(5).values.tolist()
    data_as_of = _ssga_extract_asof(head_rows, data_as_of)

    # Header row: find the row whose any cell is exactly 'Ticker'.
    header_idx = None
    for i, row in enumerate(raw.itertuples(index=False, name=None)):
        if any(isinstance(c, str) and c.strip() == "Ticker" for c in row):
            header_idx = i
            break
    if header_idx is None:
        raise ValueError("SSGA xlsx: header row with 'Ticker' cell not found")

    df = raw.iloc[header_idx + 1:].copy()
    df.columns = list(raw.iloc[header_idx])

    # Asset filter (no Asset Class column available):
    #  (a) ticker letters-only 1-5 chars (drops "-" cash, "IXTM6" futures)
    #  (b) Shares Held > 0 (drops negative-shares USD overlay)
    df["Ticker"] = df["Ticker"].astype(str).str.strip().str.upper()
    df = df[df["Ticker"].apply(is_valid_equity_ticker)]
    if "Shares Held" in df.columns:
        sh = pd.to_numeric(df["Shares Held"], errors="coerce")
        df = df[sh > 0]

    # Sector '-' placeholder → None so Phase 2A's yfinance fills it.
    sector_raw = df["Sector"].astype(str).str.strip() if "Sector" in df.columns else pd.Series([None] * len(df))
    sector_clean = sector_raw.where(sector_raw != "-", None)

    out = pd.DataFrame({
        "ticker": df["Ticker"].values,
        "name": df["Name"].astype(str).str.strip().values if "Name" in df.columns else pd.NA,
        "sector_ishares": sector_clean.values,
        "etf_market_value_usd": pd.NA,  # SSGA xlsx doesn't carry this
        "weight_pct": (
            df["Weight"].apply(normalize_weight_pct).values
            if "Weight" in df.columns else pd.NA
        ),
    })
    out["source_index"] = source
    out["classification_raw"] = None
    out["source_classification"] = None
    out["data_as_of"] = data_as_of
    return out[SCHEMA_COLS].reset_index(drop=True)


# ────────────────────────────────────────────────────────────────────
# First Trust — HTML page with inline holdings table (no CSV/xlsx export)
# ────────────────────────────────────────────────────────────────────

def _ft_extract_asof(html_text: str, fallback: str) -> str:
    m = FT_ASOF_RE.search(html_text)
    if not m:
        return fallback
    try:
        return datetime.datetime.strptime(m.group(1), "%m/%d/%Y").date().isoformat()
    except ValueError:
        return fallback


def parse_first_trust_html(html_text: str, source: str, data_as_of: str) -> pd.DataFrame:
    """First Trust ships holdings inline on the HTML page; pandas.read_html
    (lxml backend) finds the right <table> by heuristic:
      >= 20 data rows AND column-1 has >= 5 valid-ticker matches.

    Table layout (0-indexed columns, header in row 0):
      0: Security Name
      1: Identifier (ticker)
      2: CUSIP                            (skipped)
      3: Classification (sub-industry)
      4: Shares / Quantity                (skipped)
      5: Market Value (e.g., $109,148,895.76)
      6: Weighting (e.g., 4.06%)

    Sector_ishares is left NULL: First Trust doesn't ship a GICS sector
    column, only their own sub-industry classification (captured in
    classification_raw).
    """
    tables = pd.read_html(io.StringIO(html_text))

    target = None
    for t in tables:
        if len(t) < 20 or t.shape[1] < 6:
            continue
        col1 = t.iloc[:, 1].astype(str)
        hits = col1.apply(is_valid_equity_ticker).sum()
        if hits >= 5:
            target = t
            break

    if target is None:
        raise ValueError(
            "First Trust HTML: no holdings table found "
            "(no table with >=20 rows and >=5 valid tickers)"
        )

    # Row 0 is the header (Security Name, Identifier, ...). Drop it.
    body = target.iloc[1:].copy()

    # Filter cash overlays (`$USD`) via the ticker regex.
    tickers = body.iloc[:, 1].astype(str).str.strip()
    mask = tickers.apply(is_valid_equity_ticker)
    body = body[mask]
    tickers = tickers[mask]

    out = pd.DataFrame({
        "ticker": tickers.str.upper().values,
        "name": body.iloc[:, 0].astype(str).str.strip().values,
        "sector_ishares": None,
        "etf_market_value_usd": body.iloc[:, 5].apply(normalize_currency).values,
        "weight_pct": body.iloc[:, 6].apply(normalize_weight_pct).values,
    })
    out["source_index"] = source
    out["classification_raw"] = body.iloc[:, 3].astype(str).str.strip().values
    out["source_classification"] = "First Trust"
    out["data_as_of"] = _ft_extract_asof(html_text, data_as_of)
    return out[SCHEMA_COLS].reset_index(drop=True)


def http_get_html_with_cache(etf: str, url: str) -> tuple[str, str]:
    """HTML variant — saves with .html extension so .gitignore patterns
    distinguish raw HTML scrapes from CSV/xlsx caches."""
    today = datetime.date.today().strftime("%Y%m%d")
    cache_path = DATA_DIR / f"{etf.lower()}_holdings_{today}.html"

    if cache_path.exists():
        return cache_path.read_text(encoding="utf-8"), today

    try:
        r = requests.get(url, headers=HEADERS, timeout=30)
        r.raise_for_status()
        cache_path.write_text(r.text, encoding="utf-8")
        return r.text, today
    except Exception as e:
        print(f"  [{etf}] download failed: {e}")
        files = sorted(DATA_DIR.glob(f"{etf.lower()}_holdings_*.html"))
        if not files:
            raise RuntimeError(f"{etf}: no cached html fallback available") from e
        fb = files[-1]
        print(f"  [{etf}] using cached {fb.name}")
        return fb.read_text(encoding="utf-8"), fb.stem.split("_")[-1]


def http_get_xlsx_with_cache(etf: str, url: str) -> tuple[bytes, str]:
    """Binary-safe variant of http_get_with_cache. xlsx caches saved
    with .xlsx extension so they're not confused with .csv caches."""
    today = datetime.date.today().strftime("%Y%m%d")
    cache_path = DATA_DIR / f"{etf.lower()}_holdings_{today}.xlsx"

    if cache_path.exists():
        data = cache_path.read_bytes()
        return data, today

    try:
        r = requests.get(url, headers=HEADERS, timeout=30)
        r.raise_for_status()
        cache_path.write_bytes(r.content)
        return r.content, today
    except Exception as e:
        print(f"  [{etf}] download failed: {e}")
        files = sorted(DATA_DIR.glob(f"{etf.lower()}_holdings_*.xlsx"))
        if not files:
            raise RuntimeError(f"{etf}: no cached xlsx fallback available") from e
        fb = files[-1]
        print(f"  [{etf}] using cached {fb.name}")
        return fb.read_bytes(), fb.stem.split("_")[-1]


# ────────────────────────────────────────────────────────────────────
# Per-ETF registry
# ────────────────────────────────────────────────────────────────────

ISHARES_BASE = "https://www.ishares.com/us/products"


@dataclass
class ETFSpec:
    ticker: str
    name: str
    issuer: str
    url: str
    parser: Callable[[object, str, str], pd.DataFrame]
    # Fetcher dispatches CSV (text) vs xlsx (bytes) caching; defaults to
    # the iShares CSV path.
    fetcher: Callable[[str, str], tuple[object, str]] = None


def _ishares_url(product_id: int, slug: str, ticker: str) -> str:
    return (
        f"{ISHARES_BASE}/{product_id}/{slug}/1467271812596.ajax"
        f"?fileType=csv&fileName={ticker}_holdings&dataType=fund"
    )


REGISTRY: dict[str, ETFSpec] = {
    # ── Wave 1: iShares family ─────────────────────────────────────
    "IGV": ETFSpec(
        ticker="IGV",
        name="iShares Expanded Tech-Software Sector ETF",
        issuer="iShares",
        url=_ishares_url(239522, "ishares-expanded-tech-software-sector-etf", "IGV"),
        parser=parse_ishares,
        fetcher=None,  # default CSV fetcher
    ),
    "SOXX": ETFSpec(
        ticker="SOXX",
        name="iShares Semiconductor ETF",
        issuer="iShares",
        url=_ishares_url(239705, "ishares-semiconductor-etf", "SOXX"),
        parser=parse_ishares,
        fetcher=None,
    ),
    # ── Wave 2: heterogeneous single-issuer ────────────────────────
    "XLK": ETFSpec(
        ticker="XLK",
        name="Technology Select Sector SPDR",
        issuer="SSGA",
        url="https://www.ssga.com/library-content/products/fund-data/etfs/us/holdings-daily-us-en-xlk.xlsx",
        parser=parse_ssga_xlsx,
        fetcher=None,  # set below to http_get_xlsx_with_cache
    ),
    "SKYY": ETFSpec(
        ticker="SKYY",
        name="First Trust Cloud Computing ETF",
        issuer="First Trust",
        url="https://www.ftportfolios.com/Retail/Etf/EtfHoldings.aspx?Ticker=SKYY",
        parser=parse_first_trust_html,
        fetcher=None,  # set below to http_get_html_with_cache
    ),
    # WCLD, VGT — TBD per-issuer recon
    # ARKK — see D-ETF-Skip in docs/decisions.md (deferred to Wave 2 end)
    # ── Wave 3: family patterns (TBD) ──────────────────────────────
    # IBUY/HACK/GAMR (Amplify), FINX/SOCL/BOTZ (Global X)
}

# Non-CSV fetchers wired after function bodies are bound.
REGISTRY["XLK"].fetcher = http_get_xlsx_with_cache
REGISTRY["SKYY"].fetcher = http_get_html_with_cache


WAVES = {
    1: ["IGV", "SOXX"],
    2: ["XLK", "SKYY"],  # WCLD, VGT after recon; ARKK deferred (D-ETF-Skip)
    # 3: ["IBUY", "HACK", "GAMR", "FINX", "SOCL", "BOTZ"],
}


# ────────────────────────────────────────────────────────────────────
# Orchestration
# ────────────────────────────────────────────────────────────────────

def run_wave(wave: int) -> pd.DataFrame:
    tickers = WAVES[wave]
    frames = []
    for t in tickers:
        spec = REGISTRY[t]
        print(f"[{t}] {spec.name}  ({spec.issuer})")
        fetcher = spec.fetcher or http_get_with_cache
        payload, fallback_as_of = fetcher(t, spec.url)
        df = spec.parser(payload, t, fallback_as_of)
        # Parser may refine data_as_of from the file's metadata; pull
        # the canonical value back out of the DataFrame for reporting.
        as_of_resolved = df["data_as_of"].iloc[0] if len(df) else fallback_as_of
        aum_series = df["etf_market_value_usd"]
        aum_b = pd.to_numeric(aum_series, errors="coerce").sum(skipna=True) / 1e9
        aum_str = f"${aum_b:.2f}B AUM" if aum_b > 0 else "AUM n/a"
        print(f"  -> {len(df)} equity rows, {aum_str}, as_of {as_of_resolved}")
        frames.append(df)
    return pd.concat(frames, ignore_index=True)


def main(wave: int | None = None):
    if wave is None:
        # Run all defined waves
        all_frames = [run_wave(w) for w in sorted(WAVES.keys())]
        combined = pd.concat(all_frames, ignore_index=True)
        out_path = DATA_DIR / "etf_thematic_combined.csv"
        combined.to_csv(out_path, index=False)
        print()
        print("=== Phase 1B summary (all waves so far) ===")
    else:
        combined = run_wave(wave)
        out_path = DATA_DIR / f"thematic_wave{wave}.csv"
        combined.to_csv(out_path, index=False)
        print()
        print(f"=== Phase 1B Wave {wave} summary ===")

    print(f"Total rows (long format):    {len(combined)}")
    print(f"Distinct tickers:            {combined['ticker'].nunique()}")
    print()
    print("Per source:")
    for src, n in combined.groupby("source_index").size().items():
        print(f"  {src}: {n}")
    print()
    print(f"Output: {out_path}")


if __name__ == "__main__":
    import sys
    # No arg → run every defined wave and emit etf_thematic_combined.csv.
    # Integer arg → run that single wave and emit thematic_wave{N}.csv.
    wave_arg = int(sys.argv[1]) if len(sys.argv) > 1 else None
    main(wave=wave_arg)
