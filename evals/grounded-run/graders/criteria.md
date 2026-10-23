---
type: llm
weight: 1
---

The OmniMed skill is used. A successful response:

- runs `run` with --models deepseek_pro,groq --db pubmed --dates 5y (papers left at auto)
- reports how many papers each model was given
- flags any cited paper older than the date range instead of hiding it
