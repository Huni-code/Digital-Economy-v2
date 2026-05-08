# Decision Log — Mapping the U.S. Digital Economy v2

## Locked decisions

### D1 — Inclusion rule: Any-1-of-3
- Date: 2026-05-07
- Rule: company included if matches ≥1 of {GICS sector, R&D ratio >5%,
  10-K keyword count ≥2}
- Rationale: v1 had undersized Tier 2 buckets. Cast wide, narrow via
  manual borderline review.
- Reversal cost: low — re-run Phase 2 filter.

### D5 — ADR handling: implicit filter via SEC XBRL availability
- Date: 2026-05-07
- Rule: no explicit ADR exclusion at universe stage. Phase 4 SEC XBRL
  fetch naturally drops foreign-only filers.
- Rationale: avoid premature exclusion.
- Reversal cost: low.

### D-LLM — No LLM classification in Phase 3
- Date: 2026-05-07
- Rule: Phase 3C uses SIC + GICS rule-based mapping + manual overrides.
  No Claude API calls for classification.
- Rationale: prior LLM classification work produced data quality issues
  hard to debug. Rule-based output is auditable.
- Reversal cost: medium — would require re-running Phase 3, but
  rule-based output is preserved.

### D-Universe — Expanded to 16 sources
- Date: 2026-05-07
- Rule: 3 broad indices (IWV, IJH, IJR) + 13 thematic ETFs (was 11).
  Added SKYY, ARKK. Excluded QQQ (subset), PAVE, IFRA.
- Rationale (broad indices): IWV alone is an annual snapshot — Russell
  reconstitutes once per year (June FTSE Russell rebalance). S&P 400/600
  rebalance **quarterly**, so IJH/IJR catch newly-listed IPOs and
  spinoffs 6-9 months earlier. ~95% of IJH/IJR constituents already sit
  in IWV; net new ~50-100 names, but those are exactly the recently-IPO'd
  tech names we don't want to miss.
- Rationale (thematic ETFs): broad indices use GICS classification, which
  underrepresents emerging tech themes (cloud, cybersecurity, fintech).
  Thematic ETFs are curated by domain experts — using their holdings as
  a "yes-list" for category membership is cheaper than building one
  ourselves.
- Caveat (ARKK): ARK Invest is **actively managed** — Cathie Wood
  rebalances aggressively, holdings drift ~30% / year, and the fund
  includes off-thesis names (Tesla, medical devices, genomics) that are
  not digital economy. Mitigation: any company that is **ARKK-only**
  (no broad index, no other thematic ETF) gets `requires_review = 1`
  in Phase 1D and routes through Phase 2D manual review.
- Caveat (point-in-time): the v2 universe is a snapshot tied to ETF
  holdings as of one specific download date. Re-running the pipeline
  6 months later will produce a different universe. Capture date is
  stamped in `source_indices` and methodology will document it.

## Deferred decisions
- D2 (taxonomy): decide at Phase 3 start
- D3 (CAGR window): decide at Phase 5 start
- D4 (score weights): decide at Phase 6 start, post-distribution review
- D6 (market cap floor): likely moot, decide if needed

## Reversed decisions
(none yet)
