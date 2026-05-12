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

### D5b — Foreign filer surfacing (2026-05-12, Wave 1 발견)
- Date: 2026-05-12
- Context: Wave 1 (IGV/SOXX)에서 8개 foreign ADR 추가 (TSM, ASML,
  ARM, NXPI, ASX, NVMI, STM, UMC). 원 D5 정책 ("auto-filter via
  SEC XBRL absence") 적용 시 semi sector 분석에서 시장 핵심 4사
  (TSM, ASML, NXPI, ARM) 빠짐 → 분석 narrative 구멍.
- Rule:
  * Universe에 foreign ADR keep, `foreign_filer=1` 플래그
  * Phase 4 fetch: SEC XBRL Company Facts 시도
    - 성공 시 (ARM 등 10-K 제출 회사): 점수 계산 포함
    - 실패 시 (TSMC 등 20-F만): `no_us_filings=1`, financials NULL
  * 점수 계산: financials NOT NULL 회사만 (D5 정신 유지, 데이터
    일관성 보존)
  * Dashboard: "Foreign tech bellwethers" 섹션에 `no_us_filings=1`
    회사들 qualitative 노출 (ticker, name, mcap, sector)
- Rationale:
  * D5의 "U.S.-listed 분석"이라는 원칙은 점수 계산 단계에서 유지
  * 분석 narrative 구멍은 qualitative surface로 메움
  * ARM처럼 직접 10-K 제출하는 ADR은 자동으로 점수 포함
  * +1h 작업, ROI 높음
- Rejected: 20-F + ifrs-full XBRL parsing (옵션 B)
  * +2d 작업 비용, 7개 회사 위해 과잉
  * IFRS vs GAAP 회계 기준 차이로 tier 2 평균 노이즈 증가 위험
  * v3 idea로 백로그
- Reversal cost: low — `foreign_filer` 컬럼만 ignore하면 D5 원안 복귀.
- **Validation (2026-05-12, SKYY Wave 2):** 4 net-new foreign filers
  surfaced (SHOP / WIX / SAP / OTEX). Cloud sector analysis directly
  impacted (these companies would have been silently dropped under
  D5 original). Policy validated.

### D-ETF-Skip-Bot-Protected — Bot-protected ETF fetcher 스킵 (DEFERRED, last updated 2026-05-12)
- Status: **temporary skip**, revisit post-Wave 3
- Affected ETFs:
  * **ARKK** (added 2026-05-12): SPA, JS-rendered, legacy CSV URL 404,
    Wayback archive empty, `/api/fund/holdings/1004` exists but direct
    GET returns SPA index.html (SPA-internal auth/render).
  * **WCLD** (added 2026-05-12): Cloudflare bot challenge —
    all UA/header combinations return "Just a moment..." (JS execution
    required to solve the challenge).
- Common context: 두 ETF 모두 static HTTP fetch 불가능. 차단
  메커니즘 다르지만 (SPA vs Cloudflare) 해결책 카테고리는 동일
  (Playwright / 3rd-party / skip).
- Coverage loss estimate (validated post-Wave 3):
  * ARKK: 5-15 net unique tickers after thematic ETF overlap
  * WCLD: 10-20 net unique after SKYY overlap (60-80% estimated,
    needs Wave 3 data for validation)
- Options evaluated:
  A) Skip + revisit (selected)
  B) Playwright headless browser (+100 lines, brittle dependency)
  C) cloudscraper / anti-bot bypass packages (anti-bot arms race,
     issuer-specific, breaks when issuer changes challenge)
  D) 3rd-party API (yfinance / ETFdb, 1-7d data lag, free-tier limits)
  E) Permanent exclude
- Decision: **A for both**. Wave 3 (Amplify HACK/IBUY/GAMR, Global X
  FINX/SOCL/BOTZ) 완료 후 overlap 정량 분석으로 ARKK/WCLD 각각
  B/C/D/E 결정.
- Re-decision trigger: **Wave 3 완료 시점**
- Rationale:
  - Senior project deadline 압박, 2개 ETF 위해 brittle 의존성 도입
    ROI 낮음.
  - Cloud 테마는 SKYY로, Innovation 테마는 Wave 3 Amplify로 부분
    cover — critical narrative 구멍은 없음.
  - ARKK actively managed (D-Universe ARKK caveat 참고).
  - WCLD/SKYY 모두 passive "Cloud Computing" index, 60-80% overlap
    expected — WCLD 손실 제한적.
- Reversal cost: low — per-ETF B/C/D/E 추후 추가 가능, 1B 스크립트
  registry 구조 그대로 확장.
- **Update (2026-05-12, post-VGT)**: VGT N-PORT-P 데이터로 본
  IWV/VGT가 mid-cap IT를 광범위하게 cover. ARKK/WCLD net-new 추정치
  유지하되 (ARKK 5-15, WCLD 10-20) fetcher 작성 ROI 더 의문화됨 —
  대부분 micro-cap 가능성. Wave 3 (Amplify/Global X) 완료 후 최종
  결정. 자세한 학습은 D-Universe-Learning 참고.

### D-LLM — No LLM classification in Phase 3
- Date: 2026-05-07
- Rule: Phase 3C uses SIC + GICS rule-based mapping + manual overrides.
  No Claude API calls for classification.
- Rationale: prior LLM classification work produced data quality issues
  hard to debug. Rule-based output is auditable.
- Reversal cost: medium — would require re-running Phase 3, but
  rule-based output is preserved.

### D-Metrics — Expanded financial schema (+7 raw, +8 derived)
- Date: 2026-04-30
- Rule: Phase 4 schema gains 7 raw fields and Phase 5 gains 8 derived
  metrics, listed below.
- Raw additions (Phase 4):
  - `depreciation_amortization` — input to EBITDA
  - `stock_repurchase` — capital return; sign-normalized to positive
  - `long_term_debt` — separate from total_debt for net_debt calc
  - `retained_earnings` — distress signal input (NULL ≠ negative)
  - `ppe_net` — input to asset_turnover
  - `current_assets`, `current_liabilities` — inputs to current_ratio
- Derived additions (Phase 5):
  - `ebitda`, `ebitda_margin` — capital-structure-neutral profitability
  - `asset_turnover` — revenue / ppe_net (capital efficiency)
  - `current_ratio` — short-term liquidity
  - `net_debt` — long_term_debt − cash − short_term_investments
  - `net_dilution` — Δ shares YoY net of buybacks (SBC drag signal)
  - `buyback_yield` — stock_repurchase / market_cap
  - `zombie_flag` — binary distress gate; hard exclusion candidate.
        Locked definition (BIS-style 4-condition AND):
        `retained_earnings < 0` AND `avg(fcf, 3y) < 0` AND
        `interest_coverage < 1` AND `cash_runway_yrs < 2`.
        NULL when company has < 3 years FCF history (recent IPO);
        short-circuits to 0 for debt-free companies (no interest_expense).
        Expected catch: ~4-6% of universe.
        Rejected alternatives: 2-condition (too loose, catches all
        loss-stage SaaS); op_margin-based (non-cash adjustments distort
        burn signal); current_ratio < 1 (deferred revenue inflates
        denominator for SaaS, false positives).
- Rationale: investor-grade analysis requires margin quality (EBITDA),
  capital efficiency (asset_turnover, net_debt), shareholder-return
  posture (buyback_yield, net_dilution), and a distress filter
  (zombie_flag) — none of which existed in v1's metric set.
- D4 dependency: layer placement and weights defer to Phase 6 D4 review.
- Reversal cost: low for raw fields (already fetched, drop columns
  from queries); medium for zombie_flag if it changes from hard-
  exclusion to soft-flag (forces re-scoring).

### Rejected metric candidates — D-Metrics-Rejected
- Date: 2026-04-30
- Items considered and excluded from Phase 4/5 scope:
  - **Inventory turnover** — meaningful for hardware (Apple, Dell) but
    near-zero variance for SaaS / Internet platforms (no inventory).
    Cross-sub-sector aggregation would be misleading. Track in raw
    schema only if needed for hardware deep-dive later.
  - **OpEx breakdown (S&M, G&A separate)** — XBRL tags are inconsistent
    across filers (some bundle S&M into SG&A, some split). Reliable
    extraction requires per-filer parsing; cost > value at universe
    scale. Keep `sga_expense` as a single rolled-up field; use
    `rd_expense` separately (which IS reliably tagged).
  - **AOCI (Accumulated Other Comprehensive Income)** — affects
    book-value calculations for FX-heavy multinationals, but the
    interpretation noise (currency hedges, pension adjustments) drowns
    out signal at this universe size. Skip; `stockholders_equity`
    captures the bottom line.
- Reversal cost: low — re-add to schema if a Phase 5 metric specifically
  needs them.

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

## Observations / learnings

### D-Universe-Learning — ETF net-new ROI pattern (2026-05-12, Wave 2)
- Status: **observation**, informs Wave 3 prioritization
- Finding: IWV (Russell 3000)가 mid-cap IT를 이미 광범위하게 cover.
  Thematic ETF의 진짜 net-new 가치는 "mid-cap catch-up"이 아니라:
  (a) foreign-incorporated US-listed (D5b 케이스, e.g. Accenture / SAP)
  (b) recent IPO (Russell reconstitution lag, 연 1회)
  (c) 매우 작은 micro-cap (의문 가치, weight < 0.01%)
- Wave 2 데이터:
  * **SKYY** net new = 8 (4 foreign filer + 4 recent IPO) — 명확한 ROI
  * **VGT** net new = 11 (대부분 micro-cap < 0.01% weight) — ROI 의문
  * VGT의 진짜 가치 14 foreign-incorporated (Accenture/Seagate/NXP)
    는 Phase 1C에서 어차피 잡힘 (SEC company_tickers.json 매칭).
- Implication for Wave 3:
  * **Amplify** (HACK/IBUY/GAMR): Cybersecurity / Online Retail / Gaming
    테마 — Russell이 sector tag 약한 영역. 추가 가치 가능성 높음.
  * **Global X** (FINX/SOCL/BOTZ): Fintech는 GICS Financial로 묶여 IWV
    에 있을 가능성. Social / Robotics는 thematic 추가 가치 높음.
  * 정찰 시 "net new 추정"을 명시적 평가 기준에 포함.
  * 정찰 순서: HACK 먼저 (Amplify family 대표), FINX (Global X family
    대표) → 두 패밀리 net-new 정량 후 나머지 4개 결정.
- Implication for ARKK/WCLD re-decision:
  * WCLD (Cloud): SKYY와 60-80% overlap 가정 → net new 추정 10-20
  * ARKK (Innovation): IWV+VGT가 mid-cap 광범위 cover → net new 추정 5-15
  * 둘 다 fetcher 작성 ROI 의문이 강화됨 (D-ETF-Skip-Bot-Protected
    결정 정당성 ↑).
- Reversal cost: zero — 데이터 기반 관찰, 정책 자체는 아님.

## Deferred decisions
- D2 (taxonomy): decide at Phase 3 start
- D3 (CAGR window): decide at Phase 5 start
- D4 (score weights): decide at Phase 6 start, post-distribution review
- D6 (market cap floor): likely moot, decide if needed

## Reversed decisions
(none yet)
