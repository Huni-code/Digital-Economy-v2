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

## Pre-Phase Decisions

### LOCKED

1. **Digital Economy definition — LOCKED: Any-1-of-3 inclusion rule.**
   - GICS Sector ∈ {Information Technology, Communication Services subset,
     Internet Retail (Cons. Disc.)}
   - OR R&D/Revenue > 5% (TTM)
   - OR 10-K Item 1 contains ≥2 of {"technology", "platform", "software",
     "digital", "data", "internet", "cloud", "AI"}
   - Each company stores `inclusion_reason` (semicolon-joined matched
     conditions, e.g., "gics;rd_ratio") for downstream review.
   - Rationale: v1 suffered from undersized Tier 2 buckets. Cast wide,
     narrow later via borderline review (Phase 2D).

5. **ADR handling — LOCKED: No explicit ADR exclusion at universe stage.**
   Foreign ADRs auto-filter in Phase 4 when SEC XBRL Company Facts API
   returns no data. Rationale: avoid premature exclusion; let data
   availability decide.

### DEFERRED (decide at the relevant phase kickoff)

2. **Sub-sector taxonomy** — defer to Phase 3 kickoff.
   - Tier 1 candidates: Software & Cloud / Hardware & Semiconductors /
     Internet & Digital Services / Fintech / Communication & Media /
     Tech-enabled Services
   - Tier 2: refined within each Tier 1, target n≥10 per bucket.

3. **CAGR window** — defer to Phase 5 (after enrichment shows actual
   year-coverage of the universe). Default candidate: 2020→2024 (v1).

4. **Score weights** — defer to Phase 6, after seeing metric distributions.
   Default candidate: v1's Learning 40 / Inventing 30 / Investing 30 with
   Investing = CAGR 40 / SFR 30 / Margin 30.

6. **Market cap floor** — defer; likely moot given Russell 3000's natural
   ~$200M floor.

---

## Phase 0 — Setup

**Goal:** Repo, env, doc skeleton.

- [x] `git init` (done)
- [x] `.gitignore` — covers caches, raw downloads, secrets; allows
      committed derived outputs
- [x] `README.md` with hook + methodology summary + install/run + status
- [x] `requirements.txt` (requests, pandas, plotly, streamlit, yfinance,
      openpyxl; sqlite3 omitted — stdlib)
- [x] Folder layout:
  ```
  digital-economy-v2/
    pipeline/         # phase scripts (p1_* … p9_*)
    data/             # universe CSVs, DB, caches
      cache/          # API response caches (gitignore'd)
      universe/       # ETF holdings (gitignore'd) + derived universe
    notebooks/        # exploration / sanity checks
    dashboard/        # Streamlit app
    docs/             # methodology, decision log, xbrl_tags, metrics
    PHASES.md         # this file
  ```
  Each subfolder has a one-line `README.md`.
- [x] `docs/decisions.md` — log every Pre-Phase decision with rationale

**Estimate:** 30 min.

---

## Phase 1 — Universe Construction

**Goal:** Produce the raw candidate list of every U.S. public company
plausibly in the Digital Economy. Cast wide; filter in Phase 2.

### 1A — Broad index holdings ✓

- [x] Download iShares **IWV** (Russell 3000) holdings CSV — 2,573 rows
- [x] Download iShares **IJH** (S&P 400 Mid-Cap) holdings CSV — 403 rows
- [x] Download iShares **IJR** (S&P 600 Small-Cap) holdings CSV — 638 rows
- [x] Save each to `data/universe/{etf}_holdings_<YYYYMMDD>.csv` (gitignored)
- [x] Parse into normalized table: ticker, name, sector_ishares,
      etf_market_value_usd, weight_pct, source_index, data_as_of
- ⚠ `etf_market_value_usd` is iShares' position size (= ETF AUM ×
  weight%), NOT the company's market cap. True company-level
  `market_cap_usd` is fetched in Phase 2A via yfinance. Naming this
  field honestly avoids a class of "why is Apple's mcap $1B?" bugs.
- Result: 3,614 long-format rows / 2,579 distinct tickers. IJH/IJR
  contributed only ~6 unique tickers on top of IWV — the Russell-vs-S&P
  methodology overlap is tighter in practice than methodology
  documentation suggests.
- Output: `data/universe/broad_indices_combined.csv` (committed).
- Script: `pipeline/p1a_broad_indices.py`. Handles two iShares CSV
  schema variants (IWV: Ticker,Name,Sector,...; IJH/IJR: Ticker,Name,
  Type,Sector,... with "Market Weight" instead of "Weight (%)") via
  permissive header detection and weight-column matching.

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
| SKYY | First Trust Cloud | First Trust | ftportfolios.com |
| HACK | Cybersecurity | ETFMG | etfmg.com |
| FINX | Fintech | Global X | globalxetfs.com |
| IBUY | Online Retail | Amplify | amplifyetfs.com |
| SOCL | Social Media | Global X | globalxetfs.com |
| GAMR | Video Games | Wedbush ETFMG | etfmg.com |
| BOTZ | Robotics & AI | Global X | globalxetfs.com |
| ARKK | ARK Innovation | ARK | ark-funds.com |

13 thematic ETFs (was 11). Excluded: QQQ (subset of mega-cap, redundant),
PAVE/IFRA (infrastructure, not tech). ARKK is **actively managed** —
universe membership drifts ~30% / year as the manager rebalances. Capture
date stamped in `source_indices` field.

- [ ] Script `pipeline/p1b_etf_holdings.py` — download all 13, parse to
      single combined CSV with `source_etf` column.
- [ ] Save to `data/universe/etf_holdings_combined.csv`.

### 1C — Ticker → CIK mapping

- [ ] Download SEC `https://www.sec.gov/files/company_tickers.json` (~13k rows)
- [ ] Cache to `data/cache/company_tickers.json`
- [ ] Build dict: ticker → (cik, name)

### 1D — Union + dedup

- [ ] Merge all 16 sources on ticker (3 broad + 13 thematic)
- [ ] Left-join CIK from 1C
- [ ] Drop rows missing CIK (likely OTC, ADR with non-standard ticker,
      newly-listed not yet in SEC ticker map)
- [ ] Output: `data/universe/raw_universe.csv` — expected ~3,500-4,000
- [ ] Columns: cik, ticker, name, sector_ishares, source_indices
      (semicolon-joined, e.g., `"IWV;IJR;IGV;WCLD"`),
      `requires_review` (0/1), `foreign_filer` (0/1, default 0; 1 if
      ticker matches known ADR pattern or Location != "United States"
      in iShares holdings CSV), data_as_of_min, data_as_of_max
- [ ] Real `market_cap_usd` is added in Phase 2A from yfinance — kept
      out of 1D so the universe file stays clearly source-attributed.
- See D5b in `docs/decisions.md` for how `foreign_filer` flows through
  Phase 4 (XBRL fetch attempted, `no_us_filings=1` on failure) and
  Phase 8 (Foreign Bellwethers qualitative section).
- [ ] **ARKK-only flag:** any company whose `source_indices` contains
      `"ARKK"` AND no broad index (IWV/IJH/IJR) AND no other thematic ETF
      → set `requires_review = 1`. Rationale: ARKK is actively managed
      and includes off-thesis names (Tesla, medical devices). These rows
      flow into Phase 2D borderline review automatically.

**Deliverable:** `raw_universe.csv` with ~3,500-4,000 candidates.
**Estimate:** 1.5 days (per-issuer ETF formats differ; ARKK / WisdomTree /
Global X may need light scraping).

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

- [ ] Generate `data/universe/borderline_review.csv` covering:
      - cases where exactly one of the 3 inclusion conditions matched
      - cases where R&D ratio is between 4-6%
      - **all rows with `requires_review = 1`** (ARKK-only inclusions
        from Phase 1D)
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

### 3C — SIC-based split for oversized GICS buckets

For GICS sub-industries containing >40 companies (Application Software,
Semiconductors, Interactive Media & Services, Data Processing & Outsourced
Services, Systems Software):

- [ ] Build secondary mapping using SIC codes already fetched in Phase 2A.
- [ ] Example: GICS "Application Software" splits via SIC into:
      - SIC 7372 (Prepackaged Software) → tier2: "Vertical SaaS" or
        "Horizontal SaaS" depending on product description
      - SIC 7389 (Business Services NEC) → tier2: "Tech-enabled Services"
- [ ] `data/universe/sic_to_subsector.csv` — manually curated mapping
      table (SIC × parent_GICS → tier2).
- [ ] No LLM use. Rule-based + manual curation only — auditable output.

### 3D — Manual override

- [ ] `data/universe/manual_subsector_overrides.csv` — (cik, tier1, tier2,
      reason).
- [ ] Expected manual review volume: 200-400 companies (cases where
      GICS+SIC rules conflict, or company is multi-segment).
- [ ] Workflow: filter raw classifications to "low_confidence" rows
      (rules disagree), batch review in spreadsheet, re-import.

**Deliverable:** Every CIK has tier1 + tier2 assigned.
**Estimate:** 1.5 days (LLM debug overhead removed).

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
    foreign_filer INTEGER,       -- 0/1, from universe (Phase 1D)
    no_us_filings INTEGER,       -- 0/1, set in Phase 4 if XBRL empty
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
    depreciation_amortization REAL,  -- D&A; needed for EBITDA
    operating_income REAL,
    interest_expense REAL,
    net_income REAL,
    -- Cash flow
    operating_cash_flow REAL,
    capex REAL,
    free_cash_flow REAL,             -- derived: OCF - CapEx
    sbc REAL,
    stock_repurchase REAL,           -- buyback dollars; sign-normalized positive
    -- Balance sheet
    cash_and_equivalents REAL,
    short_term_investments REAL,
    current_assets REAL,             -- for current_ratio
    current_liabilities REAL,        -- for current_ratio
    ppe_net REAL,                    -- net PP&E for asset_turnover
    long_term_debt REAL,             -- LT portion only; for net_debt
    total_debt REAL,                 -- LT + ST
    retained_earnings REAL,          -- accumulated profit/loss; zombie_flag input
    stockholders_equity REAL,
    shares_outstanding REAL,
    shares_outstanding_diluted REAL,
    -- Tech-specific
    deferred_revenue REAL,
    rpo REAL,
    -- Meta
    source_tag_revenue TEXT,         -- which XBRL tag was used
    source_tag_da TEXT,              -- D&A tag actually used
    source_tag_buyback TEXT,         -- repurchase tag actually used
    source_tag_ltd TEXT,             -- long_term_debt tag actually used
    source_tag_re TEXT,              -- retained_earnings tag actually used
    source_tag_ppe TEXT,             -- ppe_net tag actually used
    source_tag_ca TEXT,              -- current_assets tag actually used
    source_tag_cl TEXT,              -- current_liabilities tag actually used
    fiscal_year_end_month INTEGER,   -- 1-12, e.g., 9=Apple, 6=MSFT
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

depreciation_amortization:
  1. us-gaap:DepreciationDepletionAndAmortization
  2. us-gaap:DepreciationAndAmortization
  3. us-gaap:Depreciation + us-gaap:AmortizationOfIntangibleAssets (sum)

stock_repurchase:
  1. us-gaap:PaymentsForRepurchaseOfCommonStock
  2. us-gaap:PaymentsForRepurchaseOfEquity
  3. us-gaap:TreasuryStockValueAcquiredCostMethod (delta YoY)
  Sign rule: SEC reports buybacks as positive cash outflow under
  "investing/financing activities". Some filers use negative sign in
  XBRL. Normalize to **positive** (always treat as outflow > 0).
  Drop rows where the absolute value > 50% of revenue (likely tag misuse).

long_term_debt:
  1. us-gaap:LongTermDebtNoncurrent
  2. us-gaap:LongTermDebt
  3. us-gaap:LongTermDebtAndCapitalLeaseObligations

retained_earnings:
  1. us-gaap:RetainedEarningsAccumulatedDeficit
  2. us-gaap:RetainedEarnings
  NULL vs negative distinction: tag missing entirely → store NULL
  (likely IFRS filer or recent IPO with no R/E line). Tag present with
  negative value → store as-is (legitimate accumulated deficit, common
  for loss-stage SaaS). zombie_flag downstream uses ratio
  retained_earnings / |stockholders_equity|, so NULL bypasses the rule
  while negative triggers evaluation.

ppe_net:
  1. us-gaap:PropertyPlantAndEquipmentNet
  2. us-gaap:PropertyPlantAndEquipmentAndFinanceLeaseRightOfUseAssetAfterAccumulatedDepreciationAndAmortization

current_assets:
  1. us-gaap:AssetsCurrent

current_liabilities:
  1. us-gaap:LiabilitiesCurrent
```

### 4C — Fetch + extract

- [ ] `pipeline/p4_enrich.py` — combine v1's `phase_f_ocf.py` and
      `phase_f2_revenue_rd.py` patterns into one pass per CIK.
- [ ] Reuse v1 caches where CIK overlaps (estimate: 200-300 CIKs hit the
      v1 cache).
- [ ] Filter: form='10-K', fp='FY'; pick latest `filed` per (cik, year).
- [ ] **Fiscal year handling:** store XBRL `fy` field as-is. Do NOT
      convert to calendar year. Document in `docs/xbrl_tags.md` that all
      year columns are fiscal-year basis. Capture `fiscal_year_end_month`
      from the company's reported period end.
- [ ] **Restatement handling:** when multiple 10-Ks exist for the same
      (cik, fy), pick the one with latest `filed` date.
- [ ] **Source-tag tracking:** for every fallback-chain field, record
      which tag actually produced the value. Schema columns:
      `source_tag_revenue`, `source_tag_da`, `source_tag_buyback`,
      `source_tag_ltd`, `source_tag_re`, `source_tag_ppe`,
      `source_tag_ca`, `source_tag_cl`. Lets downstream debugging
      identify tag-mix issues without re-fetching.
- [ ] **Retained earnings handling:** distinguish three states —
      tag absent → store NULL; tag present with positive value → as-is;
      tag present with negative value (accumulated deficit) → as-is.
      Do NOT clamp to 0. zombie_flag in Phase 5 depends on the negative
      signal.
- [ ] **Stock repurchase sign normalization:** XBRL filers split between
      reporting buybacks as positive (outflow) and negative. Apply
      `abs()` and store positive. Drop the row + log if `abs() > 0.5 *
      revenue` for that year (almost certainly a tag misuse, e.g.,
      total treasury stock balance instead of period delta).
- [ ] **Foreign filer handling (D5b):**
      * `foreign_filer=1` 회사도 SEC XBRL Company Facts API fetch 시도
      * Response empty 또는 us-gaap tag 없으면 `no_us_filings=1` 마킹,
        `financials` 테이블에 row 생성 안 함
      * companies 테이블 컬럼: `no_us_filings INTEGER` (위 schema 참조)
      * Log: `"foreign filer X has no US filings, surfaced as qualitative"`
- [ ] Rate limit: 0.11s per CIK, 800 × 0.11 = ~90 seconds.

### 4D — Coverage report

- [ ] After enrichment, generate `data/coverage_report.csv`:
      per (tier2_subsector, year, metric) → count + pct of universe.
- [ ] Flag (tier2, metric) cells with <50% coverage for review.

**Deliverable:** `data/companies.db` populated.
**Estimate:** 1.5 days (was 1d; added 7 fields × tag fallback chains +
sign/NULL normalization rules).

---

## Phase 5 — Derived Metrics

**Goal:** Compute investor-grade ratios from raw financials.

- [ ] `pipeline/p5_derive_metrics.py` — adds rows to `metrics_per_company`
      table:
  - **Margins:** gross_margin, op_margin, net_margin, fcf_margin,
        **ebitda**, **ebitda_margin**
  - **Growth:** revenue_cagr (4yr), rd_cagr, op_income_cagr
  - **Efficiency:** roic, roe, rd_intensity (RD/Rev), capex_intensity,
        **asset_turnover** (revenue / ppe_net)
  - **Health:** debt_to_ebitda, interest_coverage, cash_runway_yrs,
        **current_ratio** (current_assets / current_liabilities),
        **net_debt** (long_term_debt − cash − short_term_investments)
  - **Capital return:** **net_dilution** (Δ shares_outstanding YoY adj.
        for buybacks), **buyback_yield** (stock_repurchase / market_cap)
  - **Tech-specific:** rule_of_40 (rev_growth + fcf_margin), sbc_dilution
        (SBC/MCap), magic_number (if data allows)
  - **Distress:** **zombie_flag** (binary). BIS-style 4-condition AND.
        Triggers when ALL of:
        ```
        retained_earnings < 0                # historical losses
        AND avg(fcf, last 3 years) < 0       # sustained cash burn
        AND interest_coverage < 1            # can't service debt
        AND cash_runway_yrs < 2              # imminent failure
        ```
        NULL handling:
        - Companies with < 3 years of FCF data (recent IPO) → flag = NULL,
          NOT 0. zombie_flag is meaningless without burn-trajectory history.
        - retained_earnings tag absent (IFRS filer, see 4B) → NULL.
        - interest_coverage requires interest_expense > 0; if zero/NULL
          (debt-free company), the condition is vacuously true OR the
          rule short-circuits to "not a zombie" (debt-free can't be a
          zombie by definition). Default: short-circuit to flag = 0.
        Expected catch rate: ~4-6% of universe (30-50 of ~800).
- [ ] Each metric has its own NULL handling rule documented in
      `docs/metrics.md`.
- [ ] **SaaS current_ratio caveat:** SaaS firms with large deferred
      revenue inflate current_liabilities and depress current_ratio
      artificially. Document in `docs/metrics.md` whether to compute
      an adjusted variant: `current_ratio_adj = current_assets /
      (current_liabilities − deferred_revenue)`. Decision deferred to
      Phase 5 kickoff after seeing the distribution.

**Deliverable:** `metrics_per_company` table.
**Estimate:** 1 day (was 0.5d; added 8 metrics + zombie_flag multi-year
window logic + SaaS current_ratio adjustment review).

---

## Phase 6 — Opportunity Score

**Goal:** Roll metrics into per-company → per-sub-sector scores.

### 6A — Score architecture

Likely keep v1's three-layer (Learning / Inventing / Investing) but
revisit weights in light of richer metrics.

- [ ] `docs/scoring.md` — final weight diagram with rationale.
- [ ] Per-layer: list of (metric, normalization, weight).
- [ ] 5-95th percentile clipping retained from v1.
- [ ] **D4 placement review (v2 new metrics):** decide where each of the
      Phase 5 v2 additions sits in the score architecture. Candidates:
      - ebitda_margin → Investing (profitability quality)
      - asset_turnover → Investing or Inventing (capital efficiency)
      - current_ratio → Health gate, not in score (binary pass/fail)
      - net_debt → debt_to_ebitda already covers; possibly skip
      - net_dilution → Investing (penalizes SBC abusers)
      - buyback_yield → Investing (capital return signal)
- [ ] **zombie_flag = hard exclusion.** Companies with zombie_flag = 1
      are excluded from scoring entirely (no score, dashboard tags as
      "distressed — see metrics tab"). Document threshold + override
      list in `docs/scoring.md`.

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
  - **Foreign Bellwethers** — `no_us_filings=1` companies as a
        qualitative table (ticker, name, sector, mcap). 점수 X, 정보 O.
        본 분석에서 제외된 이유 1줄 설명 (D5b 정책 링크).
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
| 0  Setup | 0.5 |
| 1  Universe | 1.5 |
| 2  Filter | 2 |
| 3  Taxonomy | 1.5 |
| 4  Enrich | 1.5 |
| 5  Metrics | 1 |
| 6  Score | 1 |
| 7  Validate | 1 |
| 8  Dashboard | 3 |
| 9  Docs | 1 |
| **Total** | **~14 days** |

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

1. ETF holdings programmatic vs manual — most issuers expose direct CSV
   URLs (iShares, SSGA, Vanguard); ARKK, WisdomTree, Global X may need
   light scraping. Build per-issuer fetcher functions.
2. yfinance reliability for GICS sub-industry — backup: OpenFIGI API.
3. Versioning — tag v2.0 at first dashboard demo.
4. Repo decision: keep v1 archived as-is, push v2 to fresh GitHub repo.

---

*Last updated: 2026-04-30*
