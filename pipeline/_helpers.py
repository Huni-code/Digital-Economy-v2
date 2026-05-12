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

import os
import re
import time

import pandas as pd
import requests

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


# Currency codes / words that appear as "holdings" entries in some ETF
# master CSVs (Amplify ships e.g., "KRW / SOUTH KOREA WON 0.00%" alongside
# equity rows). Drop these — they're cash/FX overlay, not equity exposure.
_CURRENCY_KEYWORDS = (
    # 3-letter ISO codes (only check as whole word to avoid false hits)
    "USD", "EUR", "GBP", "JPY", "KRW", "CNY", "HKD", "CHF",
    "CAD", "AUD", "SGD", "TWD", "INR", "BRL", "MXN", "RUB",
    "ZAR", "TRY", "SEK", "NOK", "DKK", "ILS", "PLN", "NZD",
    # English currency names
    "DOLLAR", "YEN", "WON", "EURO", "POUND",
    "YUAN", "RUPEE", "PESO", "REAL", "RAND", "FRANC",
)


def is_currency_placeholder(name) -> bool:
    """True iff `name` looks like a currency / cash-overlay placeholder.

    Catches rows like:
      "KRW / SOUTH KOREA WON"
      "US DOLLAR"
      "JPY YEN"
    These trip the ticker regex (3 caps letters) but carry zero analytical
    value — they're FX overlays the ETF holds for currency hedging.
    """
    if name is None or (isinstance(name, float) and pd.isna(name)):
        return False
    upper = str(name).upper()
    # Word-boundary-ish: split on non-alpha and check tokens
    tokens = re.split(r"[^A-Z]+", upper)
    return any(t in _CURRENCY_KEYWORDS for t in tokens if t)


def is_foreign_cins(cusip) -> bool:
    """True iff `cusip` starts with an alphabetic character.

    The first character of a CUSIP indicates incorporation jurisdiction
    when the security uses CINS (CUSIP International Numbering System):
      G — Cayman Islands / Channel Islands / Ireland / UK / Bermuda
      M — Israel
      N — Netherlands
      Y — Singapore
      (other letters less common)

    US-incorporated equities have CUSIPs starting with a digit. So
    alpha-first ⇒ foreign incorporation, even when the security trades on
    a US exchange (e.g., Accenture PLC ACN on NYSE has CUSIP G1151C101).
    This is the canonical hint for the D5b `foreign_filer` flag when CUSIP
    is available; absent CUSIP, defaults to False (caller can use other
    heuristics like ADR-pattern matching or Location field).
    """
    if cusip is None or (isinstance(cusip, float) and pd.isna(cusip)):
        return False
    s = str(cusip).strip()
    return bool(s) and s[0].isalpha()


# ────────────────────────────────────────────────────────────────────
# OpenFIGI — CUSIP → ticker lookup (used by SEC N-PORT-P parser)
# ────────────────────────────────────────────────────────────────────
# Anonymous tier:  5  req/min, 10  jobs/request → ~50 jobs/min
# With API key:    250 req/min, 100 jobs/request (set OPENFIGI_API_KEY env var)

OPENFIGI_MAPPING_URL = "https://api.openfigi.com/v3/mapping"

# Preferred US-listing exchCode set (NYSE, NASDAQ, NYSE Arca, NYSE American).
# OpenFIGI's exchCode for the main US tape is "US" on consolidated quote;
# individual exchanges show as UN/UQ/UR/UA. We accept all of these.
_US_LISTING_EXCH_CODES = {"US", "UN", "UQ", "UR", "UA", "UF", "UV", "UW"}
_EQUITY_SECURITY_TYPES = {
    "Common Stock", "Class Stock", "ADR", "REIT",
    "Depositary Receipt", "Common", "Equity",
}


def _pick_ticker_from_data(entries: list[dict]) -> str | None:
    """OpenFIGI returns multiple identifier records per CUSIP (different
    venues, class variants). Return only US-listed equities; otherwise
    None.

    NO foreign-exchange fallback. Some CUSIPs (e.g. Cayman-incorporated
    dual-listed names like Confluent / 20717M103) return only foreign
    venue records (Frankfurt 8QR, Xetra CFLTEUR). Accepting those would
    write non-US tickers into the universe and break Phase 1C's SEC
    ticker→CIK lookup. Better to leave them unresolved and let
    `unmatched_cusips.csv` capture them for D5b foreign-filer review.
    """
    if not entries:
        return None
    # Pass 1: US listing + equity-like security
    for e in entries:
        if (e.get("exchCode") in _US_LISTING_EXCH_CODES
                and e.get("securityType") in _EQUITY_SECURITY_TYPES
                and e.get("ticker")):
            return e["ticker"]
    # Pass 2: any US listing with a ticker (covers some REIT / ADR
    # records OpenFIGI tags with non-canonical securityType strings)
    for e in entries:
        if e.get("exchCode") in _US_LISTING_EXCH_CODES and e.get("ticker"):
            return e["ticker"]
    return None


def lookup_cusip_batch(
    cusips: list[str],
    api_key: str | None = None,
    timeout: int = 30,
) -> dict[str, str | None]:
    """Batch-map CUSIPs to US tickers via OpenFIGI.

    Returns a dict[cusip → ticker | None]. Missing/unresolved CUSIPs map
    to None (caller decides whether to log them).

    Rate-limit handling:
      - Without api_key: 10 jobs/request, ~12-second spacing (5 req/min).
      - With api_key:    100 jobs/request, ~0.25-second spacing (250 req/min).
    On HTTP 429, sleeps 10 s and retries (up to 3 attempts per batch).
    """
    if not cusips:
        return {}

    api_key = api_key or os.environ.get("OPENFIGI_API_KEY")
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["X-OPENFIGI-APIKEY"] = api_key
        batch_size = 100
        sleep_between = 60 / 250  # 0.24s
    else:
        batch_size = 10
        sleep_between = 60 / 5  # 12s
        print(
            "  [openfigi] no OPENFIGI_API_KEY env var; running anonymous "
            f"(10 jobs/req, 12s spacing). {len(cusips)} CUSIPs -> "
            f"~{(len(cusips) / 10) * 12:.0f}s estimated."
        )

    # Dedup while preserving order; CUSIP queries are deterministic.
    unique = list(dict.fromkeys(cusips))

    results: dict[str, str | None] = {}
    for i in range(0, len(unique), batch_size):
        batch = unique[i:i + batch_size]
        payload = [{"idType": "ID_CUSIP", "idValue": c} for c in batch]

        data = None
        for attempt in range(3):
            try:
                r = requests.post(
                    OPENFIGI_MAPPING_URL,
                    headers=headers,
                    json=payload,
                    timeout=timeout,
                )
                if r.status_code == 429:
                    time.sleep(10)
                    continue
                r.raise_for_status()
                data = r.json()
                break
            except Exception as e:
                if attempt == 2:
                    print(f"  [openfigi] batch {i}-{i + len(batch)} failed: {e}")
                else:
                    time.sleep(2 ** attempt)

        if data is None:
            for c in batch:
                results[c] = None
            time.sleep(sleep_between)
            continue

        # Responses arrive in the same order as the request payload.
        for cusip, resp in zip(batch, data):
            entries = resp.get("data") or []
            results[cusip] = _pick_ticker_from_data(entries)

        time.sleep(sleep_between)

    # Expand back to caller's input order (handles input duplicates).
    return {c: results.get(c) for c in cusips}
