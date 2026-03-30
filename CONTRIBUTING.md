# Contributing to memsearch

Thanks for your interest in contributing! This guide will help you get set up and submit your first PR.

Questions or ideas? Join the [Discord](https://discord.com/invite/FG6hMJStWu).

## Getting Started

```bash
git clone https://github.com/zilliztech/memsearch.git
cd memsearch
uv sync --all-extras
uv run pre-commit install
```

> **Dependency management:** Use `uv` and `pyproject.toml` — never `pip install` directly.
>
> **Pre-commit hooks:** The `pre-commit install` step registers Git hooks that run `ruff check --fix` and `ruff format` on staged files before each commit.

## Running Tests

```bash
# Full suite
uv run python -m pytest

# Single file
uv run python -m pytest tests/test_chunker.py

# Single test with verbose output
uv run python -m pytest tests/test_store.py::test_upsert_and_search -v

# With coverage report
uv run python -m pytest --cov=memsearch --cov-report=term-missing
```

> **Note:** Always use `uv run python -m pytest` instead of `uv run pytest` to avoid picking up a system-level pytest.

## Code Style

The project uses [Ruff](https://docs.astral.sh/ruff/) for linting and formatting. CI will fail if either check doesn't pass.

```bash
uv run ruff check src/ tests/      # lint
uv run ruff format src/ tests/     # format
```

- Python 3.10+ with `from __future__ import annotations` for type hints.
- Code and comments in English.
- Line length limit: 120 characters.

## Commits and Pull Requests

Use [Conventional Commits](https://www.conventionalcommits.org/) prefixes for **PR titles**:

| Prefix       | Example                                       |
|--------------|-----------------------------------------------|
| `feat:`      | `feat: add date filtering to search`          |
| `fix:`       | `fix: handle empty markdown files in scanner` |
| `docs:`      | `docs: add troubleshooting guide`             |
| `ci:`        | `ci: update GitHub Actions versions`          |
| `chore:`     | `chore: bump dependencies`                    |
| `refactor:`  | `refactor: simplify config merging logic`     |
| `test:`      | `test: add transcript parser edge cases`      |

### Workflow

1. **Fork and branch.** Create a feature branch from `main`.
2. **Make your changes.** Keep PRs focused — one feature or fix per PR.
3. **Write tests.** Add or update tests in `tests/` for any new or changed functionality.
4. **Run checks.** Make sure `ruff check`, `ruff format --check`, and `pytest` all pass.
5. **Open a PR.** Use a conventional prefix in the title.

## Project Structure

```
src/memsearch/              # Core Python library
├── core.py                 # MemSearch public API (index, search, watch, compact)
├── cli.py                  # Click CLI
├── store.py                # Milvus vector store (hybrid search, upsert, dedup)
├── chunker.py              # Markdown heading-based chunking + SHA-256 hash
├── embeddings/             # Pluggable embedding providers (onnx, openai, google, etc.)
├── scanner.py              # File discovery (.md/.markdown)
├── config.py               # Layered TOML config system
├── watcher.py              # File watcher (watchdog-based, auto-index on change)
└── compact.py              # LLM-powered chunk summarization

plugins/
├── claude-code/            # Claude Code plugin (shell hooks + SKILL.md)
│   ├── hooks/              # SessionStart, Stop, UserPromptSubmit, SessionEnd
│   ├── skills/             # memory-recall skill (context:fork subagent)
│   ├── transcript.py       # Claude Code JSONL parser (L3)
│   └── scripts/            # derive-collection.sh, parse-transcript.sh
├── openclaw/               # OpenClaw plugin (TypeScript, registerTool)
│   ├── index.ts            # memory_search/get/transcript tools + lifecycle hooks
│   ├── skills/             # memory-recall SKILL.md (decision guide)
│   └── scripts/            # derive-collection.sh, parse-transcript.sh
├── opencode/               # OpenCode plugin (TypeScript npm plugin)
│   ├── index.ts            # Tools + experimental hooks
│   ├── scripts/            # capture-daemon.py (SQLite polling), parse-transcript.py
│   └── skills/             # memory-recall SKILL.md
└── codex/                  # Codex CLI plugin (shell hooks + SKILL.md)
    ├── hooks/              # SessionStart, Stop, UserPromptSubmit
    ├── skills/             # memory-recall skill
    └── scripts/            # install.sh, parse-rollout.sh, derive-collection.sh

evaluation/                 # Embedding provider benchmark (platform-agnostic)
tests/                      # pytest test suite
docs/                       # mkdocs-material documentation
```

## Plugin Development

### Claude Code

```bash
claude --plugin-dir ./plugins/claude-code   # test locally
```

Edits to hook scripts take effect on the next hook trigger — no restart needed.

### OpenClaw

```bash
openclaw plugins install ./plugins/openclaw   # install from local
openclaw gateway restart                       # reload plugin
```

TypeScript is loaded via jiti — no compilation step needed.

### OpenCode

```bash
mkdir -p ~/.config/opencode/plugins
ln -sf $(pwd)/plugins/opencode/index.ts ~/.config/opencode/plugins/memsearch.ts
# Restart opencode to load
```

### Codex CLI

```bash
bash plugins/codex/scripts/install.sh   # copies skill + generates hooks.json
codex --yolo                             # test with sandbox disabled
```

## Documentation

Docs live in `docs/` and are built with [mkdocs-material](https://squidfun.github.io/mkdocs-material/):

```bash
uv run mkdocs serve    # local preview at http://127.0.0.1:8000
uv run mkdocs build    # build to site/
```

## Reporting Issues

Open an issue on [GitHub](https://github.com/zilliztech/memsearch/issues) with:

- What you expected vs. what actually happened
- Steps to reproduce
- Python version and OS

## License

By contributing, you agree that your contributions will be licensed under the [MIT License](LICENSE).
