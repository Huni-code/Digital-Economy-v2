# Mapping the U.S. Digital Economy — v2

**Project:** Senior project for Calvin University, Prof. Fernando Santos
**Goal:** Build an investor-grade dashboard mapping ~800 U.S.-listed digital
economy companies with sector-level Opportunity Scores grounded in SEC XBRL
financial data.

**Why v2:** v1 started from builtin.com scraped names → SEC name matching,
which produced 50% corrupted CIK mappings and required 8 phases of cleanup.
v2 starts from CIK as primary key, uses Russell 3000 + ETF holdings as the
universe, and applies a documented Digital Economy inclusion filter.

---

## Pre-Phase Decisions (resolve before Phase 0)

These choices propagate through every later phase. Lock them in writing.

1. **Digital Economy definition** — finalize the 3-condition inclusion rule:
   - GICS Sector ∈ {Information Technology, Communication Services subset,
     Internet Retail (Cons. Disc.)}
   - OR R&D/Revenue > 5% (TTM)
   - OR 10-K Item 1 contains ≥2 of {"technology", "platform", "software",
     "digital", "data", "internet", "cloud", "AI"}
   - **Open: minimum 2-of-3 vs any-1-of-3?** (controls universe size)

2. **Sub-sector taxonomy** — Tier 1 (~6 broad) vs Tier 2 (~18 sub).
   - Tier 1 candidates: Software & Cloud / Hardware & Semiconductors /
     Internet & Digital Services / Fintech / Communication & Media /
     Tech-enabled Services
   - Tier 2: refined within each Tier 1, target n≥10 per bucket
   - **Open: keep v1's 18 sub-sectors or redesign?**

3. **CAGR window** — keep 2020→2024 (4-year) from v1, or shift to 2021→2025?

4. **Score weights** — keep v1's Learning 40 / Inventing 30 / Investing 30,
   or redesign? Within Investing keep CAGR 40 / SFR 30 / Margin 30?

5. **ADR exclusion** — confirm "U.S. companies" excludes foreign ADRs
   (Spotify, ASML, Sony). Russell 3000 is U.S.-only by construction; ETF
   supplement may include some.

6. **Market cap floor** — exclude micro-caps under $50M? Russell 3000's
   bottom decile is ~$200M so usually moot.

---

## Phase 0 — Setup

**Goal:** Repo, env, doc skeleton.

- [ ] `git init` (done)
- [ ] `README.md` with one-paragraph project summary
- [ ] `requirements.txt` (requests, pandas, sqlite3, plotly, streamlit,
      yfinance, openpyxl)
- [ ] `.gitignore` (.venv, __pycache__, data/cache/*, .env)
- [ ] Folder layout:
  ```
  digital-economy-v2/
    pipeline/         # phase scripts
    data/             # universe CSVs, DB, caches
      cache/          # API response caches (gitignore'd if large)
      universe/       # ETF holdings, raw lists
    notebooks/        # exploration / sanity checks
    dashboard/        # Streamlit app
    docs/             # methodology, decision log
    PHASES.md         # this file
  ```
- [ ] `docs/decisions.md` — log every Pre-Phase decision with rationale

**Estimate:** 30 min.

---

## Phase 1 — Universe Construction

**Goal:** Produce the raw candidate list of every U.S. public company
plausibly in the Digital Economy. Cast wide; filter in Phase 2.

### 1A — Russell 3000 holdings

- [ ] Download iShares IWV holdings CSV (free, monthly refresh)
  - URL: `https://www.ishares.com/us/products/239714/ishares-russell-3000-etf`
  - Columns kept: Ticker, Name, Sector, Market Value, Weight
- [ ] Save to `data/universe/iwv_holdings_<YYYYMMDD>.csv`
- [ ] Parse into normalized table: ticker, name, gics_sector, mcap_usd

### 1B — ETF supplement holdings

Pull holdings of 11 sector/theme ETFs to catch tech-adjacent names IWV's
sector tags miss (Fintech, Cloud, Cybersecurity, Gaming):

| Ticker | Name | Issuer | Holdings file |
|---|---|---|---|
| XLK | Technology Select | SSGA | spdrs.com |
| VGT | Vanguard IT | Vanguard | vanguard.com |
| IGV | iShares Software | iShares | ishares.com |
| SOXX | Semiconductor | iShares | ishares.com |
| WCLD | Cloud Computing | WisdomTree | wisdomtree.com |
| HACK | Cybersecurity | ETFMG | etfmg.com |
| FINX | Fintech | Global X | globalxetfs.com |
| IBUY | Online Retail | Amplify | amplifyetfs.com |
| SOCL | Social Media | Global X | globalxetfs.com |
| GAMR | Video Games | Wedbush ETFMG | etfmg.com |
| BOTZ | Robotics & AI | Global X | globalxetfs.com |

- [ ] Script `pipeline/p1b_etf_holdings.py` — download all 11, parse to
      single combined CSV with `source_etf` column.
- [ ] Save to `data/universe/etf_holdings_combined.csv`.

### 1C — Ticker → CIK mapping

- [ ] Download SEC `https://www.sec.gov/files/company_tickers.json` (~13k rows)
- [ ] Cache to `data/cache/company_tickers.json`
- [ ] Build dict: ticker → (cik, name)

### 1D — Union + dedup

- [ ] Merge IWV + ETF holdings on ticker
- [ ] Left-join CIK from 1C
- [ ] Drop rows missing CIK (likely OTC, ADR with non-standard ticker)
- [ ] Output: `data/universe/raw_universe.csv` — ~3,000-3,200 companies
- [ ] Columns: cik, ticker, name, gics_sector, mcap_usd, source_indices
      (semicolon-joined: "Russell3000;IGV;WCLD")

**Deliverable:** `raw_universe.csv` with ~3,000 candidates.
**Estimate:** 1 day.

---

## Phase 2 — Digital Economy Filter

**Goal:** Apply inclusion criteria to narrow ~3,000 → ~800.

### 2A — Enrich with SIC + GICS Sub-Industry

- [ ] For each CIK, fetch SEC submissions API
      (`https://data.sec.gov/submissions/CIK{cik}.json`):
  - sic, sicDescription
  - last 10-K filing date (for "active" check)
- [ ] Cache to `data/cache/submissions/{cik}.json`
- [ ] For GICS Sub-Industry: use yfinance `Ticker(t).info['industry']` or
      OpenFIGI API. yfinance is free but flaky — retry logic needed.

### 2B — Inclusion rule application

Apply the locked rule (see Pre-Phase Decision 1). Each company gets
`inclusion_reason` field documenting which condition(s) matched.

- [ ] `pipeline/p2_apply_filter.py`
  - Load raw_universe.csv
  - For each row, evaluate all 3 conditions
  - Mark include/exclude + reason

### 2C — Active status check

- [ ] Filter out companies whose last 10-K is older than 18 months (delisted /
      defunct).

### 2D — Borderline manual review

- [ ] Generate `data/universe/borderline_review.csv` for cases where exactly
      one condition matched, or where R&D ratio is between 4-6%.
- [ ] User reviews, marks `manual_decision` column with include/exclude.
- [ ] Apply manual decisions back to universe.

**Deliverable:** `data/universe/digital_economy_universe.csv` — ~800 CIKs.
**Estimate:** 2 days (most of it is yfinance/manual review).

---

## Phase 3 — Sub-sector Taxonomy

**Goal:** Assign each of ~800 companies to one Tier 1 broad sector and one
Tier 2 sub-sector. Goal: every Tier 2 has n≥10 (statistical floor).

### 3A — Define taxonomy

- [ ] Lock Tier 1 list (~6) and Tier 2 list (~18-20) in `docs/taxonomy.md`.
- [ ] For each Tier 2: write a 1-sentence inclusion rule + 3 example companies.

### 3B — GICS Sub-Industry → our taxonomy mapping

- [ ] Build `data/universe/gics_to_subsector.csv`:
      gics_sub_industry, our_tier1, our_tier2
- [ ] Most GICS sub-industries map 1:1; some (e.g., "Application Software")
      need split — handled in 3C.

### 3C — LLM-assisted split for ambiguous GICS buckets

For oversized GICS buckets (Application Software ~80 companies in one
bucket), use Claude API to classify each company by 10-K Item 1 + product
description into our finer Tier 2.

- [ ] `pipeline/p3c_llm_classify.py` — fetch 10-K Item 1 (first 1000 tokens),
      send to Claude, get JSON {tier1, tier2, confidence}
- [ ] Cost estimate: 80 companies × $0.01/call = $1
- [ ] Cache responses to `data/cache/llm_classifications.json`

### 3D — Manual override

- [ ] `data/universe/manual_subsector_overrides.csv` — list of (cik,
      tier1, tier2, reason) for cases where automation was wrong.

**Deliverable:** Every CIK has tier1 + tier2 assigned.
**Estimate:** 2 days.

---

## Phase 4 — Financial Enrichment (XBRL)

**Goal:** Pull all Tier 1-3 metrics from SEC XBRL Company Facts API for
each of ~800 CIKs.

### 4A — Schema

```sql
CREATE TABLE companies (
    cik TEXT PRIMARY KEY,
    ticker TEXT,
    name TEXT,
    gics_sector TEXT,
    gics_industry_group TEXT,
    gics_sub_industry TEXT,
    sic TEXT,
    sic_description TEXT,
    tier1_sector TEXT,
    tier2_subsector TEXT,
    market_cap_usd REAL,
    employees INTEGER,
    inclusion_reason TEXT,
    in_russell_3000 INTEGER,
    source_indices TEXT,
    last_10k_date TEXT
);

CREATE TABLE financials (
    cik TEXT,
    year INTEGER,
    -- Income statement
    revenue REAL,
    cost_of_revenue REAL,
    gross_profit REAL,
    rd_expense REAL,
    sga_expense REAL,
    operating_income REAL,
    interest_expense REAL,
    net_income REAL,
    -- Cash flow
    operating_cash_flow REAL,
    capex REAL,
    free_cash_flow REAL,        -- derived
    sbc REAL,
    -- Balance sheet
    cash_and_equivalents REAL,
    short_term_investments REAL,
    total_debt REAL,
    stockholders_equity REAL,
    shares_outstanding REAL,
    shares_outstanding_diluted REAL,
    -- Tech-specific
    deferred_revenue REAL,
    rpo REAL,
    -- Meta
    source_tag_revenue TEXT,    -- which XBRL tag was used
    PRIMARY KEY (cik, year)
);
```

### 4B — Tag fallback chains

Document in `docs/xbrl_tags.md`. Examples:
```
revenue:
  1. us-gaap:Revenues
  2. us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax
  3. us-gaap:SalesRevenueNet

operating_cash_flow:
  1. us-gaap:NetCashProvidedByUsedInOperatingActivities
  2. us-gaap:NetCashProvidedByOperatingActivities
  3. us-gaap:NetCashProvidedByUsedInOperatingActivitiesContinuingOperations

capex:
  1. us-gaap:PaymentsToAcquirePropertyPlantAndEquipment
  2. us-gaap:PaymentsToAcquireProductiveAssets

sbc:
  1. us-gaap:ShareBasedCompensation
  2. us-gaap:AllocatedShareBasedCompensationExpense

cash_and_equivalents:
  1. us-gaap:CashAndCashEquivalentsAtCarryingValue
  2. us-gaap:CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents
```

### 4C — Fetch + extract

- [ ] `pipeline/p4_enrich.py` — combine v1's `phase_f_ocf.py` and
      `phase_f2_revenue_rd.py` patterns into one pass per CIK
- [ ] Reuse v1 caches where CIK overlaps (estimate: 200-300 CIKs hit the
      v1 cache)
- [ ] Filter: form='10-K', fp='FY'; pick latest `filed` per (cik, year)
- [ ] Rate limit: 0.11s per CIK, 800 × 0.11 = ~90 seconds

### 4D — Coverage report

- [ ] After enrichment, generate `data/coverage_report.csv`:
      per (tier2_subsector, year, metric) → count + pct of universe.
- [ ] Flag (tier2, metric) cells with <50% coverage for review.

**Deliverable:** `data/companies.db` populated.
**Estimate:** 1 day.

---

## Phase 5 — Derived Metrics

**Goal:** Compute investor-grade ratios from raw financials.

- [ ] `pipeline/p5_derive_metrics.py` — adds rows to `metrics_per_company`
      table:
  - **Margins:** gross_margin, op_margin, net_margin, fcf_margin
  - **Growth:** revenue_cagr (4yr), rd_cagr, op_income_cagr
  - **Efficiency:** roic, roe, rd_intensity (RD/Rev), capex_intensity
  - **Health:** debt_to_ebitda, interest_coverage, cash_runway_yrs
  - **Tech-specific:** rule_of_40 (rev_growth + fcf_margin), sbc_dilution
        (SBC/MCap), magic_number (if data allows)
- [ ] Each metric has its own NULL handling rule documented in
      `docs/metrics.md`

**Deliverable:** `metrics_per_company` table.
**Estimate:** 0.5 day.

---

## Phase 6 — Opportunity Score

**Goal:** Roll metrics into per-company → per-sub-sector scores.

### 6A — Score architecture

Likely keep v1's three-layer (Learning / Inventing / Investing) but
revisit weights in light of richer metrics.

- [ ] `docs/scoring.md` — final weight diagram with rationale.
- [ ] Per-layer: list of (metric, normalization, weight).
- [ ] 5-95th percentile clipping retained from v1.

### 6B — Per-company score

- [ ] `pipeline/p6_score.py`
- [ ] Re-weighting when a metric is missing (v1 pattern).
- [ ] Output: `company_scores` table.

### 6C — Sub-sector aggregation

- [ ] Median per Tier 2.
- [ ] Tier 1 = weighted average of constituent Tier 2 (weight by n_scored).
- [ ] `insufficient_data=1` flag when n_scored < 10 (raised from v1's 5).

### 6D — Dashboard hooks

- [ ] Final tables: `subsector_scores`, `tier1_scores`,
      `company_scores_with_rank`.

**Deliverable:** Score tables ready for dashboard consumption.
**Estimate:** 1 day.

---

## Phase 7 — Validation

**Goal:** Confirm the universe + scores hold up to scrutiny.

### 7A — Bellwether check (200 canonical)

- [ ] Expand v1's 120-company list to 200, covering all 18-20 Tier 2 buckets.
- [ ] For each: confirm CIK present, financials present, sub-sector
      classification correct.
- [ ] Target: ≥98% precision (v1 hit 98% on 120).

### 7B — Coverage gates

- [ ] Every Tier 2 has n≥10 → no INSUFFICIENT flag at Tier 2 level.
- [ ] If any Tier 2 < 10, decide: merge into adjacent Tier 2, or accept
      INSUFFICIENT and note in dashboard.

### 7C — Outlier sanity

- [ ] Top/bottom 5 per metric per Tier 2 — manual eyeball for obvious
      data errors.
- [ ] Specifically watch for: negative revenue (data error), CAGR > 200%
      (probably IPO year), FCF margin < -100% (deep loss-stage)

### 7D — Sub-sector spot-check

- [ ] Pick 3 random companies per Tier 2; verify name, ticker, GICS, our
      classification, and 2-3 financial values against the live 10-K.

**Deliverable:** `docs/validation_report.md`.
**Estimate:** 1 day.

---

## Phase 8 — Dashboard

**Goal:** Streamlit app investors / professors can navigate.

### 8A — Architecture

- [ ] Multi-page Streamlit (st.Page + st.navigation) — cleaner than v1's
      single 1500-line dashboard.py.
- [ ] Pages:
  - **Home / Hero** — one-paragraph thesis, headline numbers.
  - **Universe Explorer** — searchable table, filter by Tier 1/2, MCap, etc.
  - **Sector Deep Dive** — per Tier 1, charts: revenue mix, growth, FCF,
        Rule of 40, score decomposition.
  - **Company Drill-Down** — pick a CIK, see all metrics + 4-yr trend.
  - **Methodology** — universe rules, taxonomy, score formulas, data
        caveats.

### 8B — Reusable charts

- [ ] Adapt v1's Plotly chart functions (sector ranking, growth scatter,
      etc.) into `dashboard/charts.py`.

### 8C — Caching

- [ ] `@st.cache_data` on DB loads.
- [ ] Cache bust via constant `CACHE_VERSION = "v2-2026-05"` in load
      function.

### 8D — Mobile-friendly check

- [ ] Test on phone-width viewport. Charts must not overflow.

**Deliverable:** `streamlit run dashboard/app.py` ready for demo.
**Estimate:** 3 days.

---

## Phase 9 — Documentation & Demo

- [ ] `README.md` — install + run instructions.
- [ ] `docs/methodology.md` — full pipeline write-up (this file is the
      design; methodology.md is the *executed* version with actual numbers).
- [ ] `docs/data_caveats.md` — known limitations: foreign IFRS filers,
      pre-2018 ASC 606 issues, RPO sparsity, etc.
- [ ] `docs/decisions.md` — final decision log.
- [ ] Demo script — 5-minute walkthrough for class presentation.

**Estimate:** 1 day.

---

## Total Estimate

| Phase | Days |
|---|---|
| 0  Setup | 0.1 |
| 1  Universe | 1 |
| 2  Filter | 2 |
| 3  Taxonomy | 2 |
| 4  Enrich | 1 |
| 5  Metrics | 0.5 |
| 6  Score | 1 |
| 7  Validate | 1 |
| 8  Dashboard | 3 |
| 9  Docs | 1 |
| **Total** | **~12 days** |

Solo + part-time: ~3-4 calendar weeks. Cut Phase 8 to MVP (2 pages) if
deadline pressure.

---

## Salvage from v1

These v1 assets carry over directly — no rewrite needed:

- **`pipeline/phase_f_ocf.py`** — XBRL fetch + extract pattern. Adapt for
  Phase 4.
- **`pipeline/phase_f2_revenue_rd.py`** — same.
- **`pipeline/phase_g_opportunity.py`** — score logic. Adapt for Phase 6.
- **Caches** — `data/ocf_cache.json`, `data/revenue_rd_cache.json`,
  `data/sic_cache.json`, `data/company_tickers.json`. Copy to v2's
  `data/cache/` to skip re-fetching ~300 overlapping CIKs.
- **`dashboard.py`** — Plotly chart functions, methodology copy.

Drop everything else from v1.

---

## Open Questions / TBD

1. ETF holdings download — is there a programmatic API or do we manually
   download CSVs each time? iShares has direct CSV URLs; some others need
   scraping.
2. yfinance reliability for GICS — backup plan if it rate-limits.
3. LLM classification cost ceiling — set hard $5 budget for Phase 3C?
4. Versioning strategy — tag v2.0 at first dashboard demo, then v2.1+.
5. Should the v1 repo stay as `Mapping-the-U.S.-Digital-Economy` and v2
   be a fresh repo (this folder), or rename v1 to `-v1` and make v2
   the canonical? Decision: keep v1 repo as-is for archive, push v2 to
   a new GitHub repo.

---

*Last updated: 2026-04-30*
