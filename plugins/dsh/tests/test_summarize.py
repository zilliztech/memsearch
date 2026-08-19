"""Unit tests for the DSH plugin summarizer's config resolution.

These test the pure resolution helpers in ``scripts/summarize.py`` with fake
memsearch config objects — no LLM calls, no subprocesses.
"""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS))

import summarize  # noqa: E402  (inserted above)


def _provider(type_: str, model: str = "", base_url: str = "", api_key: str = "") -> SimpleNamespace:
    return SimpleNamespace(type=type_, model=model, base_url=base_url, api_key=api_key)


def make_config(**overrides) -> SimpleNamespace:
    providers = {
        "deepseek": _provider("openai", "deepseek-chat", "https://api.deepseek.com", "env:DSK"),
        "local-anthropic": _provider("anthropic", "claude-sonnet-4-6"),
    }
    llm = SimpleNamespace(provider="", model="", base_url="", api_key="", providers=providers)
    compact = SimpleNamespace(llm_provider="", llm_model="", base_url="", api_key="")
    prompts = SimpleNamespace(summarize="")
    plugins = SimpleNamespace(
        dsh=SimpleNamespace(summarize=SimpleNamespace(enabled=True, provider="", model=""))
    )
    config = SimpleNamespace(llm=llm, compact=compact, prompts=prompts, plugins=plugins)
    return config


class TestResolveLlmSettings:
    def test_explicit_provider_uses_named_entry(self) -> None:
        config = make_config()
        provider_type, model, base_url, api_key = summarize._resolve_llm_settings(config, "deepseek", "")
        assert provider_type == "openai"
        assert model == "deepseek-chat"
        assert base_url == "https://api.deepseek.com"
        assert api_key == "env:DSK"

    def test_explicit_provider_missing_raises_visible_error(self) -> None:
        config = make_config()
        with pytest.raises(ValueError, match="Unknown LLM provider 'nope'"):
            summarize._resolve_llm_settings(config, "nope", "")

    def test_model_arg_overrides_provider_model(self) -> None:
        config = make_config()
        _, model, _, _ = summarize._resolve_llm_settings(config, "deepseek", "custom-model")
        assert model == "custom-model"

    def test_provider_type_defaults_to_name(self) -> None:
        config = make_config()
        config.llm.providers["gemini-local"] = _provider("", "gemini-3-flash-preview")
        provider_type, model, _, _ = summarize._resolve_llm_settings(config, "gemini-local", "")
        assert provider_type == "gemini-local"
        assert model == "gemini-3-flash-preview"

    def test_llm_provider_naming_configured_entry(self) -> None:
        config = make_config()
        config.llm.provider = "deepseek"
        provider_type, model, _, _ = summarize._resolve_llm_settings(config, "", "")
        assert provider_type == "openai"
        assert model == "deepseek-chat"

    def test_defaults_to_openai_with_top_level_llm(self) -> None:
        config = make_config()
        config.llm.base_url = "https://example.com/v1"
        config.llm.api_key = "env:OPENAI_API_KEY"
        provider_type, model, base_url, api_key = summarize._resolve_llm_settings(config, "", "")
        assert provider_type == "openai"
        assert model is None
        assert base_url == "https://example.com/v1"
        assert api_key == "env:OPENAI_API_KEY"

    def test_compact_fallback(self) -> None:
        config = make_config()
        config.llm.provider = ""
        config.compact.llm_provider = "anthropic"
        config.compact.llm_model = "claude-sonnet-4-6"
        provider_type, model, _, _ = summarize._resolve_llm_settings(config, "", "")
        assert provider_type == "anthropic"
        assert model == "claude-sonnet-4-6"

    def test_plugins_dsh_summarize_provider(self) -> None:
        """[plugins.dsh.summarize] provider is used when no CLI arg is passed."""
        config = make_config()
        config.plugins.dsh.summarize.provider = "deepseek"
        provider_type, model, base_url, api_key = summarize._resolve_llm_settings(config, "", "")
        assert provider_type == "openai"
        assert model == "deepseek-chat"
        assert base_url == "https://api.deepseek.com"
        assert api_key == "env:DSK"

    def test_plugins_dsh_summarize_model_override(self) -> None:
        """[plugins.dsh.summarize] model wins over the provider's default."""
        config = make_config()
        config.plugins.dsh.summarize.provider = "deepseek"
        config.plugins.dsh.summarize.model = "deepseek-v4-flash"
        _, model, _, _ = summarize._resolve_llm_settings(config, "", "")
        assert model == "deepseek-v4-flash"

    def test_cli_arg_beats_plugins_dsh_config(self) -> None:
        """The DSH plugin's own --provider/--model (from plugin config) wins."""
        config = make_config()
        config.plugins.dsh.summarize.provider = "deepseek"
        provider_type, model, _, _ = summarize._resolve_llm_settings(config, "local-anthropic", "my-model")
        assert provider_type == "anthropic"
        assert model == "my-model"


class TestMainTranscriptRecovery:
    """The uv re-exec must not lose the stdin payload.

    ``ensure_memsearch_importable`` re-execs under ``uv run`` when uv is on
    PATH; the re-exec'd process can no longer read the consumed stdin pipe, so
    ``main()`` prefers ``MEMSEARCH_DSH_TRANSCRIPT`` (carried across the exec)
    over a fresh stdin read. With the env payload present, main() must proceed
    to summarization (not bail out on the empty stdin).
    """

    def test_main_uses_env_transcript_when_stdin_is_empty(self, monkeypatch, capsys) -> None:
        marker = "env-transcript-marker-001"
        monkeypatch.setenv("MEMSEARCH_DSH_TRANSCRIPT", f"=== Turn 1 ===\n[User]: remember {marker}\n[Assistant]: ok")
        monkeypatch.setattr("sys.stdin.read", lambda: "")
        # main() parses sys.argv; in pytest that is the pytest invocation, so
        # replace it with the summarize.py CLI shape.
        monkeypatch.setattr("sys.argv", ["summarize.py", "--agent-name", "Test"])

        seen = {}

        async def fake_summarize(prompt, provider_type, model, base_url, api_key):
            seen["prompt"] = prompt
            return "- remembered"

        monkeypatch.setattr(summarize, "_summarize", fake_summarize)
        monkeypatch.setattr(summarize, "_load_summarize_prompt", lambda *a, **k: "SYSTEM")
        monkeypatch.setattr(summarize, "ensure_memsearch_importable", lambda transcript="": None)
        # Point the local `from memsearch.config import resolve_config` at a stub.
        monkeypatch.setattr("memsearch.config.resolve_config", lambda: make_config(), raising=False)

        rc = summarize.main()
        assert rc == 0
        assert "env-transcript-marker-001" in seen.get("prompt", "")
        out = capsys.readouterr().out
        assert "- remembered" in out


class TestLoadSummarizePrompt:
    def test_plugin_template_contains_agent_name(self) -> None:
        plugin_dir = Path(__file__).resolve().parent.parent
        config = make_config()
        prompt = summarize._load_summarize_prompt(config, "DeepSeek Harness", plugin_dir)
        assert "DeepSeek Harness" in prompt
        assert "third-person note-taker" in prompt
        assert "{{AGENT_NAME}}" not in prompt

    def test_custom_prompt_wins(self, tmp_path: Path) -> None:
        custom = tmp_path / "custom.txt"
        custom.write_text("CUSTOM PROMPT for {{AGENT_NAME}}", encoding="utf-8")
        config = make_config()
        config.prompts.summarize = str(custom)
        plugin_dir = Path(__file__).resolve().parent.parent
        prompt = summarize._load_summarize_prompt(config, "Agent X", plugin_dir)
        assert prompt == "CUSTOM PROMPT for Agent X"

    def test_inline_fallback_when_no_template(self, tmp_path: Path) -> None:
        config = make_config()
        empty_dir = tmp_path / "empty"
        empty_dir.mkdir()
        prompt = summarize._load_summarize_prompt(config, "Agent Y", empty_dir)
        assert "Agent Y" in prompt
        assert "third-person note-taker" in prompt

    def test_missing_custom_path_falls_back_to_template(self) -> None:
        config = make_config()
        config.prompts.summarize = "/nonexistent/path.txt"
        plugin_dir = Path(__file__).resolve().parent.parent
        prompt = summarize._load_summarize_prompt(config, "DSH", plugin_dir)
        assert "DSH" in prompt
