---
name: omnimed
description: Biomedical research assistant for microRNA (miRNA), lncRNA and other non-coding RNA candidates in cardiovascular disease. Compares answers from up to 5 AI models side by side (Gemini, DeepSeek, Qwen, GPT, Claude, GPT-OSS, Cohere…), optionally grounded in PubMed or Europe PMC papers within a date range, shows them in a browser view like the OmniMed website, checks every cited PMID/DOI against PubMed, Crossref and open full text for fabricated or off-topic citations, profiles candidates against PubMed and ClinicalTrials.gov, and scores answers with a blinded judge from a different provider. Use when the user asks to compare AI models on a research question, verify citations or PMIDs in an AI answer, search the biomedical literature, or find therapeutic ncRNA targets for heart disease (fibrosis, MI, ischemia-reperfusion, cardiomyopathy, heart failure, doxorubicin, ferroptosis).
---

# OmniMed

OmniMed helps cardiovascular researchers find therapeutic ncRNA candidates
without trusting any single AI. It keeps three kinds of evidence apart and
never blends them into one number:

1. **Citation checks**: deterministic lookups in PubMed, Crossref and DataCite. No AI.
2. **Judge score**: a rubric score from a model of a *different provider*, blinded to who wrote the answer. An opinion, not ground truth.
3. **Wet-lab verdict**: the researcher's experimental result. The only ground truth.

All tools are in one script. Run it from this skill's base directory:

```bash
python3 scripts/omnimed.py <command> …
```

Every command prints one JSON object. Answers and reports are written to a run
directory, and the JSON gives the paths. The first run may take a few seconds
longer while it installs its one dependency (httpx) into a private venv.

## Choose the workflow

| The user wants to… | Do |
|---|---|
| Compare AI models on a question | **Workflow A** |
| Ask a follow-up about a comparison | **Follow-ups** |
| Add, drop or swap models in a comparison | **Switching models** |
| Change which models are used by default | `defaults` |
| Compare answers they pasted from other AI sites | **Workflow B** |
| Check citations in a text or file | `verify` (Workflow C) |
| Find papers on a topic | `search` (Workflow C) |
| Get *your* answer to a research question, grounded in literature | **Workflow D** |

## Workflow A: compare models

### 1. Pick up to 5 models

The limit is **5 models per comparison**, the same as the website's five boxes.

- **The user named models** ("Gemini, DeepSeek and GPT"): pass their words to
  `--models` as a comma list. Names, labels and keys all resolve; the script
  rejects unknown names and more than 5.
- **The user named none:** run `python3 scripts/omnimed.py models` and show the
  model picker. The output's `picker` field is ready-made checkbox questions:
  pass them as-is to your question tool (e.g. AskUserQuestion, one call with
  all the questions; each has `multiSelect: true`). Tell the user in one line
  that they can pick up to 5, and that untouched means the defaults (labelled
  "(default)"). Map ticked labels back to keys with the `key:` in each option's
  description; names typed under "Other" go to `--models` as typed.
  - Ticked more than 5: ask which to drop. Never silently cut.
  - Ticked nothing: use `--models default`.
- **No question tool available:** list the `picker` options as a numbered
  list and ask the user to reply with numbers or names.

Models with tier `paid` (GPT, Claude) cost real money per answer. Never add
one the user did not choose.

### 2. Literature (optional)

Like the website's per-box options, the models can be given papers found for
the question, and told to cite from them. Add these to `run` (or `ask`) when the
user wants literature-backed answers, recent evidence, or a time window:

| The user says | Add |
|---|---|
| "use PubMed", "cite recent papers", "evidence-based" | `--db pubmed` |
| "Europe PMC" | `--db europepmc` (peer-reviewed only; preprints go to the conclusion) |
| "skip preprints" | `--no-preprints` (by default `compare`/`run` check the latest preprints on the candidates) |
| "past year / 5 years / 10 years" | `--dates 1y` / `5y` / `10y` (strict: older papers are not cited) |
| "since 2018" | `--dates 2018` |
| "give them 8 papers" | `--papers 8` (default `auto`: the model chooses from the 25 best matches) |

Without `--db`, models answer from their own knowledge, which is itself a fair
comparison. Each answer's report shows what it was given ("📚 12 papers (auto) ·
PubMed since 2021").

### 3. Optionally include your own answer

Only if the user asks for it. Write it **before** looking at any other model's
answer, following the same citation instruction the models get (`python3
scripts/omnimed.py prompt`) and nothing else, and save it to a file. In step 4 use `ask` + `add-answer … --provider anthropic
--source host` (or your own provider) + `compare`, so your provider is kept off
its judge. It counts toward the 5.

### 4. Run

```bash
python3 scripts/omnimed.py run "<question>" --models gemini38,deepseek_pro,groq,qwen38flash,cohere --judge host
# with literature:  … --db pubmed --dates 5y
```

This asks every model in parallel, then checks
citations and uncited claims and profiles candidates. It typically takes 2–4
minutes; the slowest model sets the pace. Tell the user it is running, and use
a long timeout (10 minutes).

### 4b. Score the answers yourself, blind

With `--judge host`, **you** score every answer, at no API cost. A Claude
answer is also scored by GPT-5.5 (you may favour your own style even unnamed);
its shown score is the average of the two. The output gives a `judge_packet`
path: the answers as A, B, C… in random order, with the rubric and their
citation-check facts. Score them **before** reading `report.md` or anything
else that names the models:

1. Read `judge_packet.md` and follow its instructions; score each answer on its own.
2. Write the JSON object it asks for to a file, then:
   ```bash
   python3 scripts/omnimed.py add-scores <run> <scores-file>
   ```

Score each answer on its own merits, including any you suspect is Claude's. If
GPT-5.5 could not score (no key, out of credit), the Claude answers carry your
score only; the report says so.

### 5. Write the verdict and show the conversation view

Read `report.md` from the run directory, then write a short verdict
(4–8 bullets) to a file. It is a scientific conclusion about the **candidates**,
for a researcher deciding what to test. Citation quality is already shown in
each answer's box and the scoreboard: do not list PMIDs or retell citation
problems here, and do not review the cited papers yourself.

- **Agreed:** candidates most models named, with the same direction
  (overexpress ↑ / knock down ↓) and the same disease model.
- **Disagreed:** candidates named with opposite directions or different
  mechanisms, and which models said what.
- **Only one model:** notable candidates the others missed.
- **Latest preprints:** from report.md's "Latest preprints" section (OmniMed's
  own search; the models never saw these). For each preprint that bears on a
  candidate, say whether it **supports** or **contradicts** it, citing it by
  its ID (`P3`). Name any candidate found only in preprints. Label all of them
  "preprint, not peer-reviewed", and never raise a candidate's rank on a
  preprint alone. If the search was unavailable, say so in one line.
- **Test first in the lab:** 2–4 candidates, ranked by the strength of
  independent evidence (the candidates table's papers and trials), not by how
  many models named them, since models share training data and are wrong
  together. For each: direction (mimic / inhibitor), model system and a
  readout, plus the main risk. A contradicting preprint is a risk worth naming.
  End with: "Suggestions, not validated results."
- One line, only if it changes the picture: an answer that was cut off or whose
  citations mostly failed is weaker evidence for what it alone proposed.
- If your own answer is in the comparison, say so and do not rank it above the others.

Then put it in the **Conclusion** box and show the conversation view: the
website's layout, each model in its own coloured box with badges for citations
and judge score, problems highlighted, every answer in full. Follow-ups are
added to the same page (earlier questions collapsed), like the website's chat.

```bash
python3 scripts/omnimed.py add-verdict <run> <verdict-file>
```

This opens the conversation in the user's browser (Chrome or their default).
A follow-up opens it again, with the new question added.

### 6. Present in chat

Keep it short; the answers themselves are in the browser, one box per model.
Show, in this order:
1. Your verdict.
2. The **Scoreboard** table from `report.md`, exactly as written.
3. Problems, one line per model (e.g. "GPT-OSS: 1 off-topic citation"). The
   details are in the conversation view.
4. One line: the side-by-side answers are open in the browser; you can paste
   any answer or the candidates table on request.

Then stop. Do not start other work in the same turn: no re-checking papers by
hand, no changes to OmniMed's code, no commits. If a result looks wrong (say, a
citation flagged off-topic that seems on-topic), say so in one line and let the
user decide.

Never summarise or paraphrase a model's answer in place of showing it. If the
browser did not open (`opened_in_browser: false`) or the user
prefers the chat, show every answer in full under its model name instead.

End by asking if they want to swap any models, and mention that wet-lab results
can be recorded on the OmniMed website.

## Follow-ups

A follow-up question ("give me the citations again", "what about in vivo?",
"which of these has trial data?") continues the conversation:

```bash
python3 scripts/omnimed.py run "<follow-up>" --models <same models> --after <previous run> --judge host [--db … --dates …]
```

Each model gets **its own** earlier questions and answers as history, never
another model's, so the answers stay independent. A model that was not in the
earlier run is told the earlier questions only. Use `--judge host` and
score it (step 4b), then present as in steps 5–6; the browser page is the same
conversation, now with this question added.

## Switching models

Changes apply to the **same run**, so answers that did not change keep their
citation checks and judge scores. Only the new models are asked and checked.

| The user says | Do |
|---|---|
| "Add Qwen 3.8 Max" | `ask "<question>" --models qwen38max0902 --run <run>`, then `compare <run> --judge host` (and step 4b) |
| "Drop Cohere" | `remove-answer <run> cohere`, then `compare <run>` |
| "Swap Cohere for GPT-5.5" | `remove-answer <run> cohere`, `ask … --models gpt55 --run <run>`, `compare <run>` |
| "Retry the one that failed" | `ask … --models <that key> --run <run>`, then `compare <run>` |
| "Use these by default from now on" | `defaults gemini38,deepseek_pro,gpt55` |
| "Back to the normal defaults" | `defaults --reset` |

Every `compare` here takes `--judge host`; only answers that changed are in the
new packet, so score just those (step 4b).

A run holds at most 5 models: when adding would exceed that, ask which to drop
first. After any change, write a fresh verdict (`add-verdict`): `compare`
clears the old one, because it described a different set of answers.

## Workflow B: compare pasted answers

The user pasted answers from ChatGPT, Gemini, etc. (copied by hand from those sites):

```bash
python3 scripts/omnimed.py new-run "<question>"
python3 scripts/omnimed.py add-answer <run> /tmp/answer1.md --label "ChatGPT (pasted)" --provider openai
python3 scripts/omnimed.py add-answer <run> /tmp/answer2.md --label "Gemini (pasted)" --provider google
python3 scripts/omnimed.py compare <run>
```

Write each pasted answer to its own file first, exactly as pasted. Set
`--provider` when you know it, so the judge comes from elsewhere. Then
continue from Workflow A step 5. Say in your verdict that pasted answers have
no recorded model version, so they are not research-grade data.

## Workflow C: single checks

```bash
python3 scripts/omnimed.py verify answer.md            # or pipe text on stdin
python3 scripts/omnimed.py unsourced answer.md
python3 scripts/omnimed.py search "miR-29 cardiac fibrosis" --limit 8 --year-from 2018
```

For `verify`, report each citation as one of: exists, **does not exist**, real
but **does not match the claim**, **retracted**, or could not be checked. A
citation whose lookup failed (`exists: null`) is *not* fabricated. Never call
it that.

## Workflow D: your own grounded answer

1. `search` the topic (one or two focused queries).
2. Write the answer in your own way, citing as the models are told to
   (`python3 scripts/omnimed.py prompt`).
   Cite PMIDs from the search results; if the user set a date range, only papers
   within it.
3. Save your draft to a file and run `verify` on it. Fix or remove every
   citation that does not exist or does not match its claim, then present.

## Rules

- **Models get no answer format.** They are told only how to cite (`prompt` shows it), so each answers in its own words and structure. Your own answers follow the same citation rule: cite findings by PMID with a link, never invent an identifier.
- **Never read, print or copy API keys or env files.** `setup` shows which keys exist as true/false only.
- **Keep the three layers separate.** Never average citation results, judge score and wet-lab verdict into one number.
- **You judge blind.** Score from `judge_packet.md` before you see model names, never after.
- **You judge every answer, blind; GPT-5.5 adds a second score to Claude answers only.** No other model judges.
- **Judge scores are noisy.** The same answer can score very differently on a re-run. Present them as one reviewer's opinion, not a measurement.
- **Errors are information.** If a model fails, show its error in plain words (see below), carry on with the rest, and offer to retry it.

| Error | Meaning |
|---|---|
| `NO_API_KEY` | No key for this provider; run `setup` |
| `API_KEY_INVALID` | Key rejected by the provider |
| `RATE_LIMIT` | Free tier exhausted or too many requests; try later |
| `INSUFFICIENT_CREDITS` | The provider account behind this model is out of credit |
| `SERVICE_UNAVAILABLE` | Provider overloaded (already retried once) |
| `MODEL_UNAVAILABLE` | Provider no longer serves this model id |
| `REFUSED` | A safety classifier declined the request before the model ran, not a judgement on the question. Every Claude 5 model runs them and `bio` (research biology) fires on ordinary ncRNA questions. Say which area was named, and offer the same question on another Claude model or a non-Claude one |
| `TRUNCATED_BEFORE_ANSWER` | Model spent its whole budget thinking |
| `NETWORK_ERROR` | Connection dropped (already retried once); retrying usually works |
| `TIMEOUT` | No answer within 5 minutes |
| `LITERATURE_UNREACHABLE` | No literature database could be reached (offline, or a sandbox that blocks them). Say so; never report it as "no papers found". With `--db`, an unreachable database shows as "literature search failed" on that answer |
| `TOO_MANY_MODELS` | More than 5 in one comparison; ask which to drop |

## Setup problems

Run `python3 scripts/omnimed.py setup`. If no keys are found, the user puts
them in `~/.config/omnimed/keys.env` (one `NAME=value` per line, e.g.
`GEMINI_API_KEY=…`) or sets `OMNIMED_ENV_FILE`. Literature tools (`search`,
`verify`, `unsourced`) need no keys at all. A model not in the list can be
added in `~/.config/omnimed/models.json` (see README). See
[reference/interpreting-results.md](reference/interpreting-results.md) for
what each metric means.
