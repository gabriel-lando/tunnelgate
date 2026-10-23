# CLAUDE.md

Tunnelgate: internal kill switch and route manager for Cloudflare Tunnels (FastAPI backend + SvelteKit 3 SPA,
single container).

## Conventions

- Talk to the user (Gabriel) in Brazilian Portuguese. Code, comments, commits and docs are in English; only
  the UI is translated (`frontend/src/lib/i18n/*.json`, keys must match — `pnpm i18n:check`).
- Keep code comments short; no long explanatory comment blocks.
- Never hardcode hostnames, groups or tunnel names; everything comes from env or the Cloudflare API.
- Every value sent to Cloudflare is validated (`backend/src/tunnelgate/validation.py`); keep it that way.
- Security-relevant changes need a regression test and an entry in `docs/security-review.md`.
- Dependency rules: versions ≥ 3 days old (uv `exclude-newer`, pnpm `minimumReleaseAge`); lockfiles enforced;
  GitHub Actions pinned by commit SHA; Python scanners via hash-locked `ci/scanners.txt`.
- After API schema changes: `cd backend && uv run python scripts/export_openapi.py`, then update
  `frontend/src/lib/types.ts`.
- SvelteKit 3: config in `vite.config.ts`; import with `#lib/...` and explicit `.ts`; use `resolve()` for links.

## Checks before finishing a change

```sh
cd backend && uv run ruff check . && uv run ruff format --check . && uv run mypy src && uv run pytest
cd frontend && pnpm check && pnpm lint && pnpm i18n:check && pnpm test && pnpm build
```
