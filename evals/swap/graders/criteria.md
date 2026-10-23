---
type: llm
weight: 1
---

The OmniMed skill is used. A successful response:

- first runs `run` with gemini38 (or gemini), deepseek_pro, groq
- remove-answer <run> groq
- ask … --models qwen38flash --run <run>
- compare <run>
- other answers keep their judge scores
- writes a fresh verdict with add-verdict
