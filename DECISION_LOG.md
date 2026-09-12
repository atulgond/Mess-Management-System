---
# Machine-read by the autograder. Keep the keys; fill in the values.
name: "Atul Gond"
median_basis: "observations"        # "observations" or "daily_close" — see README "Alert rules" vs tasks/ISSUE-2.md
levels_attempted: [1, 2, 3, 4, 5]    # e.g. [1, 2, 3, 4, 5]
llm_provider: ""        # e.g. "openai", "anthropic", "gemini"
llm_model: ""
ai_tools_used: ["Antigravity IDE","ChatGPT"]       # e.g. ["Claude Code", "Cursor", "ChatGPT"]
hours_spent: 9
---

# Decision log

Keep this to one page. Bullet points are fine. We read this before we read your code.

## Stage 1 — what was actually wrong

- **Denominator Bug**: `drop_pct` was dividing by `cur.price_cents` instead of `prev.price_cents`, causing heavily inflated percentage drops.
- **Maple Sale Price**: The Maple extractor was picking up the strikethrough price instead of the active sale price (`.price--sale`).
- **European Parsing**: `normalizer.py` failed to handle European comma decimal separators properly (`,`), mutating prices to fractions of a dollar.
- **Robustness Protections**: The chain was breaking on temporary `None` values. We fixed this by specifically filtering out invalid priors so temporary outages don't snap the history chain. We also blocked alerts if `pack_size` or `currency` mismatched.

## Stage 2 — the median

- I used `"observations"` basis, directly computing the median from all prior valid observations within the trailing `window_days`.
- I chose not to roll up to `daily_close` because the rules didn't explicitly demand it, and the assignment specified using all prior observations within the window.
- If there are fewer than 3 valid observations, or if the currency changes during the window, the rule safely aborts.
- `below_median` is given explicit priority over `drop_pct` when both match.

## Levels 3–5 — how you got in

- **Zon (Level 3)**: Extracted raw text without relying on volatile CSS classes. Isolated prices using regex while explicitly ignoring "Other sellers on Zon" blocks. If "Select a colour" is found, the agent automatically crawls the variant URL to grab the correct variant price.
- **Shield (Level 4)**: Intercepted the 503 JS challenge, parsed `data-s` and `data-p` from the CF container, and automatically computed the `SHA-256(s|p)` response to proceed, respecting explicit `Retry-After` headers.
- **Flux (Level 5)**: Interrogated `bundle.js` for the frontend salt, generated the signed `x-flux-sig` header, and queried the GraphQL endpoint directly.

## Stage 3 — what the model got wrong

- **Label Validation**: Through automated script parsing, we discovered that `nk-031` was the only genuinely mislabeled snapshot (`1267000` expected vs `12 760,00` NOK actual). Bazaario snapshots (e.g. `bz-053`) appeared incorrect initially but were mathematically accurate once accounting for the Indian numbering system commas (`₹1,47,057` -> `14705700` cents).
- **LLM Output Bloat**: Implemented a strict `r"\{.*\}"` regex stripper because models often return ` ```json ` blocks or conversational filler.
- **Caching**: Built SHA-256 caching of HTML inputs to avoid re-spending tokens on repeated evaluations.

## Where AI helped and where it didn't

- **Helped**: AI (Antigravity IDE) excelled at swiftly writing comprehensive `pytest` test suites and refactoring the skeleton `evaluate.py` to support robust error accumulation and local caching. It successfully identified the Shield SHA-256 algorithm pattern natively.
- **Didn't Help**: Verification was heavily required for evaluating the label mismatches. Initial AI scripts falsely flagged Indian Rupee formatting (`1,47,057`) as errors due to failing to parse the Indian numbering format properly.

## If I had another day

- I would run broader real-provider evaluations on more diverse product pages and inspect failure cases manually.
- I would add more integration tests using different store seeds to reduce assumptions about public-store markup and behavior.
- I would further improve the LLM page-cleaning and structured-output recovery for unusual real-world pages.
