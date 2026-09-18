# Shared repository and merge workflow

There are still two people. Person A uses Claude for the frontend. Person B uses Codex for backend/core integration and Antigravity for provider adapters plus regression testing. These are tool assignments, not three independent people.

## Fixed file ownership

| Writer | Own files | Branch |
|---|---|---|
| Claude | frontend/** only, including frontend package/lock files and GUI tests | codex/frontend-claude |
| Codex | backend/** except the paths assigned below; data/**; root README/.gitignore; scripts/**; approved shared-doc changes | codex/backend |
| Antigravity | backend/app/providers/**; backend/tests/providers/**; backend/tests/regression/**; qa/** | codex/backend-antigravity |
| Person B with Codex | Integrates reviewed branches and resolves shared-contract changes with Person A | codex/integration |

Codex owns backend/tests/engine, backend/tests/api and smoke tests; Antigravity does not rewrite them. Both may read all files. Requests for fixes in another owner's directory go to that owner or through an explicitly agreed change. No simultaneous writers in the same checkout. Both backend tools share contracts/provider_protocol.py and the HTTP OpenAPI before either implements integration logic.

## Establish a common base

Extract this ZIP into the project directory (it contains plans and supplied data, not implemented code). Review git status; preserve existing work. In a fresh repository, initialize Git with main and commit the pack. In an existing repository, commit the reviewed pack on its agreed base branch; do not rename/reset the repository automatically. Both people clone/fetch this same commit. Do not separately scaffold unrelated repositories and try to merge them at the end.

Example branch setup after the shared base is committed (run each in its own clone/worktree, not all in one active checkout):

```
git switch -c codex/frontend-claude
git switch -c codex/backend
git switch -c codex/backend-antigravity
```

Those are alternatives for the three checkouts. On separate laptops use a shared remote and push the named branches. On one laptop use Git worktrees rooted outside one another; don't run multiple branch switches underneath an active agent. No cloud deployment is required for this collaboration.

## Integration gates and merge order

1. Codex commits the backend skeleton, tested dependency set and shared provider protocol import location. Merge this small bootstrap into both other branches so they build against identical definitions.
2. Claude commits the frontend shell/API client; Codex commits the first real search. Person B merges both into codex/integration and runs a browser request end to end immediately.
3. Antigravity adds providers/tests against the common interface. Codex merges that branch after the backend's ingestion boundary exists. Production core files should not conflict because their ownership differs.
4. Merge small completed packages, not a single end-of-hackathon dump. After contract changes, both branches must consume the updated spec before further endpoint work.
5. Run the release checks, review remaining differences, then merge integration into the agreed main branch.

Example integration commands after all branches are pushed and working trees are clean:

```
git fetch origin
git switch codex/integration
git merge --no-ff origin/codex/backend
git merge --no-ff origin/codex/backend-antigravity
git merge --no-ff origin/codex/frontend-claude
```

Create codex/integration from the agreed base the first time. Do not use --allow-unrelated-histories, hard reset, force-push or wholesale "ours/theirs" conflict resolution. When shared files conflict, compare the intended API behavior, fix it once, and rerun contract tests. Frontend lockfile is Claude's; backend dependency lock is Codex's, with Antigravity requesting additions rather than generating a competing lock.

## Release checks

From repo root: python docs/tools/validate_spec.py. From backend: pytest for engine/API/providers/regression. From frontend: npm ci, npm run typecheck, npm run build, GUI checks. Confirm actual commands in the implemented README; the scripts do not exist yet in this planning pack.

Run the default numerical fixture, incident/manager acceptance loop, two-tab decision refresh, clock progression between readiness and departure, inactive-hub exclusion, immutable decision history and a real MapLibre page. Test production frontend served by Python, not just Vite. Disconnect internet to test fallback; reconnect to test configured integrations. Run from a path containing spaces. Preserve the old v1 ZIP for comparison; distribute only the version-2 pack for new work.

## Dependencies and data

This version includes the seven user-supplied CSVs under data/raw plus source brief files under reference so the teammate can inspect the actual challenge. These are local handoff files; a Git remote does not need to be public. Commit source code and approved demo fixtures; decide whether to track original inputs in the shared private repository or exchange them via this ZIP. Exclude runtime DBs, venv, node_modules, actual .env secrets and generated builds.

No live secret is included. Copy config/examples into local .env files during implementation and set provider keys locally. A key must never be copied into frontend code, a VITE_ variable or the shared contract.
