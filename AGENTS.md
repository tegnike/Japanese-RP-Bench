# Repository Guidelines

## Project Structure & Module Organization

Core Python code lives in `src/japanese_rp_bench/`; the current benchmark is under `src/japanese_rp_bench/v2/`, while top-level modules preserve v1. Tests are in `tests/`. Role definitions and scenarios belong in `role_packs/<pack>/`, with `pack.yaml`, `roles/`, and `scenarios/`. Configurations live in `configs/`; distinguish current entry points from historical snapshots using `configs/README.md`. The `dashboard/` directory is a separate Next.js application. Treat `conversations/`, `evaluations/`, and dated files in `docs/` as reproducibility artifacts. Put disposable output under `tmp/`.

## Build, Test, and Development Commands

- `python -m pip install -e .` installs Python 3.10+ dependencies and both CLI entry points.
- `python -m unittest discover -s tests` runs Python tests without contacting model APIs.
- `japanese-rp-bench-v2 validate role_packs/core-ja` validates Role Pack paths, schemas, rules, and probes.
- `japanese-rp-bench-v2 pilot --config configs/benchmark_full.yaml --output tmp/pilot-full --workers 4` checks credentials and a small execution path before a paid run. Follow `docs/benchmark-v2-production-protocol.md`; never launch a full run casually.
- `cd dashboard && npm install && npm run dev` starts the results UI. Use `npm run lint` and `npm test` before submitting dashboard changes; the latter performs a production build and rendered-HTML tests.

## Coding Style & Naming Conventions

Use four-space indentation and type hints for Python. Follow existing `snake_case` functions and modules, `PascalCase` classes, and `UPPER_CASE` constants. Keep imports grouped as standard library, third party, then local modules. Tests use `test_<behavior>` names. TypeScript uses two-space indentation, React components in `PascalCase`, and ESLint via `dashboard/eslint.config.mjs`. YAML IDs should be stable, lowercase, and descriptive; rule IDs follow `role.aspect.detail`.

## Testing Guidelines

Add focused `unittest` cases to `tests/test_v2.py` for scoring, schemas, providers, runners, or Role Pack behavior. Validate every changed pack. For dashboard work, update `dashboard/tests/rendered-html.test.mjs` when visible labels or serialized data change. No coverage threshold is enforced, but regressions should have a test.

## Published Results and Dashboard

Treat the published dashboard as part of every benchmark result change. When adding or changing a model, metric, ranking rule, or published score, update the canonical result documentation and `dashboard/app/data.ts` in the same change. If the metric schema changes, also update dashboard labels, explanations, filters, and rendered-HTML assertions. Run the Python test suite plus `npm run lint` and `npm test` in `dashboard/`. Commit and push the exact validated source, publish it to the existing Sites project, and verify the live dashboard contains the new model or metric before reporting the task complete. A source commit or push alone does not complete a published-results update.

## Commit & Pull Request Guidelines

History uses concise imperative subjects, sometimes with Conventional Commit prefixes (`feat:`, `refactor:`, `docs:`). Keep each commit scoped. Pull requests should explain the benchmark behavior changed, list verification commands, link relevant issues, and include screenshots for dashboard UI changes. For result updates, document model conditions, completion status, cost, artifact paths, and hashes.

## Security & Reproducibility

Keep API keys in environment variables such as `OPENAI_API_KEY`, `GEMINI_API_KEY`, and `ANTHROPIC_API_KEY`; never commit them to YAML. Use a new empty output directory when configuration fingerprints differ, and preserve historical configs and artifacts unchanged.
