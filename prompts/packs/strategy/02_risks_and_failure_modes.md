# Risks and failure modes — {{intent}} / {{query}}

Based on the sources about "{{query}}", what are the most commonly cited risks, pitfalls, and failure modes?

List them in order of frequency of mention, and note any mitigations recommended. Cite the source by title or channel when a specific risk is attributed to one. Do not hallucinate URLs.

Do not include step-by-step install commands here; implementation details belong to the implementation pack.

---

## Hard-to-reverse decisions

Identify decisions that, once made, are expensive or disruptive to undo. For each one, state:
- What the decision locks in
- The cost of reversing it later
- Any mitigation or escape hatch mentioned in the sources

Include the following known constraints for this domain, and supplement with anything the sources add:

- **NotebookLM 50-source cap per notebook:** once a notebook is built around a fixed source set, adding new sources requires creating a new notebook and re-running all prompts. Design curation filters accordingly.
- **Unofficial client brittleness:** the `notebooklm` CLI wraps an unofficial API. A Google-side change can break the entire pipeline with no warning. Mitigations: pin the client version, monitor for breakage, keep the CLI decoupled so it can be swapped.
- **Token vs. control tradeoff:** using NotebookLM's hosted model means no control over the underlying LLM, context window, or output format. If structured outputs or reproducibility are required, this architecture is a poor fit.
