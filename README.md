# OmniMed Skill

OmniMed as an **Agent Skill**: use it inside Claude Code (and other skill-aware
agents) instead of, or alongside, the [OmniMed website](https://omni--med.vercel.app).

Ask a cardiovascular ncRNA research question in your AI chat, and OmniMed:

- **asks up to 5 AI models in parallel**, picked with checkboxes in the chat from the same 23 models the website offers
- **grounds them in the literature** when you want: papers from PubMed or Europe PMC, within a date range, cited inline
- **follows up**: each model keeps its own earlier answers, never another model's
- **opens the answers in your browser, laid out like the website**: one coloured box per model, every answer in full, a Conclusion box, and follow-ups added to the same page
- **checks every citation** against PubMed, Crossref, DataCite and the paper's open full text: fabricated PMIDs, real papers cited for the wrong claim, retractions, papers older than your date range
- **looks for literature behind uncited claims**
- **profiles every candidate** miRNA/lncRNA against PubMed and ClinicalTrials.gov, independently of what the models said
- **scores each answer with a blinded judge** from a *different provider*
- writes a side-by-side **report** with every answer shown in full

Citation checks, judge scores and wet-lab results are kept in separate columns
and never blended. See [interpreting-results.md](skills/omnimed/reference/interpreting-results.md),
and [docs/SYSTEM_DESIGN.md](docs/SYSTEM_DESIGN.md) for how it is built.

## Install (Claude Code)

**Option 1: symlink (development):**

```bash
ln -s "$PWD/skills/omnimed" ~/.claude/skills/omnimed
```

**Option 2: as a plugin (once this folder is its own GitHub repo):**

```
/plugin marketplace add chitrashensah/omnimed-skill
/plugin install omnimed@omnimed
```

Requires Python 3.10+. On first use the skill installs its only dependency
(`httpx`) into a private venv at `~/.cache/omnimed/venv`, so your Python environments are untouched.

## API keys

**Literature tools need no keys.** Searching PubMed and verifying citations is free.

To ask other models, put keys in `~/.config/omnimed/keys.env` (never in this folder):

```env
GEMINI_API_KEY=...       # free tier: aistudio.google.com
GROQ_API_KEY=...         # free tier: console.groq.com
DEEPSEEK_API_KEY=...     # cheap
OPENROUTER_API_KEY=...   # Qwen; some free models
COHERE_API_KEY=...       # free trial key
OPENAI_API_KEY=...       # paid (GPT)
ANTHROPIC_API_KEY=...    # paid (Claude)
NCBI_EMAIL=you@example.com   # PubMed asks callers to identify themselves
```

Every `*.env` file in `~/.config/omnimed/` is loaded; `OMNIMED_ENV_FILE` points
elsewhere. Variables already set in your shell win. Keys are never printed:
`setup` reports them as present/absent only.

## Models

The same 23 models as the website, with the same keys, names and defaults.
**At most 5 per comparison**, like the site's five boxes. Defaults are marked.

| Key | Model | Group | Cost |
|---|---|---|---|
| `opus55` | Claude Opus 5.5 | Anthropic | Paid |
| `opus5` | Claude Opus 5 | Anthropic | Paid |
| `fable51` | Claude Fable 5.1 | Anthropic | Paid |
| `fable5` | Claude Fable 5 | Anthropic | Paid |
| `opus48` | Claude Opus 4.8 | Anthropic | Paid |
| `sonnet55` | Claude Sonnet 5.5 | Anthropic | Paid |
| `sonnet5` | Claude Sonnet 5 | Anthropic | Paid |
| `claude` | Claude Sonnet 4.6 | Anthropic | Paid |
| `gpt6astra` | GPT-6 Astra | OpenAI | Paid |
| `gpt61sol` | GPT-6.1 Sol | OpenAI | Paid |
| `gpt56sol` | GPT-5.6 Sol | OpenAI | Paid |
| `gpt55` | GPT-5.5 | OpenAI | Paid |
| `gpt54mini` | GPT-5.4 mini | OpenAI | Low cost |
| `deepseek_pro` | DeepSeek V4 Pro **(default)** | DeepSeek | Low cost |
| `gemini38` | Gemini 3.8 Flash **(default)** | Google | Free tier |
| `gemini36` | Gemini 3.6 Flash | Google | Free tier |
| `gemini35` | Gemini 3.5 Flash | Google | Free tier |
| `gemini` | Gemini 2.5 Flash | Google | Free tier |
| `qwen38flash` | Qwen 3.8 Flash **(default)** | Qwen | Low cost |
| `qwen38max` | Qwen 3.8 Max | Qwen | Low cost |
| `qwen37plus` | Qwen 3.7 Plus | Qwen | Low cost |
| `qwen36flash` | Qwen 3.6 Flash | Qwen | Low cost |
| `qwen` | Qwen 2.5 72B | Qwen | Low cost |
| `groq` | Groq GPT-OSS 120B **(default)** | Other | Free tier |
| `cohere` | Cohere Command A+ **(default)** | Other | Free tier |

Model names that are ambiguous resolve to the newest model of that family:
"GPT" is GPT-5.5, "Claude Sonnet" is Sonnet 5.5, "DeepSeek" is V4 Pro and "Llama" is
GPT-OSS on Groq. Gemini 3.5 Flash is currently served by Google as Gemini 3.6
Flash; the report records the model each provider actually served.

### Choosing and switching

- **In the chat:** name them ("compare Gemini 3.8, DeepSeek and GPT-5.5"), or name none
  and tick boxes in the picker (four checkbox groups: Google, Open models, OpenAI,
  Anthropic; others can be typed in).
- **Mid-conversation:** "add Qwen 3.8 Max", "drop Cohere", "swap Cohere for GPT-5.5".
  Only the changed models are asked again; the rest keep their checks and scores.
- **Your own defaults:** "use Gemini 3.8, DeepSeek and GPT-5.5 by default", or
  `omnimed.py defaults gemini38,deepseek_pro,gpt55` (`--reset` restores the site's).
- **A model that is not listed:** add it to `~/.config/omnimed/models.json`:

  ```json
  {"mistral_large": {"label": "Mistral Large", "provider": "openrouter",
                     "id": "mistralai/mistral-large", "tier": "cheap"}}
  ```

  Providers: `anthropic`, `openai`, `google`, `groq`, `deepseek`, `openrouter`, `cohere`.

## Use

Just ask in Claude Code:

> Compare Gemini, DeepSeek and GPT-OSS on which microRNAs reduce cardiac fibrosis after MI.

> Are these citations real? … (PMID: 19043405) … (PMID: 98765432)

> I asked ChatGPT and Gemini the same question. Here are both answers, compare them.

> Find papers since 2020 on lncRNA H19 in doxorubicin cardiotoxicity.

> Compare DeepSeek and GPT-OSS on miRNA targets for DOX cardiotoxicity, using PubMed papers from the last 5 years.

> (afterwards) Give me the citations again with links.

Or run the tools directly:

```bash
S=skills/omnimed/scripts/omnimed.py
python3 $S setup                                   # what is configured
python3 $S models                                  # models, defaults, picker
python3 $S run "your question" --models gemini38,groq,deepseek_pro --open
python3 $S run "your question" --models deepseek_pro,groq --db pubmed --dates 5y   # with literature
python3 $S run "a follow-up" --models deepseek_pro,groq --after <run>               # continue a conversation
python3 $S remove-answer <run> groq                # swap a model out…
python3 $S ask "your question" --models gpt55 --run <run>   # …and another in
python3 $S compare <run> --open
python3 $S verify answer.md
python3 $S search "miR-29 cardiac fibrosis" --year-from 2018
```

Runs are saved to `~/omnimed-runs/<timestamp>-<question>/` with every answer,
`comparison.json`, `report.md` and `report.html`; the first run of a conversation
also holds `conversation.html`, every question on one page (reopen it with
`omnimed.py open <run>`). The page is a local file; nothing is uploaded.

## Cost

| Part | Cost |
|---|---|
| Literature search, citation checks, candidate profiles | Free, no key |
| Gemini, GPT-OSS (Groq), Cohere | Free API tiers |
| DeepSeek, Qwen, GPT-5.4 mini | Fractions of a cent per answer (e.g. Qwen 3.8 Flash ≈ $0.003) |
| GPT-5.5 / GPT-6 / Claude | Paid per token; only used when you choose them |
| Comparing, verdict, explanation | Done by the AI you are chatting with, on your own subscription |

## Layout

```
omnimed-skill/
├── .claude-plugin/          plugin.json, marketplace.json
├── docs/SYSTEM_DESIGN.md    architecture, data flow, shared code, release
├── skills/omnimed/
│   ├── SKILL.md             what Claude reads: workflows and rules
│   ├── reference/           how to read results
│   └── scripts/
│       ├── omnimed.py       the CLI (one JSON object per command)
│       ├── sync_from_backend.sh
│       └── omnimed_lib/
│           ├── grounding.py            ← shared with the website (base prompt, literature, history)
│           ├── literature_service.py   ← shared (citation checks, search, candidates)
│           ├── agent_service.py        ← shared (judge rubric)
│           ├── models.py       the 23 models, provider calls over plain HTTP
│           ├── env.py          key loading
│           ├── report.py       markdown report
│           └── report_html.py  browser view (the website's layout)
├── tests/                   unit tests (offline) + live PubMed tests
└── evals/                   behaviour cases for `claude plugin eval`
```

The three shared modules live in the [website's backend](https://github.com/chitrashensah/omniMed)
(`omnimed-backend/services/`) and are copied here unchanged, so the website and
the skill ground a question, check a citation and score an answer the same way.
After changing any of them there, run `skills/omnimed/scripts/sync_from_backend.sh`
(it looks for the website checked out next to this repo as `../nexora`, or pass
the backend path). A test fails if the
copies drift. Model keys match the website's `validations.model` keys, so data
from both can be pooled.

## Test

```bash
~/.cache/omnimed/venv/bin/python -m unittest discover -s tests                  # offline
OMNIMED_LIVE=1 ~/.cache/omnimed/venv/bin/python -m unittest discover -s tests   # + PubMed
claude plugin validate --strict .                                             # manifest + skill
claude plugin eval . --allow-tools Bash                                        # behaviour cases in evals/ (calls model APIs)
```

## Release

1. Bump `version` in `.claude-plugin/plugin.json` and add a [CHANGELOG](CHANGELOG.md) entry.
2. `claude plugin validate --strict .`
3. Commit, then `claude plugin tag .` to create the `omnimed--v<version>` tag, and push with tags.

## Roadmap

1. **This skill**: Claude Code, local scripts *(v0.2: literature grounding, follow-ups, full-text citation checks)*
2. **MCP server** on the OmniMed backend: same tools for Claude Desktop, Claude.ai and ChatGPT
3. **In-chat UI**: model picker, side-by-side panels, scoreboard, wet-lab score submission
4. Pilot with the lab, then public release and a new Zenodo version

## License

MIT. Companion to the [OmniMed website](https://github.com/chitrashensah/omniMed)
([live](https://omni--med.vercel.app)), University of South Dakota UDiscover 2026.
