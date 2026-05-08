# Mapping the U.S. Digital Economy

What's the next great tech sector — and which companies in it deserve a
closer look? This project ranks ~800 U.S.-listed digital-economy companies
across 18-20 sub-sectors and surfaces the ones with the strongest combined
growth, cash-generation, and capital-efficiency profile, all grounded in
SEC filings rather than analyst estimates.

The output is a Streamlit dashboard you can sort, filter, and drill into:
sector-level Opportunity Scores at the top, individual company financials
with 4-year trends underneath, and a methodology page that documents
every choice the score depends on.

---

## Methodology summary

- **Universe:** the union of three broad indices (Russell 3000 via
  iShares IWV, S&P 400 Mid-Cap via IJH, S&P 600 Small-Cap via IJR) plus
  13 thematic tech ETFs (XLK, VGT, IGV, SOXX, WCLD, SKYY, HACK, FINX,
  IBUY, SOCL, GAMR, BOTZ, ARKK). The thematic supplement catches modern
  tech themes — cybersecurity, cloud, fintech — that broad-index GICS
  classification underrepresents. CIK is the primary key throughout;
  no name-matching games.
- **Digital Economy filter:** any company satisfying ≥1 of three
  conditions — GICS sector match, R&D / revenue > 5%, or 10-K Item 1
  keyword density — flows into Phase 2. Borderline cases route to
  manual review. ~3,500-4,000 raw candidates → ~800 included.
- **Financials:** SEC XBRL Company Facts API. 4-5 years of revenue,
  R&D, OCF, CapEx, SBC, debt, equity, shares outstanding, and tech-
  specific items (deferred revenue, RPO). Tag fallback chains documented
  in [docs/xbrl_tags.md](docs/xbrl_tags.md). No paid data feeds.
- **Derived metrics:** EBITDA, FCF margin, Rule of 40, asset turnover,
  net debt, net dilution, buyback yield, plus a BIS-style `zombie_flag`
  for distress filtering.
- **Scoring:** three-layer Opportunity Score — Learning (40%) /
  Inventing (30%) / Investing (30%) — with the Investing layer
  combining Revenue CAGR, Self-Funding Ratio, and Cash Margin.
  Distribution-aware normalization (5th–95th percentile clip).

Every locked decision lives in [docs/decisions.md](docs/decisions.md);
the full build plan is in [PHASES.md](PHASES.md).

---

## Install / run

Python 3.11+.

```bash
git clone https://github.com/Huni-code/Digital-Economy-v2.git
cd Digital-Economy-v2

python -m venv .venv
.venv\Scripts\activate          # Windows
# source .venv/bin/activate     # macOS / Linux

pip install -r requirements.txt
```

To rebuild the database from scratch (one-time, ~30 minutes including
SEC API rate limits):

```bash
python pipeline/p1_universe.py
python pipeline/p2_filter.py
python pipeline/p3_classify.py
python pipeline/p4_enrich.py
python pipeline/p5_metrics.py
python pipeline/p6_score.py
```

To launch the dashboard:

```bash
streamlit run dashboard/app.py
```

---

## Project status

**Phase 0 — setup.** Repository scaffolding in place; pipeline and
dashboard not yet implemented. Detailed roadmap with deliverables and
estimates in [PHASES.md](PHASES.md).

---

## Author

Sunghun (Huni) Kim
Senior Project, Fall 2026
Calvin University · Advisor: Prof. Fernando Santos
