# Changelog

## 0.2.1 — 2026-10-23

### Fixed
- An unreachable literature database (offline, or a sandbox that blocks PubMed) no longer looks
  like "no papers exist". `search` now fails with `LITERATURE_UNREACHABLE`; with `--db`, the answer
  is labelled "literature search failed" and the model is not told that nothing was found. Results
  with an unreachable source are listed in `unavailable` and are not cached.

## 0.2.0 — 2026-10-23

### Added
- **Literature grounding** for `ask` and `run`: `--db pubmed|europepmc`, `--dates 1y|5y|10y|all`
  (strict), `--papers auto|N` (auto = the 25 best matches, 8 with abstracts).
- **Follow-ups** with `--after <run>`: each model gets its own earlier answers (never another
  model's), capped at 12 messages / 24,000 characters; models that missed an earlier question
  are told what it was. Runs are chained through `run.json`.
- **Full-text citation check**: when a paper's abstract doesn't name the claim, its open full
  text is checked (Europe PMC, then NCBI PubMed Central). Papers older than the date range are
  flagged.
- `INSUFFICIENT_CREDITS` error, retried like other transient errors.
- `docs/SYSTEM_DESIGN.md`, this changelog, and behaviour evals in the `claude plugin eval` format.

### Changed
- Grounding, citation checking and the judge rubric are now the website's own modules
  (`grounding.py`, `literature_service.py`, `agent_service.py`), copied byte for byte by
  `sync_from_backend.sh`; a test fails if they drift. The research prompt is generated from the
  website's prompts.
- Models updated to the website's 23.
- Thinking is always on: Claude uses adaptive thinking at effort `high`.
- A saved citation result from an older checker version is re-checked instead of reused.

### Removed
- `literature.py` and `rubric.py` (replaced by the shared modules), `evals/prompts.json`
  (replaced by `evals/<case>/`).

## 0.1.0

First version: compare up to 5 models, verify citations against PubMed, Crossref and DataCite,
blinded judge, candidate profiles, markdown and browser reports.
