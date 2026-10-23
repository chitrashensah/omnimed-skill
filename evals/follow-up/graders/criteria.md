---
type: llm
weight: 1
---

The OmniMed skill is used. A successful response:

- the second question is sent with `run ... --after <first run>` using the same models
- does not start an unrelated new conversation for the follow-up
- each model's follow-up answer is shown with its citation check
