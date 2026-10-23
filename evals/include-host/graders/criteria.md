---
type: llm
weight: 1
---

The OmniMed skill is used. A successful response:

- writes its own answer before reading the others
- adds it with --provider anthropic --source host
- its judge is not an Anthropic model
- does not rank its own answer above the others

(This case calls paid model APIs.)
