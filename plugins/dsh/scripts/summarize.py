#!/usr/bin/env python3
"""DSH plugin summarizer: reuse memsearch's ``[llm.providers.*]`` config.

This is the ``custom-llm`` summarizer backend (``summarizeMode: custom-llm``):
it imports the same memsearch config + LLM plumbing the four built-in
platform plugins use via ``memsearch summarize --plugin <name>``:

    prompt + transcript  ->  resolve_config() -> compact.summarize_text()

Provider selection (most specific first):

1. ``--provider <name>``  — the DSH plugin config's ``summarizeProvider``;
   looked up in ``[llm.providers.<name>]``. Missing entry is a visible error.
2. ``[plugins.dsh.summarize]`` — the memsearch-managed section aligned with the
   other platform plugins (``[plugins.<platform>.summarize]``).
3. ``cfg.llm.provider``   — when it names a configured provider or is a raw
   provider type (openai/anthropic/gemini).
4. ``cfg.compact.llm_provider`` (deprecated fallback) or ``openai``.

Failures exit non-zero with a message on stderr so the plugin can surface a
visible error instead of silently writing nothing.

Usage:
    summarize.py --agent-name "DeepSeek Harness" [--provider NAME] [--model M] \\
        [--project-dir DIR]
    transcript ... (stdin)  ->  bullet points (stdout)
"""

# ruff: noqa: T201  # CLI tool: stdout/stderr are the output mechanism
from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# memsearch importability bootstrap (shared with plugins/_shared/scripts)
# ---------------------------------------------------------------------------


def ensure_memsearch_importable(transcript: str = "") -> None:
    """Make the memsearch Python API importable from any environment.

    May re-exec the process under a memsearch-enabled interpreter (uv run);
    when it does, the transcript payload is carried over via
    ``MEMSEARCH_DSH_TRANSCRIPT`` so the re-exec'd process still sees it even
    though the original stdin pipe has been consumed.
    """
    user_paths = [
        str(Path.home() / ".local" / "bin"),
        str(Path.home() / ".cargo" / "bin"),
        str(Path.home() / "bin"),
        "/usr/local/bin",
    ]
    existing_path = os.environ.get("PATH", "")
    path_parts = existing_path.split(os.pathsep) if existing_path else []
    for user_path in reversed(user_paths):
        if Path(user_path).is_dir() and user_path not in path_parts:
            path_parts.insert(0, user_path)
    os.environ["PATH"] = os.pathsep.join(path_parts)

    # Prefer the checkout's own source when running from a git worktree.
    for parent in Path(__file__).resolve().parents:
        src_dir = parent / "src"
        if (src_dir / "memsearch").is_dir():
            sys.path.insert(0, str(src_dir))
            break

    try:
        import memsearch  # noqa: F401

        return
    except ModuleNotFoundError:
        pass

    if os.environ.get("MEMSEARCH_DSH_UV_BOOTSTRAP") == "1":
        return

    # Carry the already-consumed stdin payload across the re-exec below.
    reexec_env = {**os.environ, "MEMSEARCH_DSH_UV_BOOTSTRAP": "1"}
    if transcript:
        reexec_env["MEMSEARCH_DSH_TRANSCRIPT"] = transcript

    memsearch_bin = _which("memsearch")
    if memsearch_bin:
        try:
            first_line = Path(memsearch_bin).read_text(encoding="utf-8", errors="ignore").splitlines()[0]
            if first_line.startswith("#!"):
                python_bin = first_line[2:].strip().split()[0]
                if python_bin:
                    os.execvpe(
                        python_bin,
                        [python_bin, str(Path(__file__).resolve()), *sys.argv[1:]],
                        reexec_env,
                    )
        except (OSError, UnicodeDecodeError):
            pass

    uv = _which("uv")
    if not uv:
        return

    os.execvpe(
        uv,
        [
            uv,
            "run",
            "--with",
            "memsearch[onnx]",
            "python",
            str(Path(__file__).resolve()),
            *sys.argv[1:],
        ],
        reexec_env,
    )


def _which(name: str) -> str | None:
    """Return the first PATH match for ``name`` (no shell involved)."""
    for directory in os.environ.get("PATH", "").split(os.pathsep):
        if not directory:
            continue
        candidate = Path(directory) / name
        if candidate.is_file() and os.access(candidate, os.X_OK):
            return str(candidate)
    return None


# ---------------------------------------------------------------------------
# Summarization
# ---------------------------------------------------------------------------


def _load_summarize_prompt(config, agent_name: str, plugin_dir: Path) -> str:
    """Load the summarize prompt: user override > plugin template > inline."""
    configured = getattr(config, "prompts", None)
    custom_path = getattr(configured, "summarize", "") if configured else ""
    if custom_path:
        candidate = Path(custom_path).expanduser()
        if candidate.is_file():
            return candidate.read_text(encoding="utf-8").replace("{{AGENT_NAME}}", agent_name)

    builtin = plugin_dir / "prompts" / "summarize.txt"
    if builtin.is_file():
        return builtin.read_text(encoding="utf-8").replace("{{AGENT_NAME}}", agent_name)

    return (
        "You are a third-person note-taker. You will receive a transcript of ONE conversation turn "
        f"between User and {agent_name}.\n\n"
        "Record what happened as factual third-person notes. Output 2-10 bullet points, each starting with '- '. "
        "Use 'User' for the user. First bullet: what User asked or wanted. Remaining bullets: what was done, "
        f"found, changed, configured, tested, explained, decided, or could not be completed by {agent_name}. "
        "Mandatory language rule: write every bullet in the same primary language as the [User] text. "
        "If User mixes languages, use the dominant user-facing language. "
        "Be specific when useful: mention important files read or edited, searches or research performed, "
        "refactors, commands or tests run, key findings, and concrete outcomes. Prefer the final user-visible "
        "outcome over low-level transcript mechanics. Do NOT answer User's question yourself. Output ONLY "
        "bullet points."
    )


def _resolve_llm_settings(config, provider_arg: str, model_arg: str) -> tuple[str, str | None, str | None, str | None]:
    """Resolve (provider_type, model, base_url, api_key) from memsearch config.

    Mirrors the plugin summarize resolution in ``cli.py`` while adding the
    compact-style fallback for when no ``[llm.providers.*]`` entry is named.

    Resolution order (most specific first):
    1. ``--provider`` / ``--model`` CLI args (the DSH plugin's own
       ``summarizeProvider`` / ``summarizeModel`` config).
    2. ``[plugins.dsh.summarize]`` — the memsearch-managed config that the
       other four platform plugins (Claude Code, Codex, OpenCode, OpenClaw)
       share; added so DSH aligns with the same single config surface.
    3. ``[llm.providers.*]`` / ``llm.provider`` / ``compact.llm_provider``.
    """
    llm = getattr(config, "llm", None)
    compact = getattr(config, "compact", None)

    # 2. memsearch [plugins.dsh.summarize] — aligned with the other plugins.
    plugins = getattr(config, "plugins", None)
    dsh_cfg = getattr(plugins, "dsh", None) if plugins else None
    dsh_summarize = getattr(dsh_cfg, "summarize", None) if dsh_cfg else None
    dsh_provider = getattr(dsh_summarize, "provider", "") or ""
    dsh_model = getattr(dsh_summarize, "model", "") or ""

    def _named_provider(name: str, model_override: str = "") -> tuple[str, str | None, str | None, str | None]:
        providers = getattr(llm, "providers", {}) if llm else {}
        provider_cfg = providers.get(name)
        if provider_cfg is None:
            raise ValueError(f"Unknown LLM provider {name!r}. Configure [llm.providers.{name}] in memsearch config.")
        provider_type = provider_cfg.type or name
        model = model_override or provider_cfg.model or (getattr(llm, "model", "") or "")
        base_url = provider_cfg.base_url or getattr(llm, "base_url", "") or None
        api_key = provider_cfg.api_key or getattr(llm, "api_key", "") or None
        return provider_type, model or None, base_url, api_key

    if provider_arg:
        return _named_provider(provider_arg, model_arg)

    if dsh_provider:
        return _named_provider(dsh_provider, dsh_model or model_arg)

    top_provider = getattr(llm, "provider", "") if llm else ""
    if top_provider and top_provider in (getattr(llm, "providers", {}) or {}):
        return _named_provider(top_provider, model_arg)

    if not top_provider:
        top_provider = getattr(compact, "llm_provider", "") if compact else ""
    provider_type = top_provider or "openai"
    model = model_arg or getattr(llm, "model", "") or getattr(compact, "llm_model", "")
    base_url = getattr(llm, "base_url", "") or getattr(compact, "base_url", "") or None
    api_key = getattr(llm, "api_key", "") or getattr(compact, "api_key", "") or None
    return provider_type, model or None, base_url, api_key


async def _summarize(
    prompt: str, llm_provider: str, model: str | None, base_url: str | None, api_key: str | None
) -> str:
    from memsearch.compact import summarize_text

    return await summarize_text(
        prompt,
        llm_provider=llm_provider,
        model=model,
        base_url=base_url,
        api_key=api_key,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Summarize a DSH turn with memsearch-managed LLM.")
    parser.add_argument("--agent-name", default="DeepSeek Harness", help="Agent display name.")
    parser.add_argument("--provider", default="", help="Named [llm.providers.*] entry to use.")
    parser.add_argument("--model", default="", help="Override the LLM model.")
    parser.add_argument("--project-dir", default="", help="Project directory (config resolution anchor).")
    parser.add_argument("--plugin-dir", default="", help="Plugin directory (prompt template location).")
    args = parser.parse_args()

    # Read the transcript from stdin BEFORE any exec-based bootstrap: the uv
    # re-exec below replaces the process image and the pipe would otherwise be
    # consumed already. The re-exec'd process recovers the payload from
    # MEMSEARCH_DSH_TRANSCRIPT (set by ensure_memsearch_importable).
    transcript = os.environ.get("MEMSEARCH_DSH_TRANSCRIPT", "")
    if not transcript:
        transcript = sys.stdin.read()
    if not transcript.strip():
        return 0

    plugin_dir = Path(args.plugin_dir).resolve() if args.plugin_dir else Path(__file__).resolve().parent.parent

    if args.project_dir:
        os.chdir(args.project_dir)

    ensure_memsearch_importable(transcript)

    try:
        from memsearch.config import resolve_config

        config = resolve_config()
    except Exception as error:  # surface any config failure visibly
        print(f"Error: failed to load memsearch config: {error}", file=sys.stderr)
        return 1

    try:
        system_prompt = _load_summarize_prompt(config, args.agent_name, plugin_dir)
        provider_type, model, base_url, api_key = _resolve_llm_settings(config, args.provider, args.model)
        prompt = f"{system_prompt}\n\nTranscript:\n{transcript}"
        summary = asyncio.run(_summarize(prompt, provider_type, model, base_url, api_key))
    except Exception as error:  # report provider errors instead of hiding them
        print(f"Error: {error}", file=sys.stderr)
        return 1

    if summary and summary.strip():
        print(summary.strip())
        return 0
    print("Error: summarizer returned no output", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
