# Phase 1 Milestone Report — Universe Construction

**Date:** 2026-05-12
**Status:** ✅ Complete (Phases 1A → 1B Waves 1-3 → 1C-1/3 → 1D)
**Output:** `data/universe/raw_universe.csv` — **2,621 distinct CIKs**

---

## What Phase 1 delivered

A canonical U.S. digital-economy universe assembled from primary
sources (SEC + 11 ETF holdings) with full audit trail. Every row
carries a resolved CIK and provenance information (which ETF(s)
sourced it, which method matched it to SEC, whether it's foreign-
incorporated). Phase 2 will narrow this with the Digital Economy
inclusion filter; Phase 4 will pull financials via the SEC XBRL
Company Facts API.

### Headline numbers

| | |
|---|---|
| Total source ETFs | 14 attempted, **11 successfully fetched** (3 broad indices + 8 thematic) |
| Total raw long-format rows | 4,323 across all 11 fetchers |
| Distinct tickers (deduped) | 2,665 |
| Distinct CIKs after 1C-1+1C-3 | **2,621** |
| Auto-resolved by SEC ticker map | 2,615 (98.6%) |
| Resolved via SEC EDGAR name search | 6 (1C-3 unique additions) |
| Final unmatched (excluded) | 11 (all non-digital-economy) |
| Foreign-filer flagged (CUSIP CINS) | 22 |
| ETFs deferred (D-ETF-Skip-Bot-Protected → E) | 2 (ARKK + WCLD) |

---

## Phase breakdown

### 1A — Broad indices (3 ETFs)

iShares IWV (Russell 3000) + IJH (S&P 400 Mid) + IJR (S&P 600 Small).
Single CSV parser shared across all three.

| ETF | Rows | AUM | Notes |
|---|---|---|---|
| IWV | 2,573 | $19.4B | Russell 3000 base |
| IJH | 403   | $118.4B | ~99% overlap with IWV |
| IJR | 638   | $102.3B | ~99% overlap with IWV |

**Finding:** IJH/IJR contributed only ~6 net-new tickers on top of
IWV. The S&P-vs-Russell methodology overlap is tighter in practice
than documentation suggests.

### 1B — Thematic ETFs (8 of 13 attempted)

Per-issuer fetcher patterns, all driven by one `REGISTRY` in
`pipeline/p1b_thematic_etfs.py`.

| Wave | ETFs | Pattern | Net-new vs broad |
|---|---|---|---|
| 1 | IGV, SOXX (iShares) | Same CSV pattern as 1A | 8 (all foreign ADRs: TSM, ASML, ARM, NXPI, ASX, NVMI, STM, UMC) |
| 2 | XLK (SSGA), SKYY (First Trust), VGT (Vanguard) | xlsx / HTML / SEC N-PORT-P | 28 (SKYY 8 foreign+IPO, VGT 11 micro-cap, 9 deferred) |
| 3 Amplify | HACK, IBUY, GAMR | **Single master CSV** with `Account==ticker` client-side filter | 12 (Israeli + Chinese + LatAm) |
| 3 Global X | FINX, SOCL, BOTZ | Per-fund CSV with daily date-stamped URL | 29 (heavily Chinese ADRs — BIDU/BILI/TME/XPEV/PONY etc.) |

**5 distinct fetcher patterns built and unified by a single registry:**
1. iShares CSV
2. SSGA xlsx (openpyxl)
3. First Trust HTML scrape (`pandas.read_html`, lxml)
4. Vanguard SEC N-PORT-P XML + OpenFIGI CUSIP→ticker bulk lookup
5. Amplify shared master CSV
6. Global X dated-URL CSV with day-walking fallback

### 1C — CIK resolution

| Stage | What it does | Result |
|---|---|---|
| 1C-1 | SEC `company_tickers.json` auto-match + class-share variant fallback (BRKB→BRK-B etc.) | 2,615/2,665 (98.1%) |
| 1C-2 | Classify unmatched into `foreign_cins` / `foreign_adr` / `likely_recent_ipo` / `typo_or_unknown` | 19 routed to 1C-3 |
| 1C-3 | SEC EDGAR full-text search ranked by Jaccard (token overlap) × active-CIK preference | 19/19 resolved |
| Dedup | Merge rows that 1C-1 and 1C-3 each resolved to the same CIK (Accenture/Flex/NXP came in via both ticker-bearing ETFs and VGT NULL-ticker rows) | 13 merged |

### 1D — Finalization

Quality pass over `matched_universe.csv` → renames to `raw_universe.csv`:
- CIK uniqueness verified (0 duplicates)
- Ticker uniqueness over non-null verified
- `unmatched_final.csv` non-leakage verified
- Phase 2A placeholder columns pre-created (gics_*, sic, mcap_usd, etc.)

---

## Key decisions made along the way

All locked-or-observed entries live in
[`docs/decisions.md`](decisions.md). Highlights:

- **D1** — Inclusion rule: any-1-of-3 (GICS sector OR R&D ratio OR
  10-K keyword density). Cast-wide-narrow-later.
- **D5 + D5b** — Foreign ADRs not pre-excluded; Phase 4 SEC XBRL
  availability is ground truth. `foreign_filer` column is a hint
  (CUSIP CINS-based when available).
- **D-LLM** — No LLM classification in Phase 3 (rule-based + manual,
  auditable).
- **D-Universe** — 3 broad indices + 13 thematic ETFs; documented
  ARKK active-management caveat.
- **D-Metrics** — Phase 4 schema gains 7 raw + 8 derived fields
  (EBITDA, FCF, RoIC, Rule of 40, `zombie_flag`, etc.).
- **D-ETF-Skip-Bot-Protected** — ARKK + WCLD permanently excluded
  after Wave 3 net-new evaluation showed near-zero marginal value.
- **D-Universe-Learning** — *Russell 3000 covers US tech sectors
  comprehensively. The real value of thematic ETFs is **foreign
  filer surfacing** (Israeli, Chinese, LatAm names), not US-sector
  gap-filling.* This learning shifted later wave priorities.

---

## What didn't work / known limitations

- **OpenFIGI CUSIP → ticker** has uneven CINS (foreign-incorporated)
  coverage. 19 VGT CUSIPs returned no US listing; recovered via
  Phase 1C-3 SEC EDGAR name search.
- **6 universe rows have NULL ticker** — VGT N-PORT-P holdings
  resolved by name search to CIK only. Not a blocker (Phase 2/4 use
  CIK as primary key) but worth backfilling from CIK→ticker reverse
  lookup later.
- **Global X `foreign_filer` defaults to 0** — Global X ships SEDOL
  identifiers only, no CUSIP. The CUSIP-based CINS hint can't apply.
  Phase 4 XBRL fetch is the ground truth for these rows.
- **ARKK + WCLD permanently excluded.** Marginal net-new ≈ 0 after
  full 11-ETF coverage; not worth Playwright/cloudscraper dependency.

---

## What we have committed

```
git log --oneline (Phase 1 commits)

0146e64  docs: ARKK/WCLD re-decision -> E (permanent exclude)
8b3fe72  feat(1D): finalize universe -> raw_universe.csv (2,621 distinct CIK)
7e572ed  feat(1C): ticker -> CIK mapping (1C-1 SEC + 1C-3 EDGAR name search)
0aae79a  feat(1B Wave 3 close): Global X FINX/SOCL/BOTZ + Wave 3 done
668df55  feat(1B Wave 3 Amplify): HACK + IBUY + GAMR via shared master CSV
8642508  feat(1B Wave 2): VGT via SEC N-PORT-P + OpenFIGI CUSIP->ticker
36fd171  docs: D5b validation + ARKK re-decision trigger moved to post-Wave 3
8f1ed6a  feat(1B Wave 2): SSGA XLK + First Trust SKYY fetchers
7ab48de  feat(1B-wave1): iShares thematic (IGV, SOXX) + D5b foreign filer policy
042977f  feat(1A): broad-index holdings — IWV + IJH + IJR
997d4c2  chore(phase 0): scaffold v2 — README, requirements, folder structure
844a03a  feat: add 7 buy-side raw fields and 8 derived metrics
8b5b73d  docs: lock D1/D5, expand universe to 16 sources, add .gitignore + decision log
19168eb  docs: initial v2 phase plan
```

15 commits total. Each commit message contains a concrete "what / why
/ rationale" — auditable in isolation.

---

## What Phase 2 receives

[`data/universe/raw_universe.csv`](../data/universe/raw_universe.csv)

```
columns:
  cik                  10-char zero-padded SEC CIK (primary key)
  ticker               US ticker, NULL for 6 N-PORT-P-only resolutions
  name                 issuer-reported name
  cusip                CUSIP9, populated for VGT (319) + Amplify (60)
  isin                 ISIN, populated for VGT only
  foreign_filer        0/1 CUSIP-CINS hint; ground truth is Phase 4
  source_indices       semicolon-joined ETF list (e.g. "IGV;IWV;VGT;XLK")
  match_source         audit trail: sec_auto / sec_variant:X / edgar_search:j=Y:Z / manual_override
  + 8 NULL placeholder columns for Phase 2A (gics_*, sic, market_cap_usd, etc.)
```

Phase 2 (Digital Economy inclusion filter) will:
1. Enrich with GICS sector + SIC via yfinance / SEC submissions API
2. Compute R&D ratio + 10-K keyword density
3. Apply D1 any-1-of-3 inclusion rule
4. Output `data/universe/digital_economy_universe.csv` (~800 rows
   target)

---

## Time spent (rough)

| Phase | Estimate | Actual | Notes |
|---|---|---|---|
| 0 (setup) | 0.5d | 0.5d | On |
| 1A (broad) | 1.5d | 0.5d | iShares pattern simpler than expected |
| 1B Wave 1 (IGV, SOXX) | — | 0.5d | Same CSV pattern, registry built |
| 1B Wave 2 (XLK/SKYY/VGT) | — | 1.5d | SSGA easy, First Trust HTML moderate, VGT N-PORT-P + OpenFIGI hardest |
| 1B Wave 3 (Amplify/Global X) | — | 0.5d | Shared master CSV + dated URL — both elegant |
| 1C-1 + 1C-3 + dedup | 1d | 0.5d | 99.6% match rate; few iterations on Jaccard ranking |
| 1D + ARKK/WCLD re-decision + milestone | — | 0.3d | Mostly verification |

**Phase 1 total: ~4.5 days vs original 6-7 day estimate.** Came in
under budget largely because the 1C extended staging found the gap
small (only 19 SEC name searches needed, vs hundreds anticipated).

---

## Next: Phase 2 — Digital Economy filter

Goal: 2,621 → ~800 via the locked D1 any-1-of-3 inclusion rule.

Subphases (per PHASES.md):
- 2A — Enrich with SIC + GICS Sub-Industry via SEC submissions +
  yfinance/OpenFIGI
- 2B — Apply D1 inclusion rule, record matched-conditions in
  `inclusion_reason` column
- 2C — Active-status check (drop entities with no 10-K in 18 months)
- 2D — Borderline manual review for edge cases

After Phase 2, Phase 3 (sub-sector taxonomy) and Phase 4 (XBRL
financial enrichment) follow.
