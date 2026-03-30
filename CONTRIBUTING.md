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
| `style:`     | `style: apply ruff formatting`                |
| `perf:`      | `perf: cache embedding results`               |

Labels are assigned automatically from the title prefix via [release-drafter](https://github.com/release-drafter/release-drafter). These labels categorize the auto-generated release notes.

PRs without a conventional prefix still work — they just won't be auto-labeled.

### Workflow

1. **Fork and branch.** Create a feature branch from `main`.
2. **Make your changes.** Keep PRs focused — one feature or fix per PR.
3. **Write tests.** Add or update tests in `tests/` for any new or changed functionality.
4. **Run checks.** Make sure `ruff check`, `ruff format --check`, and `pytest` all pass.
5. **Open a PR.** Use a conventional prefix in the title.

## Project Structure

```
src/memsearch/          # Core Python library
├── core.py             # MemSearch public API
├── cli.py              # Click CLI
├── store.py            # Milvus vector store
├── chunker.py          # Markdown chunking
├── embeddings/         # Pluggable embedding providers
├── scanner.py          # File discovery
├── config.py           # TOML config system
├── watcher.py          # File watcher
├── compact.py          # LLM summarization
plugins/claude-code/    # Claude Code plugin (shell hooks)
├── .claude-plugin/     # Plugin manifest
├── hooks/              # 4 lifecycle hooks + shared utilities
├── scripts/            # Helper scripts (derive-collection.sh)
├── transcript.py       # JSONL transcript parser
└── skills/             # Memory recall skill

tests/                  # pytest test suite
docs/                   # mkdocs-material documentation
```

## Claude Code Plugin Development

To test the plugin locally without installing from the marketplace:

```bash
# 1. Install memsearch CLI
pip install memsearch

# 2. Set your embedding API key
export OPENAI_API_KEY="sk-..."

# 3. Launch Claude Code with the local plugin
claude --plugin-dir ./plugins/claude-code
```

Edits to hook scripts take effect on the next hook trigger — no restart needed (except `SessionStart`, which fires once per session).

**Testing hooks manually:**

```bash
# Simulate a user prompt
echo '{"prompts":[{"content":"what caching solution did we pick?"}]}' | bash plugins/claude-code/hooks/user-prompt-submit.sh

# Test session start
echo '{}' | bash plugins/claude-code/hooks/session-start.sh
```

Hooks read JSON from stdin and write JSON to stdout. Check that the output contains valid `additionalContext` fields.

**Debugging tips:**

- Hooks log to stderr — add `echo "debug: ..." >&2` to trace without breaking the JSON contract.
- Watch PID file: `.memsearch/.watch.pid` — delete it if the watcher gets stuck.
- `stop.sh` calls `claude -p --model haiku` internally. Set `stop_hook_active=1` to skip it during manual testing.

## Documentation

Docs live in `docs/` and are built with [mkdocs-material](https://squidfun.github.io/mkdocs-material/):

```bash
uv run mkdocs serve    # local preview at http://127.0.0.1:8000
```

## Reporting Issues

Open an issue on [GitHub](https://github.com/zilliztech/memsearch/issues) with:

- What you expected vs. what actually happened
- Steps to reproduce
- Python version and OS

## License

By contributing, you agree that your contributions will be licensed under the [MIT License](LICENSE).
