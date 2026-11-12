import json
import os
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest

from memsearch.transcript import last_exchange, parse_transcript, select_turns


def _history(path):
    rows = [
        {"type": "message", "role": "user", "content": "Earlier topic", "id": "message-0001"},
        {"type": "message", "role": "assistant", "content": "Earlier answer"},
        {
            "type": "message",
            "role": "user",
            "id": "message-0002",
            "content": [
                {
                    "type": "input_text",
                    "text": "<user_context>hidden context</user_context><user_query>Remember Blue Lantern</user_query>",
                }
            ],
        },
        {"type": "reasoning", "content": "private reasoning"},
        {"type": "function_call", "name": "read_file", "callId": "c", "arguments": '{"path":"settings.toml"}'},
        {"type": "function_call_result", "callId": "c", "output": {"content": "cache_ttl=37"}},
        {
            "type": "message",
            "role": "assistant",
            "content": [{"type": "output_text", "text": "The TTL is 37 minutes."}],
        },
        {"type": "message", "role": "user", "content": "<system-reminder>host reminder</system-reminder>"},
    ]
    path.write_text("\n".join(json.dumps(r) for r in rows), encoding="utf-8")


def test_workbuddy_capture_and_anchored_drilldown(tmp_path):
    path = tmp_path / "session.jsonl"
    _history(path)
    turns = parse_transcript(path)
    assert last_exchange(turns) == {
        "turn": "message-0002",
        "text": "[User]: Remember Blue Lantern\n[Assistant]: The TTL is 37 minutes.",
    }
    selected = select_turns(turns, "message-0002", 0)
    assert len(selected) == 1 and selected[0].text == "Remember Blue Lantern"
    tool = next(t.tools[0] for t in turns if t.tools)
    assert (tool.name, tool.command, tool.output) == ("read_file", "settings.toml", "cache_ttl=37")
    for content in ("<user_info/>hello", "<identity_context>do not capture"):
        path.write_text(json.dumps({"type": "message", "role": "user", "content": content}), encoding="utf-8")
        assert last_exchange(parse_transcript(path)) == {}


@pytest.mark.skipif(os.name != "posix", reason="executes the Bash marketplace hook")
def test_workbuddy_marketplace_stop(tmp_path):
    repo = Path(__file__).resolve().parents[1]
    market = json.loads((repo / ".codebuddy-plugin/marketplace.json").read_text())
    root = repo / market["plugins"][0]["source"]
    manifest = json.loads((root / ".codebuddy-plugin/plugin.json").read_text())
    hook = json.loads((root / manifest["hooks"]).read_text())["hooks"]["Stop"][0]["hooks"][0]["command"]
    project = tmp_path / "active project"
    project.mkdir()
    path = project / "session.jsonl"
    _history(path)
    home = tmp_path / "home"
    bindir = home / ".local/bin"
    bindir.mkdir(parents=True)
    executable = Path(sys.executable).with_name("memsearch")
    assert executable.is_file()
    (bindir / "memsearch").symlink_to(executable)
    trap = bindir / "claude"
    trap.write_text('#!/bin/sh\ntouch "$HOME/unexpected-native"\nexit 1\n')
    trap.chmod(0o755)
    env = {
        k: v
        for k, v in os.environ.items()
        if not k.startswith(("MEMSEARCH_", "MILVUS_", "CLAUDE_", "CODEBUDDY_", "OPENAI_"))
    }
    env.update(
        HOME=str(home),
        CODEBUDDY_PLUGIN_ROOT=str(root),
        CLAUDE_PROJECT_DIR=str(tmp_path),
        PATH=f"{bindir}:{os.defpath}",
        NO_PROXY="127.0.0.1",
    )
    calls = []

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            calls.append(body)
            result = {
                "id": "test",
                "object": "chat.completion",
                "created": 0,
                "model": "unit",
                "choices": [
                    {
                        "index": 0,
                        "message": {"role": "assistant", "content": "- Blue Lantern expires after 37 minutes."},
                        "finish_reason": "stop",
                    }
                ],
            }
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps(result).encode())

    def stop(payload):
        result = subprocess.run(
            ["sh", "-c", hook],
            env=env,
            cwd=tmp_path,
            input=json.dumps(payload),
            text=True,
            capture_output=True,
            timeout=30,
            check=True,
        )
        assert json.loads(result.stdout) == {}
        return result.stderr

    with HTTPServer(("127.0.0.1", 0), Handler) as server:
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            config = home / ".memsearch/config.toml"
            config.parent.mkdir()
            config.write_text('[embedding]\nprovider="onnx"\n')
            payload = {"cwd": str(project), "transcript_path": str(path)}
            stop(payload)
            assert not list(project.glob(".memsearch/memory/*.md"))
            with config.open("a") as f:
                f.write(
                    f'[llm.providers.test]\ntype="openai"\napi_key="test-only"\nmodel="unit"\nbase_url="http://127.0.0.1:{server.server_port}/v1"\n[plugins.workbuddy.summarize]\nprovider="test"\n'
                )
            assert "transcript_path" in stop({"cwd": str(project)})
            assert not calls
            stop(payload)
        finally:
            server.shutdown()
            thread.join()
    assert len(calls) == 1
    body = str(calls[0]["messages"])
    assert "Remember Blue Lantern" in body and "The TTL is 37" in body
    assert not any(
        s in body for s in ("cache_ttl=37", "hidden context", "Earlier topic", "private reasoning", "host reminder")
    )
    (journal,) = project.glob(".memsearch/memory/*.md")
    assert "- Blue Lantern expires after 37 minutes." in journal.read_text()
    assert f"session:session turn:message-0002 transcript:{path}" in journal.read_text()
    assert not (tmp_path / ".memsearch").exists()
    assert not (home / "unexpected-native").exists()
