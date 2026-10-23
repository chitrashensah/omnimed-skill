# Interpreting OmniMed results

## Citation check (Layer 1, deterministic)

Every PMID, DOI and author–year citation in an answer is looked up in PubMed,
Crossref and DataCite.

| Field | Meaning |
|---|---|
| `checked` | Distinct papers cited (a paper given as both PMID and DOI counts once) |
| `verified` | The identifier exists |
| `fabricated` | The identifier does not exist anywhere. A hallucinated citation |
| `unresolved` | The lookup failed (network, rate limit). **Not** evidence of fabrication |
| `mismatched` | The paper exists, but its title/abstract does not mention the miRNA or target the claim is about. A miscitation |
| `retracted` | The paper exists and is retracted |
| `hallucination_rate` | fabricated ÷ (verified + fabricated) |
| `miscitation_rate` | mismatched ÷ citations whose support could be judged |

Support is judged by rules, not by an AI: does the paper name the miRNA,
lncRNA or gene target the claim is about? Title, abstract and MeSH terms come
first. A citation that looks unsupported from those gets a **full-text second
look**: the paper's open-access full text (Europe PMC, or NCBI PubMed Central
as backup) is searched too, and a match there is reported as *supported (full
text)*. When no open full text exists but the paper is on the claim's topic,
the verdict is *not in the title or abstract; full text not available*, which
does not count against the model. A `mismatched` flag that survives all this is
almost always a real problem (e.g. an ADHD paper cited for a miR-21 claim).

The rules check that a paper is **about** the claimed molecule, not that it
**agrees** with the claim. That judgement is what the AI score is for.

An answer with **few citations** can look clean. Read citation results together
with **Uncited claims**.

## Literature given, and the date range

With `--db`, each answer's report line says what that model was given, e.g.
"📚 12 papers (auto) · PubMed since 2021". *Auto* offers the 25 best matches (the
top 8 with abstracts) and lets the model choose; fewer means the database had
fewer. With `--dates`, models are told to cite only papers from that range, and
any cited paper older than it is flagged in the report.

## Uncited claims

Up to six specific claims the answer made *without* a citation are each
searched in PubMed. "2 of 6 unsupported" means a search found nothing related
for two of them. Finding nothing does not prove a claim false. It marks the
claim for a human to check.

## Candidate profile

Every miRNA/lncRNA named by any answer is counted in PubMed (all time and since
2021) and in ClinicalTrials.gov as an intervention. This is independent of the
answers. A candidate one model named with 3 trials can outrank one that five
models named with none.

## Judge score (Layer 2, model opinion)

A model from a different provider scores each answer 1–10 on:

- **evidence**: are claims supported by real, relevant, correctly attributed sources?
- **mechanism**: is the biological mechanism specific and coherent?
- **actionability**: could a wet-lab researcher act on it (target, model system, assay)?
- **calibration**: does stated confidence match the evidence?

The judge sees the Layer 1 citation findings (so it does not have to guess
whether a PMID is real), which means its score partly depends on Layer 1. It
is not told which model wrote the answer. Judge scores are noisy. The same
answer can receive very different scores on re-runs, so compare models over
many questions, not one.

## Wet-lab verdict (Layer 3, ground truth)

Recorded by the researcher on the OmniMed website after experiments. The
project's research question is whether Layers 1 and 2 predict Layer 3, which is
why the three are never merged.

## Run directory

`~/omnimed-runs/<timestamp>-<question>/` (override with `OMNIMED_RUNS_DIR`):

- `question.txt`
- `run.json`: the run this one follows up (`after`) and the literature options
- `answers/<model>.md`: each answer as written; `answers/<model>.json`: status, served model id, tokens, time
- `comparison.json`: everything, machine-readable
- `report.md`: the human-readable report
- `report.html`: this question's view, laid out like the website (one box per model, Conclusion box)
- `conversation.html` (in the first run of a conversation): every question and its answers on one page; this is what is shown beside the chat or in the browser
