"""
Shared utilities used by Phase 1 fetchers/parsers.

Three issuer-agnostic primitives that show up everywhere:
  - normalize_weight_pct: float-out the weight cell regardless of '%' /
    comma / dollar / whitespace garnish.
  - normalize_currency:   float-out a market-value cell with '$' / ','.
  - is_valid_equity_ticker: ticker pattern check used to drop cash
    sweeps, FX overlays, futures, and other non-equity rows that ETF
    holdings files sometimes carry.

These don't depend on requests/openpyxl/lxml so importing this module
is cheap and side-effect free.
"""

from __future__ import annotations

import re

import pandas as pd

# Letters-only, 1-5 chars. Real US-listed equity tickers in our universe
# are alphabetic; class suffixes (BRK.B, BF.B) get normalized in Phase 1C
# from SEC's company_tickers.json, not from raw ETF holdings.
#
# Catches the non-equity rows seen in the wild:
#   "-"      iShares / SSGA cash sweep, US dollar overlay
#   "$USD"   First Trust cash overlay
#   "IXTM6"  SSGA sector futures (digit fails the [A-Z]-only class)
_TICKER_RE = re.compile(r"^[A-Z]{1,5}$")


def normalize_weight_pct(value) -> float | None:
    """Weight cell → float (in percent units, no % suffix).

    Accepts already-numeric, or strings like '14.49121', '0.075040',
    '6.89%', ' 6.89 % ', '$1.23' (defensive against tag mix-ups).
    Returns None for empty/NaN/unparseable input.
    """
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    s = str(value).strip().rstrip("%").lstrip("$").replace(",", "").strip()
    if not s:
        return None
    try:
        return float(s)
    except ValueError:
        return None


def normalize_currency(value) -> float | None:
    """Currency cell → float (USD). Strips '$' and ',', tolerates int/float."""
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    s = str(value).strip().lstrip("$").replace(",", "").strip()
    if not s:
        return None
    try:
        return float(s)
    except ValueError:
        return None


def is_valid_equity_ticker(ticker) -> bool:
    """True iff `ticker` is a 1-5 letter all-caps symbol.

    Drops the standard set of ETF-holdings non-equity placeholders:
    '-', '$USD', 'CASH', futures contracts with digits, etc.
    """
    if ticker is None or (isinstance(ticker, float) and pd.isna(ticker)):
        return False
    return bool(_TICKER_RE.match(str(ticker).strip()))
