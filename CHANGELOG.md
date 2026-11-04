# Changelog

## 0.2.4 — 2026-11-04

### Added
- **Latest preprints in the conclusion** (shared with the website). `compare` and `run` search
  bioRxiv, medRxiv and other servers (via Europe PMC, last 24 months) for each candidate the models
  named, and for RNAs that recent preprints on the topic study but no model named. A preprint
  counts only if its title or abstract names the candidate and the question's main topic terms. They appear in
  report.md and the browser view as "Latest preprints (not peer-reviewed)", by ID (`P1`, `P2`…),
  with a link to the journal version when one exists. The verdict says which support or contradict
  a candidate. Every preprint comes from OmniMed's search, never from a model. `--no-preprints`
  skips it; an outage is reported as unknown, not as "none".
- **"Test first"** in the conclusion: for each candidate to test, direction (mimic / inhibitor),
  model system, readout and main risk, marked as suggestions, not validated results.

### Changed
- **Models get peer-reviewed papers only.** Europe PMC grounding (`--db europepmc`) now excludes
  preprints, which go to the conclusion instead, labelled.
- **No limits on what a model writes or thinks** (shared with the website). No thinking cap on
  Qwen or Command A+; output ceilings raised (32,768, Gemini 65,536; a model with a lower maximum,
  like Qwen 3.8 on Groq at 16,384, is retried at its own maximum); timeout 10 minutes; follow-ups
  resend each model's earlier answers in full, the whole conversation; abstracts are no longer cut
  at 700 characters.
- **Models get no answer format.** They used to receive a 450-word research prompt (question
  tiers, a fixed candidate template), which made every answer look alike. Now they are told only how
  to cite, so the citation checker can read it (`omnimed.py prompt` shows it); each model answers in
  its own words and structure. The papers list (with `--db`) and follow-up history are unchanged.
  `reference/research-prompt.md` is gone, and `sync_from_backend.sh` no longer generates it.
- **Every added instruction is cut to the minimum** (shared with the website): the citation rule is
  one sentence; the papers list is introduced by one line ("the user did not write or see this
  list; cite any that are relevant") plus the date rule; a model joining mid-chat is told only the
  earlier questions. Longer wording was reshaping answers away from what each model gives on its own.
- **One judge for every answer** in a comparison, from a provider none of the compared models come
  from, as on the website. Each answer used to get its own judge, so scores side by side came from
  different reviewers and were not comparable. A kept score from another judge is re-judged.

- **The conclusion is about the candidates:** which ones the models agreed and disagreed on, and which
  2–4 to test first in the lab (direction, model system, readout). Citation problems stay in each
  answer's box and the scoreboard.
- **Claude is the judge** (`--judge host`, what the skill now uses), at no API cost: it scores every
  answer blind, from an anonymised, shuffled packet (`judge_packet.md`), and `add-scores` records
  the scores. A Claude answer also gets a GPT-5.5 score, since Claude may favour its own style even
  unnamed; it shows the average, and the report gives both numbers. No other model judges.
- For `--judge auto` (API judge, outside the skill's workflow), a judge is never from the same maker
  as an answer (GPT-OSS counts as OpenAI), and a failing judge falls back to the next.
- Problems are listed at the end of each answer instead of above it; wide tables in an answer scroll.
- Gemini's output ceiling is 32,768 tokens (was 8,192), shared with its thinking.

### Fixed
- **Numbered reference lists were not checked at all.** A model given papers cites them as
  "[4]" and lists the full references at the end, which carry no PMID — so the answer was
  reported as "No citations" and the most careful citer in a run scored the same as one that
  cited nothing. Reference entries are now resolved by title (the strongest key there is),
  falling back to author and year, and get the same support check as a PMID. On a real
  answer this went from 0 to 11 citations checked, all resolved to the right paper, one of
  which turned out to be **retracted**. A found paper must match the cited title closely
  (0.80) or it is reported as unconfirmed: author and year alone had matched a miR-132
  inhibitor reference to an unrelated lncRNA paper by the same author. A title PubMed does
  not index is reported as unconfirmed, never as fabricated. Checker version 8.
- **A candidate a model named was reported as "named by no model".** Only the first
  8 candidates get a preprint search of their own, and the same cut was applied to the list
  used to decide what counts as new, so a candidate ranked 9th or lower (miR-29 in a real
  run) came back as found only in preprints. Every candidate a model named now counts as known.
- **Initials and study words were matched as gene symbols.** Two-letter capitals and words
  like LGBTQ, WGS and MDR were read as genes, so a citation was reported as off-topic with
  the reason "the paper concerns LGBTQ". Gene symbols now need three characters, and the
  known non-genes are listed. In a real answer this removed 4 false off-topic verdicts
  (reported as unchecked instead) and kept both genuine ones. Checker version 7.
- **A real DOI cited for the wrong paper passed.** Crossref gives a DOI only a title, and the
  checker does not judge a claim on a title alone, so a DOI for an inclisiran trial cited for a
  miR-132 drug was reported as fine. DOI citations are now looked up in PubMed for their abstract
  and checked like PMIDs. Checker version 6.
- **Literature search kept off-topic papers.** "micro RNA and long non coding RNAs … cardiovascular
  disease" required every word in a paper, and when nothing matched, dropped the topic before a
  typo, leaving one oral-cancer paper. RNA classes now form one OR term (`(lncRNA OR microRNA)`),
  more filler words are ignored, and the topic words come first so they are dropped last.
- **Citations under a candidate's title line** ("1. **miR-21 — miRNA**", then "- Synergy:
  complements miR-29 … [PMID]") were checked against the other RNA on the line alone, so correct
  papers were reported as off-topic (12 of DeepSeek's 12 in one run; 6 were real errors). The title
  now joins every bullet under it. Disease and molecule-class words (COVID-19, RNAs, lncRNAs…) are
  no longer matched as genes. Checker version 5.
- **Cut-off answers are marked.** An answer that hit the length limit mid-way was shown as complete;
  it now carries a "cut off" tag, in the scoreboard and in the report.

### Added
- `--dates` takes a start year (`--dates 2018`) as well as `1y`, `5y`, `10y`.

## 0.2.3 — 2026-10-23

### Fixed
- Correct citations were reported as off-topic when cited on a detail bullet ("Cell lines
  studied: … DIC model [PMID]") under a candidate heading ("#### miR-495-3p"). The bullet named no
  RNA, and "DIC" (doxorubicin-induced cardiotoxicity) was read as a gene symbol. The heading is
  now part of the claim, and disease, drug, cell-type and cell-line abbreviations (DIC, DOX, MSC,
  EVs, AC16, H9C2…) are no longer treated as genes. Checker version 4: saved results are re-checked.

### Added
- **Conversation view.** A follow-up adds to the same page (`conversation.html` in the first run),
  earlier questions collapsed, like the website's chat. In the Claude app it is shown as an
  artifact beside the chat and updated in place on each follow-up; from the terminal it opens in
  the browser. `open <run>` opens it.

### Changed
- After a comparison, Claude shows a short conclusion, the scoreboard and one line of problems per
  model, then stops; the answers are in the browser view. It no longer re-reviews papers by hand,
  edits OmniMed's code or commits in the same turn.

## 0.2.2 — 2026-10-23

### Fixed
- The judge saw at most 6,000 characters of an answer, with the middle cut. A complete 6.9k-character
  answer was scored 4/10 as "partially truncated", penalised for OmniMed's own trimming. The limit is
  now 12,000 characters, and anything trimmed carries a note telling the judge not to count it.

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
