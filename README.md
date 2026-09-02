# Purrsist

[![CI](https://github.com/heet-talati/purrsist/actions/workflows/ci.yml/badge.svg)](https://github.com/heet-talati/purrsist/actions/workflows/ci.yml)
[![PyPI](https://img.shields.io/pypi/v/purrsist)](https://pypi.org/project/purrsist/)
[![Python](https://img.shields.io/badge/python-3.12%2B-blue)](https://www.python.org/)
[![Code style: ruff](https://img.shields.io/badge/code%20style-ruff-000000.svg)](https://github.com/astral-sh/ruff)

> [!NOTE]
> _The content and reflections in this README are mine. I wrote the draft and used Claude to polish the wording which was reviewed by me (also why you'll spot the odd — em dash)._

### A terminal habit-tracker that won't let you quietly abandon what you started.

Purrsist is a local-only CLI: cap your active goals at three, put a real deadline and hour target on each, time your focus sessions against them, and leave a log entry so tomorrow-you knows what happened. Everything lives in one SQLite file — no accounts, no sync, no browser tab.

## Demo

> 🎥 _Demo GIF / asciinema recording coming soon._

## Project Description

The problem this solves is personal: it's easy to abandon what you're learning the moment something newer and shinier shows up, and to keep doing that indefinitely without ever finishing anything. Purrsist makes that switching cost visible instead of invisible. You can only have three goals active at once, each one needs a real deadline, and the moment your top-priority goal falls behind the pace it needs to hit that deadline, the app locks further priority and mode changes until you either catch up or explicitly `unlock` with a reason. Curiosity isn't punished — you can still add and park new ideas — it just can't silently hijack what you're actually spending time on.

## Features

- **Goals** — a small number of active priorities (max 3, one ranked top), each with an hours target and a required deadline
- **Lock-in** — falling behind pace on your top-priority goal locks further priority/mode changes until you catch up or consciously `unlock` with a reason
- **Pace tracking** — average hours/day and a projected days-to-finish estimate per goal
- **Focus timer** — pomodoro-style start/pause/resume/stop timer scoped to a goal, with a visual + audible cue on completion
- **Session logs** — jot down what you did right after a timer ends, or backfill it later; list sessions filtered by goal
- **Streaks** — a daily streak that requires a real log entry and at least 15 minutes tracked that day
- **Local-only data** — everything lives in one SQLite file at `~/.purrsist/purrsist.db`; nothing leaves your machine

## Technologies

- **Python 3.12+** — the language, run as a REPL-style CLI
- **SQLite** — the entire data layer, one local file, no server
- **[rich](https://github.com/Textualize/rich)** — terminal tables, colors, and the animated countdown timer
- **[uv](https://docs.astral.sh/uv/)** — dependency and virtual environment management (not bare `pip`)
- **[ruff](https://github.com/astral-sh/ruff)** — linting and formatting
- **[mypy](https://mypy-lang.org/)** — static type checking
- **[pytest](https://docs.pytest.org/)** — the test suite
- **GitHub Actions** — CI on every push/PR to `main`
- **PyPI trusted publishing (OIDC)** — publishing on version tags, no stored API token

## Keyboard Shortcuts

During an active `track` session:

| Key | Action |
|---|---|
| `p` | Pause / resume the timer |
| `q` | Stop the session early |
| `Ctrl+C` | Also stops the session early |

## Installation & Usage

### Install from PyPI

```bash
pip install purrsist
python -m purrsist
```

```
purrsist > goal add 20 "Learn Rust" 30
✓ Added goal 'Learn Rust' (20.0h, due 2026-09-27)

purrsist > goal priority "Learn Rust"
✓ 'Learn Rust' is now active (priority 1)

purrsist > track "Learn Rust"
▶ Tracking 'Learn Rust' for 25 min. Press 'p' to pause, 'q' to stop early (Ctrl+C also works).
```

Type `help` at any time for the top-level command list, or `<command> help` (e.g. `goal help`, `track help`) for its subcommands. Data is stored locally at `~/.purrsist/purrsist.db`.

### Run from source (development)

This project uses [uv](https://docs.astral.sh/uv/) — not bare `pip` — for everything.

```bash
git clone https://github.com/heet-talati/purrsist.git
cd purrsist
uv sync --all-groups
```

| Task | Command |
|---|---|
| Run the app | `uv run python -m purrsist` |
| Run all checks (tests, lint, format, types — same order as CI) | `uv run python scripts/check.py` |
| Run tests | `uv run pytest` |
| Run a single test | `uv run pytest tests/test_cli.py::test_initialization` |
| Lint | `uv run ruff check .` |
| Format check / fix | `uv run ruff format --check .` / `uv run ruff format .` |
| Type check | `uv run mypy src` |

See [`CLAUDE.md`](CLAUDE.md) for architecture notes and [`PRD.md`](PRD.md) for product scope. Work is tracked as [GitHub Issues](https://github.com/heet-talati/purrsist/issues).

## Known Issues

- The timer's pause/resume/stop key listener is implemented with `msvcrt`, so it only works on Windows — there's no macOS/Linux keyboard input path yet.
- No reminders or notifications if a goal goes untouched for a while.
- No goal categories, and no "parking lot" for ideas you want to keep without letting them disturb your active priorities.
- No review/statistics command for daily, weekly, or monthly summaries — only per-goal pace stats exist today.
- Single-machine only: no sync or backup across devices.

## Bugs

Notable bugs that were caught and fixed during development:

- `goal list`'s Active/Inactive tables rendered with no gap and misaligned columns.
- Lock-in only ever evaluated the priority-1 goal, so a goal ranked 2 or 3 falling behind its own deadline pace was never caught.
- The average-hours/day pace calculation could be inflated for a goal started the same day — elapsed days is now floored at 1.
- A rapid double Ctrl+C could still crash the app with an uncaught `KeyboardInterrupt` even after the first shutdown-handling fix.
- Pressing Ctrl+C right after a track countdown crashed the REPL with an `EOFError`.
- Deleting an active goal left a gap in the priority ranking instead of shifting the remaining goals up.

## The Process

This started because I was trying to learn several different things at once and getting nowhere with any of them. The first step wasn't code — it was documenting the problem, what a solution could look like, and what success actually meant (finishing one thing, completely). That became a PRD, along with a feature list, a rough roadmap, and a running list of open product questions.

I also used the project deliberately to learn things beyond the code itself. I set up a GitHub Project with a Kanban board and practiced real project management: breaking features down into user stories, then into atomic issues, and along the way learning how sub-issues work. I wrote some of the early code by hand, then brought in Claude Code specifically to learn what AI-assisted development actually looks like in practice. Beyond that, I wanted to learn how software actually gets shipped — CI/CD, publishing to PyPI on version tags, trunk-based development with short-lived branches, reviewing changes through pull requests instead of merging directly, and working with a real package manager and virtual environment (`uv`) instead of ad hoc global installs.

## What I Learned

This was my first time doing TDD, and it didn't go as cleanly as I expected — a lot of the actual test-writing ended up delegated to Claude Code rather than driven by me. I came away with a general shape of what TDD looks like, and next time I want to drive it more through behaviors I define up front, using Claude Code to help surface gaps in my own thinking rather than to fill them in for me.

I also learned, the hard way, that I hadn't done enough upfront research or clearly defined the outcome before building. The high-level features were designed reasonably well, but database design, architecture, and implementation all happened far too quickly and turned into something closer to vibe coding. Looking back, what I actually had was a product-level spec — a PRD with a problem statement, success criteria, and a feature list — but never a technical-level spec: no data model, no architecture, no behavior/acceptance criteria written down before implementation. That missing layer is exactly what let it slide into vibe coding, so what I was reaching for was closer to spec-driven development, just without the structure to make it real.

I picked up Claude Code hooks along the way and want to use them more deliberately next time. And I learned that the way I write prompts matters a lot — giving specific, directive prompts makes the implementation predictable and easy to follow, instead of overwhelming. It's slower, but the resulting code is noticeably higher quality and easier to maintain. On top of all that, I got real practice working with package managers and virtual environments instead of just knowing about them abstractly.

## Overall Growth

This is my first CLI project, my first time attempting TDD, and my first time shipping a package to PyPI. It's also the first time I've run a project through a GitHub Project/Kanban board with proper user stories broken into atomic issues and sub-issues, the first time I've deliberately practiced AI-assisted development rather than just using it ad hoc, and the first project where I followed trunk-based development with short-lived branches and pull-request review discipline end to end.

## How It Can Be Improved

- Go through the code and actually read how it works end to end, rather than trusting that it does — most of the bugs that came up trace directly back to specs that weren't detailed or clear enough in the first place.
- Use the app myself, note where friction or bugs show up, and document them properly instead of just patching and moving on.
- Next time, put planning, architecture, and database design in their own documents before writing implementation, and spend more time nailing down behavior and user experience before diving into code.
- Use Claude Code hooks more deliberately where they'd actually help.
- Write more specific, directive prompts up front — slower to write, but far more predictable to build on.
- Look into pair-programming with AI more intentionally, and into code review tooling.
- Document the build journey next time — as a video or a written article — instead of only after the fact.
