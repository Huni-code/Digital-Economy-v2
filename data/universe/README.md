ETF / index holdings CSVs (raw, gitignore'd by `*_holdings_*.csv`) and the derived universe outputs (raw, filtered, manual overrides — committed).

## Manual overrides

`manual_ticker_cik_overrides.csv` — append-only sheet for ticker → CIK mappings that `company_tickers.json` doesn't cover (Phase 1C-1 fills the auto-match column; this file patches the rest). Each row must trace back to a source + reason so the override is reproducible across rebuilds:

```
ticker,cik,name,source,reason,date_added
ACN,0001467373,Accenture plc,manual,SEC CIK lookup,2026-05-12
```

Applied in Phase 1C-1 after auto-matching, before the 1C-3/4 decision.

