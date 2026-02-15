# Contributing to memsearch

Thanks for your interest in contributing! Here's how to get started.

## Development Setup

```bash
git clone https://github.com/zilliztech/memsearch.git
cd memsearch
uv sync --all-extras
```

## Running Tests

```bash
# All tests
uv run python -m pytest

# Single file
uv run python -m pytest tests/test_chunker.py

# Single test with verbose output
uv run python -m pytest tests/test_store.py::test_upsert_and_search -v
```

> **Note:** Always use `uv run python -m pytest` instead of `uv run pytest` to avoid picking up system-level pytest.

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
└── transcript.py       # JSONL transcript parser

ccplugin/               # Claude Code plugin (shell hooks)
├── .claude-plugin/     # Plugin manifest
└── hooks/              # 4 lifecycle hooks + shared utilities

tests/                  # pytest test suite
docs/                   # mkdocs-material documentation
```

## Making Changes

1. **Fork and branch.** Create a feature branch from `main`.
2. **Write tests.** If you're adding or changing functionality, add corresponding tests in `tests/`.
3. **Run the test suite.** Make sure all tests pass before submitting.
4. **Keep PRs focused.** One feature or fix per PR.

## Code Style

- Python 3.10+ with `from __future__ import annotations` for type hints.
- Code and comments in English.
- Use `uv` and `pyproject.toml` for dependency management — never `pip install` directly.

## Claude Code Plugin Development

To test the plugin locally without installing from the marketplace, use `--plugin-dir` to point Claude Code at your local checkout:

```bash
# 1. Make sure memsearch CLI is installed
pip install memsearch

# 2. Set your embedding API key
export OPENAI_API_KEY="sk-..."

# 3. Launch Claude Code with the local plugin
claude --plugin-dir ./ccplugin
```

This loads hooks directly from `ccplugin/hooks/` — any edits to the shell scripts take effect on the next hook trigger (no restart needed for most hooks, except `SessionStart` which only fires once).

**Testing individual hooks manually:**

```bash
# Test user-prompt-submit hook (simulates a user prompt)
echo '{"prompts":[{"content":"what caching solution did we pick?"}]}' | bash ccplugin/hooks/user-prompt-submit.sh

# Test session-start hook
echo '{}' | bash ccplugin/hooks/session-start.sh
```

Hooks read from stdin and write JSON to stdout. Check that the output contains valid `additionalContext` fields.

**Debugging tips:**

- Hooks log to stderr — add `echo "debug: ..." >&2` to trace execution without breaking the JSON stdout contract.
- The watch process PID file is at `.memsearch/.watch.pid` — delete it if the watcher gets stuck.
- The `stop.sh` hook calls `claude -p --model haiku` internally. Set `stop_hook_active=1` in the environment to skip it during manual testing.

## Documentation

Docs are in `docs/` and built with mkdocs-material:

```bash
uv run mkdocs serve    # local preview at http://127.0.0.1:8000
```

## Reporting Issues

Open an issue on [GitHub](https://github.com/zilliztech/memsearch/issues) with:
- What you expected to happen
- What actually happened
- Steps to reproduce
- Your Python version and OS

## License

By contributing, you agree that your contributions will be licensed under the [MIT License](LICENSE).
