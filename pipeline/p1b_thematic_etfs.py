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
  data/universe/{etf}_holdings_YYYYMMDD.csv         raw, gitignored
Output (combined, after all waves)
  data/universe/thematic_combined.csv               normalized, committed

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
    """iShares CSV → normalized DataFrame. Same logic that drove 1A."""
    skip = find_ishares_header_row(csv_text)
    df = pd.read_csv(io.StringIO(csv_text), skiprows=skip)

    if "Asset Class" in df.columns:
        df = df[df["Asset Class"].astype(str).str.strip().str.lower() == "equity"]
    df = df.dropna(subset=["Ticker"])
    df = df[~df["Ticker"].astype(str).str.strip().isin(["", "-"])]

    mv_col = next((c for c in df.columns if "Market Value" in c), None)
    w_col = next(
        (c for c in df.columns if "Weight" in c and "Notional" not in c),
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
    parser: Callable[[str, str, str], pd.DataFrame]


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
    ),
    "SOXX": ETFSpec(
        ticker="SOXX",
        name="iShares Semiconductor ETF",
        issuer="iShares",
        url=_ishares_url(239705, "ishares-semiconductor-etf", "SOXX"),
        parser=parse_ishares,
    ),
    # ── Wave 2: heterogeneous single-issuer (TBD) ──────────────────
    # XLK, VGT, SKYY, WCLD, ARKK
    # ── Wave 3: family patterns (TBD) ──────────────────────────────
    # IBUY/HACK/GAMR (Amplify), FINX/SOCL/BOTZ (Global X)
}


WAVES = {
    1: ["IGV", "SOXX"],
    # 2: ["XLK", "VGT", "SKYY", "WCLD", "ARKK"],
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
        text, as_of = http_get_with_cache(t, spec.url)
        df = spec.parser(text, t, as_of)
        aum = df["etf_market_value_usd"].sum(skipna=True) / 1e9
        print(f"  -> {len(df)} equity rows, ${aum:.2f}B AUM, as_of {as_of}")
        frames.append(df)
    return pd.concat(frames, ignore_index=True)


def main(wave: int | None = None):
    if wave is None:
        # Run all defined waves
        all_frames = [run_wave(w) for w in sorted(WAVES.keys())]
        combined = pd.concat(all_frames, ignore_index=True)
        out_path = DATA_DIR / "thematic_combined.csv"
        combined.to_csv(out_path, index=False)
        print()
        print("=== Phase 1B summary (all waves) ===")
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
    wave_arg = int(sys.argv[1]) if len(sys.argv) > 1 else 1
    main(wave=wave_arg)
