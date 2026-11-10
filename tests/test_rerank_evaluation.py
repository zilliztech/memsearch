"""Check metric semantics and complete candidate coverage."""

import hashlib
import importlib.util
import json
import math
import sys
from pathlib import Path

import pytest

spec = importlib.util.spec_from_file_location(
    "rerank_evaluate", Path(__file__).parents[1] / "evaluation" / "rerank_evaluate.py"
)
evaluation = importlib.util.module_from_spec(spec)
spec.loader.exec_module(evaluation)


def test_multihop_recall_is_fraction_of_gold_not_hit_rate():
    result = evaluation.metrics(["irrelevant", "a", "other"], ["a", "b"])
    assert result["recall_at_1"] == 0
    assert result["recall_at_5"] == 0.5
    assert result["hit_at_1"] == 0
    assert result["hit_at_5"] == 1
    assert result["hit_at_10"] == 1
    assert result["mrr_at_10"] == 0.5
    assert result["ndcg_at_10"] == pytest.approx((1 / math.log2(3)) / (1 + 1 / math.log2(3)))


def test_absent_positives_are_not_dropped():
    assert all(v == 0 for v in evaluation.metrics(["x", "y"], ["z"]).values())


def test_perfect_ranking_and_top_ten_limit():
    result = evaluation.metrics(["a", "b"], ["a", "b"])
    assert result["ndcg_at_10"] == 1
    assert result["recall_at_10"] == 1
    assert evaluation.metrics([str(i) for i in range(11)], ["10"])["mrr_at_10"] == 0


def test_invalid_candidate_or_gold_sets():
    with pytest.raises(ValueError):
        evaluation.metrics(["a", "a"], ["a"])
    with pytest.raises(ValueError):
        evaluation.metrics(["a"], [])


def test_voyage_index_coverage():
    with pytest.raises(ValueError):
        evaluation.validate_voyage({"data": [{"index": 0}, {"index": 0}]}, 2)
    assert evaluation.validate_voyage({"data": [{"index": 1}, {"index": 0}]}, 2) == [1, 0]


def test_full_runner_resumes_cached_bilingual_responses_without_credentials(tmp_path, monkeypatch):
    data = tmp_path / "data"
    data.mkdir()
    cache = tmp_path / "cache"
    cache.mkdir()
    output = tmp_path / "output"
    ids = [str(i) for i in range(10)]
    candidate_file = data / "candidates.json"
    candidate_file.write_text(json.dumps([{"query_id": qid, "retrieved_ids": ids} for qid in ("q1", "q2")]))
    for lang in ("zh", "en"):
        docs = [f"{lang} document {i}" for i in ids]
        corpus = [{"chunk_id": cid, "content": doc} for cid, doc in zip(ids, docs, strict=True)]
        query = {"query_id": "q1", "query": f"{lang} query", "query_type": "simple", "positive_chunk_ids": ["0"]}
        (data / f"corpus_{lang}.jsonl").write_text("\n".join(json.dumps(r) for r in corpus))
        (data / f"queries_{lang}.jsonl").write_text(
            "\n".join(json.dumps({**query, "query_id": qid}) for qid in ("q1", "q2"))
        )
        for provider in ("jev", "voyage"):
            if provider == "jev":
                payload = evaluation.JevReranker(model="jev-1.13.0").build_request(query["query"], docs)
                raw = {
                    "model": "jev-1.13.0",
                    "usage": {"input_tokens": 100},
                    "answers": {f"d{i}": {"type": "noul", "noul": 1.0 if i == 0 else 0.0} for i in range(10)},
                }
            else:
                payload = {
                    "model": "rerank-3",
                    "query": query["query"],
                    "documents": docs,
                    "top_k": 10,
                    "truncation": False,
                }
                raw = {"data": [{"index": i} for i in reversed(range(10))], "usage": {"total_tokens": 100}}
            digest = hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()
            (cache / f"{provider}-{digest}.json").write_text(json.dumps({"response": raw, "latency_s": 0.1}))

    def no_network(*args, **kwargs):
        raise AssertionError("Cached evaluation must not call an API")

    monkeypatch.setattr("urllib.request.urlopen", no_network)
    monkeypatch.delenv("TYPESAFE_API_KEY", raising=False)
    monkeypatch.delenv("VOYAGE_API_KEY", raising=False)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "rerank_evaluate",
            "--data-dir",
            str(data),
            "--candidates",
            str(candidate_file),
            "--output",
            str(output),
            "--reuse-cache",
            str(cache),
        ],
    )
    evaluation.main()
    report = json.loads((output / "report.json").read_text())
    assert report["complete"]
    all_jev = next(
        r for r in report["metrics"] if r["language"] == "all" and r["query_type"] == "all" and r["method"] == "jev"
    )
    assert all_jev["n"] == 4
    assert all_jev["mrr_at_10"] == 1.0
    assert all_jev["hit_at_5"] == 1.0
    assert len(list((output / "cache").glob("*.json"))) == 4
