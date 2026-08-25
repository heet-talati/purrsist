# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

All commands go through `uv` (this project uses a uv-managed environment, not an activated venv + plain pip).

- Run the app: `uv run python -m purrsist`
- Run all checks in the same order CI uses (tests, ruff lint, ruff format check, mypy — stops at first failure): `uv run python scripts/check.py`
- Run tests only: `uv run pytest`
- Run a single test: `uv run pytest tests/test_cli.py::test_initialization`
- Lint: `uv run ruff check .`
- Format check: `uv run ruff format --check .` (auto-fix: `uv run ruff format .`)
- Type check: `uv run mypy src`
- Build distributables: `uv build`

## Architecture

- `src/purrsist/` is the installed package (editable install via `uv`). `cli.py` holds the entire CLI surface: the `COMMANDS` dict (source of `help` text), input parsing (`query_input`), output helpers (`print_cli`), and the `repl()` main loop, which dispatches on command name via `match/case`. Add a new top-level command by adding an entry to `COMMANDS` and a case to the `match` block in `repl()`.
- `src/commands/` is a second, sibling top-level package (not a subpackage of `purrsist`) intended for feature-specific command modules — currently only `goals.py`, unimplemented. It has no `__init__.py`; it's picked up today only via setuptools' automatic namespace-package discovery plus `uv`'s editable install path. This is an open architectural question (whether Goals code should live here vs. under `src/purrsist/commands/`), not a settled convention to extend without reconsidering.
- `__main__.py` is the entry point (`python -m purrsist`): prints the welcome banner, then calls `repl()`.
- Tests import the installed package directly (`from purrsist import ...`), not via `src.` — a bare `pytest`/`uv run pytest` only resolves `src.`-prefixed imports correctly under `python -m pytest` invocation, so importing the installed package is what makes the suite invocation-independent.

## Product context

`PRD.md` is the source of truth for product scope (problem statement, MVP user stories, open product questions). Work is tracked as GitHub Issues in `heet-talati/purrsist` (`gh issue list --repo heet-talati/purrsist`) — check there before assuming what's in scope for a given feature.

## Working conventions

- GitHub flow: short-lived branches off `main`, no `type/name` prefixes — plain descriptive names (e.g. `add-goal-command`, not `feat/add-goal-command`). Branch → commit → push → PR → CI → merge → delete branch.
- Never create, rename, delete, merge, or push a branch without being explicitly told to take that specific action. A broader instruction ("set X up", "clean this up") authorizes the work itself, not the git operations around it.
- Show the diff and get explicit approval before every `git commit`.
- Before referencing a third-party GitHub Action version (`uses: owner/action@vX`), check that action's actual tags/releases page — don't assume it follows the same floating-major-tag convention as a different action.

## CI/CD

- `.github/workflows/ci.yml` runs `scripts/check.py` on every push to `main` and every pull request.
- `.github/workflows/publish.yml` triggers on tags matching `v*.*.*`: it re-runs the same checks independently, verifies the tag matches `pyproject.toml`'s `version`, then builds and publishes to PyPI via trusted publishing (OIDC — no stored API token).
