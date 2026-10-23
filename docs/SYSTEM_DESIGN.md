# OmniMed Skill — System Design

The OmniMed Skill brings the [OmniMed website](https://github.com/chitrashensah/omniMed)'s
research workflow into Claude Code: ask up to five AI models the same
cardiovascular ncRNA question, optionally ground them in PubMed or Europe PMC
papers, check every citation, score the answers blind, and show them side by
side. It is built so that **the skill and the website reach the same verdict on
the same answer**: the code that grounds a question, checks citations and scores
answers is shared, byte for byte.

---

## 1. Architecture

```mermaid
flowchart LR
    U[Researcher] --> CC[Claude Code<br/><i>host agent</i>]
    CC -- reads --> SK[SKILL.md<br/>workflows + rules]
    CC -- runs --> CLI[scripts/omnimed.py<br/>one JSON object per command]
    CLI --> LIB[omnimed_lib]
    LIB -- "≤ 5 in parallel" --> LLM[LLM providers<br/>Anthropic · OpenAI · Google<br/>DeepSeek · OpenRouter · Groq · Cohere]
    LIB -- "search · verify" --> LIT[Literature<br/>PubMed · Europe PMC · PubMed Central<br/>Crossref · DataCite · ClinicalTrials.gov]
    CLI -- writes --> RUN[(~/omnimed-runs/&lt;run&gt;<br/>answers · report.md · report.html)]
    RUN -- opens --> BR[Browser view<br/><i>website layout</i>]
```

**Division of labour.** Claude Code is the interface and the analyst: it picks
the workflow from `SKILL.md`, asks the user which models to compare, reads the
report, and writes the verdict. The script does everything that must be exact
and repeatable: calling the models, checking citations, scoring, and writing
the report. Every command prints one JSON object so the host can parse it; long
material goes to files in the run directory.

---

## 2. Components

| Path | Responsibility |
|---|---|
| `skills/omnimed/SKILL.md` | What Claude reads: when to use the skill, the workflows, the rules |
| `skills/omnimed/reference/research-prompt.md` | The prompt every model gets (website base prompt + "miRNA Research"); generated, never edited by hand |
| `skills/omnimed/reference/interpreting-results.md` | What each metric means |
| `scripts/omnimed.py` | The CLI: setup, models, defaults, search, verify, unsourced, ask, run, compare, add-answer, remove-answer, add-verdict, open |
| `omnimed_lib/models.py` | The 23-model registry (mirrors the website), provider calls over plain HTTP, judge selection |
| `omnimed_lib/env.py` | API keys from env files outside the repo; reports presence as booleans only |
| `omnimed_lib/report.py`, `report_html.py` | The markdown report and the browser view (the website's layout) |
| **`omnimed_lib/grounding.py`** | *Shared with the website:* base prompt, literature grounding, history caps, the missed-questions note |
| **`omnimed_lib/literature_service.py`** | *Shared:* literature search, citation verification (incl. full text), uncited claims, candidate profiles |
| **`omnimed_lib/agent_service.py`** | *Shared:* the judge rubric and reply parsing |

### Shared code, not copied code

```mermaid
flowchart LR
    W[omnimed-backend/services<br/>grounding · literature_service · agent_service] -- "sync_from_backend.sh<br/>(byte-identical copy)" --> S[omnimed_lib]
    F[omnimed-frontend builtinPrompts.js<br/>+ grounding.BIOMEDICAL_BASE_PROMPT] -- generated --> P[reference/research-prompt.md]
    T[tests: SharedWithWebsite] -. fails if they differ .-> S
    T -. fails if they differ .-> P
```

The three shared modules live in the website's backend and are copied, unchanged,
by `scripts/sync_from_backend.sh`, which also regenerates the research prompt.
`tests/test_omnimed.py` fails if any copy differs from the website's, so a fix
made in one place cannot silently diverge. The modules import only the standard
library, `httpx` and each other (`grounding` imports `literature_service`), which
is what lets the same file run in both projects.

---

## 3. Asking and comparing (`run`)

```mermaid
sequenceDiagram
    participant C as Claude Code
    participant O as omnimed.py
    participant L as Literature APIs
    participant M as Models (≤5)
    participant J as Judge (other provider)

    C->>O: run "question" --models … [--db --dates --papers] [--after run]
    O->>O: history per model from the --after chain,<br/>earlier questions each model missed
    opt --db given
        O->>L: one keyword search per database + date range
    end
    par each model
        O->>M: research prompt + own history + [papers] + question
        M-->>O: answer
    end
    O->>L: verify citations, uncited claims, candidate profiles
    O->>J: one blinded rubric call per answer (judge ≠ its provider)
    O-->>C: JSON: scoreboard, candidates, report paths
    C->>C: read report.md, write verdict
    C->>O: add-verdict → conversation.html (artifact beside the chat, or browser)
```

What each model receives, and when, is decided by the shared `grounding.py`,
exactly as on the website:

| Part | When |
|---|---|
| Research prompt (base rules + research format) | Always, unless `--no-prompt` |
| Its own earlier questions and answers | Follow-ups (`--after`): ≤ 12 messages, ≤ 24,000 characters |
| Earlier questions it never saw | It was not part of an earlier run |
| Papers from PubMed / Europe PMC | `--db` given; `auto` = the 25 best matches, 8 with abstracts |
| Date-range rule (strict) | `--dates` given |

**Independence.** A model never sees another model's answers, so the comparison
stays fair. **Thinking is always on:** Claude runs adaptive thinking at effort
`high`; the other providers reason by default; Qwen (OpenRouter) and Cohere
have a 6,000-token thinking cap because uncapped they returned nothing.

---

## 4. Measuring answers

The same three layers as the website, kept in separate fields:

1. **Citation check (rules, no AI).** Identifiers resolved in PubMed, Crossref
   and DataCite; author–year citations matched by a fielded PubMed search; support
   judged by whether the paper names the claim's molecule or target, with a
   full-text second look (Europe PMC, then NCBI PubMed Central). Results carry a
   `checker_version`; a saved result from an older checker is re-run, not reused.
2. **AI score.** A judge for each answer, never from that answer's provider
   (so a host answer from Claude is never judged by a Claude model), never told
   which model wrote it; overall = the average of evidence, mechanism,
   actionability and calibration. The website instead uses one judge for all
   answers to a question, outside every scored provider.
3. **Wet-lab verdict.** Recorded on the website; the only ground truth.

---

## 5. Data: the run directory

```
~/omnimed-runs/<timestamp>-<question>/        (OMNIMED_RUNS_DIR overrides)
├── question.txt
├── run.json            the run this one follows (after) and literature options
├── answers/<model>.md  each answer exactly as written
├── answers/<model>.json status, served model id, tokens, time, papers given
├── comparison.json     checks, scores, candidates, verdict (machine-readable)
├── report.md           the report Claude reads and shows
├── report.html         this question's view
└── conversation.html   (first run only) every question of the conversation on one page
```

A conversation is a chain of runs linked by `run.json → after`. Swapping a model
re-uses everything that did not change (matched by answer hash and checker
version), so only the new model is asked, checked and scored.

---

## 6. Security and privacy

| Concern | Design |
|---|---|
| API keys | Read from `~/.config/omnimed/*.env` or `OMNIMED_ENV_FILE`, never from the skill folder; never printed (`setup` reports booleans); the host is told never to read them |
| Dependencies | One package (`httpx`), installed into a private venv at `~/.cache/omnimed/venv` on first use |
| Model text in the browser | Rendered as Markdown only through DOMPurify; plain text if the libraries do not load |
| Data | Runs stay on the user's machine. Sent out: the questions (to the chosen providers), identifiers (to the literature APIs), and, in the Claude app only, the conversation page, published as a private artifact to show it beside the chat |
| Paid models | Never added unless the user chose them; the judge prefers free models |
| Limits | 5 models per run; 40 citations and 8 full-text look-ups per answer; PubMed paced at 2.5 requests/s (9 with `NCBI_API_KEY`) |

---

## 7. Where it runs

| Client | Status |
|---|---|
| Claude Code (terminal, desktop app's Code tab) | Fully supported: scripts run locally with network access and the user's keys |
| Claude.ai / Claude desktop chat | Skills run in a cloud sandbox without the user's key files and possibly without network access; the literature tools may work, model comparison will not |
| ChatGPT and other clients | Not supported by a skill; the planned MCP server covers them |

---

## 8. Testing and release

- **Unit tests** (`tests/`, offline): env parsing, model registry vs. website,
  judge provider rules, picker, limits, reports, conversation chain, literature
  options, shared-code parity. **Live tests** (`OMNIMED_LIVE=1`): PubMed checks
  on fixture answers.
- **Behaviour evals** (`evals/`, `claude plugin eval`): should-trigger and
  should-not-trigger prompts with graded expectations.
- **Release:** `claude plugin validate --strict .`, bump `version` in
  `.claude-plugin/plugin.json`, add a `CHANGELOG.md` entry, then
  `claude plugin tag .` to create the release tag.

---

## 9. Next steps

- **MCP server** on the website's backend, exposing the same tools to Claude
  desktop, claude.ai and ChatGPT, with the website's database as the shared
  store for wet-lab results.
- **Submitting a wet-lab score** from the skill, once that server exists.
