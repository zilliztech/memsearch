"""Contract tests for the remote rerank adapter, without network calls."""

import copy
import http.client
import io
import json
import threading
import urllib.error
import urllib.request
import urllib.response
from email.message import Message
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from memsearch.core import MemSearch
from memsearch.remote_reranker import DEFAULT_URL, RemoteReranker
from memsearch.reranker import rerank


@pytest.fixture(autouse=True)
def _hermetic_reranker_environment(monkeypatch):
    """Keep operator env (tunnel URLs, hosted keys) out of the contract tests."""
    monkeypatch.delenv("MEMSEARCH_REMOTE_RERANKER_URL", raising=False)
    monkeypatch.delenv("MEMSEARCH_REMOTE_RERANKER_API_KEY", raising=False)


@pytest.fixture
def mock_transport(monkeypatch):
    """Replace only transport, keeping urllib's response and redirect handlers."""
    monkeypatch.setattr("urllib.request._opener", None)
    monkeypatch.setattr("urllib.request.getproxies", dict)

    def patch(handler):
        def open_http(_self, request):
            return handler(request, request.timeout)

        monkeypatch.setattr("urllib.request.HTTPHandler.http_open", open_http)
        monkeypatch.setattr("urllib.request.HTTPSHandler.https_open", open_http)

    return patch


def http_response(request, body, *, code=200, location=None):
    headers = Message()
    if location is not None:
        headers["Location"] = location
    result = urllib.response.addinfourl(io.BytesIO(body), headers, request.full_url, code)
    result.msg = http.client.responses[code]
    return result


def response(scores):
    return {
        "model": "Qwen3-Reranker-8B",
        "results": [{"index": index, "relevance_score": score} for index, score in enumerate(scores)],
        "usage": {"documents": len(scores)},
    }


def open_request(scores, calls):
    def handler(request, timeout):
        calls.append((request, timeout))
        return http_response(request, json.dumps(response(scores)).encode())

    return handler


def test_dispatch_strips_prefix_and_scores_every_candidate(mock_transport):
    candidates = [
        {"content": "long memory " * 2000, "source": "a.md", "score": 9},
        {"content": "second", "source": "b.md", "chunk_id": "b"},
        {"content": "third", "source": "c.md"},
    ]
    before = copy.deepcopy(candidates)
    calls = []
    mock_transport(open_request([0.2, 0.8, 0.8], calls))

    ranked = rerank("question", candidates, model_name="remote:Qwen3-Reranker-8B", top_k=2)

    assert [r["source"] for r in ranked] == ["b.md", "c.md"]
    assert ranked[0]["chunk_id"] == "b"
    assert candidates == before
    assert len(calls) == 1
    request, timeout = calls[0]
    payload = json.loads(request.data)
    assert payload == {
        "model": "Qwen3-Reranker-8B",
        "query": "question",
        "documents": [c["content"] for c in candidates],
    }
    assert request.full_url == DEFAULT_URL
    assert request.get_header("Content-type") == "application/json"
    assert timeout == 60


def test_url_comes_from_environment(monkeypatch):
    monkeypatch.setenv("MEMSEARCH_REMOTE_RERANKER_URL", "http://127.0.0.1:9999/rerank")
    assert RemoteReranker().url == "http://127.0.0.1:9999/rerank"
    assert RemoteReranker(url="http://explicit/rerank").url == "http://explicit/rerank"


def test_unranked_candidates_are_dropped(mock_transport):
    # A top_n response ranks only two of the four candidates.
    short = {"model": "Qwen3-Reranker-8B", "results": [{"index": 2, "relevance_score": 0.9}]}
    calls = []

    def handler(request, timeout):
        calls.append(request)
        return http_response(request, json.dumps(short).encode())

    mock_transport(handler)
    candidates = [{"content": f"passage {i}"} for i in range(4)]
    ranked = RemoteReranker().rerank("question", candidates)
    assert [r["content"] for r in ranked] == ["passage 2"]


def test_empty_candidates_need_no_request(mock_transport):
    def fail(*args, **kwargs):
        raise AssertionError("empty candidate list must not reach the network")

    mock_transport(fail)
    assert RemoteReranker().rerank("query", []) == []
    assert RemoteReranker().evaluate("query", []) == {"model": "Qwen3-Reranker-8B", "results": []}


@pytest.mark.parametrize("body", [b"<html>not json</html>", b"\xff"])
def test_malformed_body_raises_runtime_error(mock_transport, body):
    # A 200 with a non-JSON body must surface as RuntimeError like every
    # other transport failure, not as a raw JSONDecodeError.
    mock_transport(lambda request, timeout: http_response(request, body))
    with pytest.raises(RuntimeError, match="malformed response"):
        RemoteReranker().rerank("query", [{"content": "text"}])


def test_empty_results_payload_raises(mock_transport):
    empty = {"model": "Qwen3-Reranker-8B", "results": []}
    mock_transport(lambda request, timeout: http_response(request, json.dumps(empty).encode()))
    with pytest.raises(RuntimeError, match="no results"):
        RemoteReranker().rerank("query", [{"content": "text"}])


def test_bearer_header_follows_the_api_key(mock_transport):
    calls = []

    def handler(request, timeout):
        calls.append(request)
        return http_response(request, json.dumps(response([0.5])).encode())

    mock_transport(handler)
    RemoteReranker(api_key="secret").rerank("query", [{"content": "text"}])
    assert calls[-1].get_header("Authorization") == "Bearer secret"
    RemoteReranker().rerank("query", [{"content": "text"}])
    assert calls[-1].get_header("Authorization") is None


def test_api_key_comes_from_environment_and_constructor_takes_precedence(monkeypatch, mock_transport):
    monkeypatch.setenv("MEMSEARCH_REMOTE_RERANKER_API_KEY", "environment-DUMMY-KEY")
    calls = []
    mock_transport(open_request([0.5], calls))

    RemoteReranker().rerank("query", [{"content": "text"}])
    assert calls[-1][0].get_header("Authorization") == "Bearer environment-DUMMY-KEY"
    RemoteReranker(api_key="constructor-DUMMY-KEY").rerank("query", [{"content": "text"}])
    assert calls[-1][0].get_header("Authorization") == "Bearer constructor-DUMMY-KEY"
    with pytest.raises(ValueError, match="plain http"):
        RemoteReranker(url="http://relay.example.com/v1/rerank")


def test_api_key_over_plain_http_is_restricted_to_loopback():
    with pytest.raises(ValueError, match="plain http"):
        RemoteReranker(url="http://relay.example.com/v1/rerank", api_key="secret")
    # https to the same host is fine, and loopback stays allowed so SSH
    # tunnels and local gateways keep working.
    RemoteReranker(url="https://relay.example.com/v1/rerank", api_key="secret")
    RemoteReranker(url="http://127.0.0.1:8081/v1/rerank", api_key="secret")
    RemoteReranker(url="http://localhost:8081/v1/rerank", api_key="secret")


@pytest.mark.parametrize("code", [301, 302, 303, 307, 308])
@pytest.mark.parametrize(
    "destination",
    [
        pytest.param("https://trusted-origin.invalid/capture", id="same-origin"),
        pytest.param("http://trusted-origin.invalid/capture", id="same-host-downgrade"),
        pytest.param("https://other-origin.invalid/capture", id="cross-origin-https"),
        pytest.param("http://other-origin.invalid/capture", id="cross-origin-downgrade"),
    ],
)
@pytest.mark.parametrize("api_key", ["", "redirect-DUMMY-NOT-A-SECRET"], ids=["no-key", "bearer"])
def test_redirects_are_refused_without_requesting_destination(mock_transport, code, destination, api_key):
    url = "https://trusted-origin.invalid/v1/rerank"
    calls = []

    def redirect(request, timeout):
        calls.append(request)
        # Both HTTP and HTTPS use this fake transport. Following a Location
        # fails here, before any network call can send credentials or text.
        assert request.full_url == url, "redirect destination must never be requested"
        return http_response(request, b"private redirect body", code=code, location=destination)

    mock_transport(redirect)
    with pytest.raises(RuntimeError, match=f"^Remote reranking failed \\(HTTP {code}\\)$") as exc:
        RemoteReranker(url=url, api_key=api_key).rerank("private query", [{"content": "private text"}])

    assert "private" not in str(exc.value)
    assert len(calls) == 1
    assert calls[0].full_url == url
    assert calls[0].get_method() == "POST"
    assert calls[0].get_header("Authorization") == (f"Bearer {api_key}" if api_key else None)
    assert json.loads(calls[0].data)["documents"] == ["private text"]


def test_request_does_not_use_or_replace_global_opener(monkeypatch, mock_transport):
    global_opener = Mock()
    global_opener.open.side_effect = AssertionError("reranker must use its own opener")
    install_opener = Mock(side_effect=AssertionError("reranker must not install a global opener"))
    monkeypatch.setattr("urllib.request._opener", global_opener)
    monkeypatch.setattr("urllib.request.install_opener", install_opener)
    calls = []
    mock_transport(open_request([0.5], calls))

    ranked = RemoteReranker().rerank("query", [{"content": "text"}])

    assert ranked == [{"content": "text", "score": 0.5}]
    assert len(calls) == 1
    assert urllib.request._opener is global_opener
    global_opener.open.assert_not_called()
    install_opener.assert_not_called()


@pytest.mark.parametrize("score", [None, True, "0.5", float("nan"), float("inf")])
def test_invalid_scores_fail(score):
    result = response([0.5])
    result["results"][0]["relevance_score"] = score
    with pytest.raises(ValueError, match="score"):
        RemoteReranker.scores(result, 1)


@pytest.mark.parametrize("index", [-1, 1, 4, "0", True, False, None])
def test_invalid_indexes_fail(index):
    # False (== 0) passes the range check for any count, so this case is what
    # actually pins the isinstance-bool exclusion; True is rejected by the
    # range check alone whenever the payload has a single candidate.
    result = response([0.5])
    result["results"][0]["index"] = index
    with pytest.raises(ValueError, match="index"):
        RemoteReranker.scores(result, 1)


def test_missing_results_or_duplicates_fail():
    with pytest.raises(ValueError, match="results list"):
        RemoteReranker.scores({"model": "x"}, 1)
    duplicated = {"results": [{"index": 0, "relevance_score": 0.1}, {"index": 0, "relevance_score": 0.2}]}
    with pytest.raises(ValueError, match="duplicate"):
        RemoteReranker.scores(duplicated, 2)


@pytest.mark.parametrize("code", [401, 429, 503])
def test_http_errors_do_not_leak_body_or_fall_back(mock_transport, code):
    def fail(*args, **kwargs):
        raise urllib.error.HTTPError(DEFAULT_URL, code, "private payload", {}, None)

    mock_transport(fail)
    with pytest.raises(RuntimeError, match=f"HTTP {code}") as exc:
        RemoteReranker().rerank("query", [{"content": "private text"}])
    assert "private" not in str(exc.value)


@pytest.mark.parametrize(
    "error",
    [
        http.client.RemoteDisconnected("Remote end closed connection"),
        urllib.error.URLError("private transport error"),
        TimeoutError("private timeout"),
    ],
)
def test_remote_transport_failure_is_explicit(mock_transport, error):
    def disconnect(*args, **kwargs):
        raise error

    mock_transport(disconnect)
    with pytest.raises(RuntimeError, match="failed or timed out") as exc:
        RemoteReranker().rerank("query", [{"content": "text"}])
    assert "private" not in str(exc.value)


def test_invalid_configuration():
    with pytest.raises(ValueError):
        RemoteReranker(model="")
    with pytest.raises(ValueError):
        RemoteReranker(timeout=0)
    with pytest.raises(ValueError):
        RemoteReranker().rerank("q", [], top_k=-1)


def test_url_scheme_is_restricted(monkeypatch):
    # Only http/https are acceptable fetch targets; other schemes are a
    # classic SSRF vector and are rejected at construction time.
    with pytest.raises(ValueError, match="http or https"):
        RemoteReranker(url="file:///etc/passwd")
    with pytest.raises(ValueError, match="http or https"):
        RemoteReranker(url="ftp://internal/x")
    monkeypatch.setenv("MEMSEARCH_REMOTE_RERANKER_URL", "gopher://internal:70/x")
    with pytest.raises(ValueError, match="http or https"):
        RemoteReranker()


@pytest.mark.asyncio
async def test_search_fetches_extra_candidates_and_returns_remote_top_k(mock_transport):
    candidates = [{"content": f"passage {i}", "chunk_id": str(i)} for i in range(6)]
    store = Mock()
    store.search.return_value = candidates
    mem = MemSearch.__new__(MemSearch)
    mem._embedder = SimpleNamespace(embed=AsyncMock(return_value=[[0.1, 0.2]]))
    mem._store = store
    mem._reranker_model = "remote:Qwen3-Reranker-8B"
    mem._reranker_url = None
    mem._reranker_api_key = None

    def remote_request(request, timeout):
        assert threading.current_thread() is not threading.main_thread()
        return http_response(request, json.dumps(response([0.1, 0.2, 0.3, 0.9, 0.4, 0.8])).encode())

    mock_transport(remote_request)
    results = await mem.search("question", top_k=2)
    assert [r["chunk_id"] for r in results] == ["3", "5"]
    assert store.search.call_args.kwargs["top_k"] == 6


# =====================================================================
# Config-level url / api_key forwarding (feature: reranker credentials
# live in ~/.memsearch/config.toml, immune to host env-var scrubbing).
# =====================================================================


def test_rerank_forwards_config_url_and_key(mock_transport, monkeypatch):
    """rerank() must thread url/api_key into RemoteReranker, not drop them."""
    from memsearch import remote_reranker
    from memsearch.remote_reranker import RemoteReranker as Real

    calls = []
    seen = {}
    mock_transport(open_request([0.5], calls))

    class Spy(Real):
        def __init__(self, *args, **kwargs):
            seen.update(kwargs)
            super().__init__(*args, **kwargs)

    # reranker.py imports RemoteReranker lazily inside rerank(), so the
    # patch target is the defining module, not memsearch.reranker.
    monkeypatch.setattr(remote_reranker, "RemoteReranker", Spy)
    rerank(
        "q",
        [{"content": "text"}],
        model_name="remote:m",
        url="http://127.0.0.1:9/v1/rerank",
        api_key="cfg-DUMMY-KEY",
    )
    assert seen["url"] == "http://127.0.0.1:9/v1/rerank"
    assert seen["api_key"] == "cfg-DUMMY-KEY"
    assert calls[-1][0].full_url == "http://127.0.0.1:9/v1/rerank"
    assert calls[-1][0].get_header("Authorization") == "Bearer cfg-DUMMY-KEY"


def test_rerank_without_url_and_key_keeps_env_fallback(mock_transport, monkeypatch):
    """url/api_key default None -> env fallback behaviour is unchanged."""
    from memsearch import remote_reranker
    from memsearch.remote_reranker import RemoteReranker as Real

    monkeypatch.setenv("MEMSEARCH_REMOTE_RERANKER_API_KEY", "env-DUMMY-KEY")
    seen = {}
    calls = []

    class Spy(Real):
        def __init__(self, *args, **kwargs):
            seen.update(kwargs)
            super().__init__(*args, **kwargs)

    monkeypatch.setattr(remote_reranker, "RemoteReranker", Spy)
    mock_transport(open_request([0.5], calls))
    rerank("q", [{"content": "text"}], model_name="remote:m")
    assert seen["url"] is None
    assert seen["api_key"] is None
    assert calls[-1][0].get_header("Authorization") == "Bearer env-DUMMY-KEY"


def test_reranker_config_fields_roundtrip(tmp_path, monkeypatch):
    """config set/get on the new trusted keys; literal values pass through."""
    import memsearch.config as config_mod

    monkeypatch.setattr(config_mod, "GLOBAL_CONFIG_PATH", tmp_path / "config.toml")
    config_mod.set_config_value("reranker.url", "https://relay.example/v1/rerank")
    config_mod.set_config_value("reranker.api_key", "cfg-DUMMY-KEY")
    cfg = config_mod.resolve_config()
    assert cfg.reranker.url == "https://relay.example/v1/rerank"
    assert cfg.reranker.api_key == "cfg-DUMMY-KEY"


@pytest.mark.asyncio
async def test_search_uses_configured_url_and_key(mock_transport):
    """MemSearch.search threads reranker_url/api_key into the remote call."""
    candidates = [{"content": f"passage {i}", "chunk_id": str(i)} for i in range(3)]
    store = Mock()
    store.search.return_value = candidates
    mem = MemSearch.__new__(MemSearch)
    mem._embedder = SimpleNamespace(embed=AsyncMock(return_value=[[0.1, 0.2]]))
    mem._store = store
    mem._reranker_model = "remote:m"
    mem._reranker_url = "http://127.0.0.1:9/v1/rerank"
    mem._reranker_api_key = "cfg-DUMMY-KEY"

    calls = []

    def remote_request(request, timeout):
        calls.append(request)
        return http_response(request, json.dumps(response([0.3, 0.1, 0.2])).encode())

    mock_transport(remote_request)
    results = await mem.search("question", top_k=2)
    assert calls[0].full_url == "http://127.0.0.1:9/v1/rerank"
    assert calls[0].get_header("Authorization") == "Bearer cfg-DUMMY-KEY"
    assert [r["chunk_id"] for r in results] == ["0", "2"]
