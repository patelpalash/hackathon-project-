# Transit Planner — implementation pack 2.0.0

Open docs/START_HERE.md first.

- Claude: docs/prompts/CLAUDE_FRONTEND.md
- Codex: docs/prompts/CODEX_BACKEND.md
- Antigravity: docs/prompts/ANTIGRAVITY_BACKEND.md
- Merge together: docs/MERGE_GUIDE.md

Includes the corrected planning documents, API/provider contracts, MapLibre/live-data plan, fixtures, original source CSVs and challenge brief. It does not contain an implemented frontend or backend. No secrets are included. TomTom live traffic requires a locally configured server-side API key; all unavailable integrations must be labeled.

Validation: install jsonschema and tzdata in your own development Python environment, then run python docs/tools/validate_spec.py. See docs/VALIDATION_REPORT.md for what was actually checked.
