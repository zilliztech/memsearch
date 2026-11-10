"""Evaluate frozen retrieval candidates with Jev or Voyage; never regenerate embeddings."""

# ruff: noqa: T201

from __future__ import annotations

import argparse
import csv
import hashlib
import http.client
import json
import math
import os
import statistics
import tempfile
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

from memsearch.jev_reranker import JevReranker


def metrics(ids: list[str], positives: list[str]) -> dict[str, float]:
    gold = set(positives)
    if not gold or len(ids) != len(set(ids)):
        raise ValueError("Metrics require nonempty gold labels and unique candidate IDs")
    hits = [int(cid in gold) for cid in ids[:10]]
    ideal = sum(1 / math.log2(i + 2) for i in range(min(10, len(gold))))
    return {
        "hit_at_1": float(any(hits[:1])),
        "hit_at_5": float(any(hits[:5])),
        "hit_at_10": float(any(hits)),
        "recall_at_1": sum(hits[:1]) / len(gold),
        "recall_at_5": sum(hits[:5]) / len(gold),
        "recall_at_10": sum(hits) / len(gold),
        "mrr_at_10": next((1 / (i + 1) for i, hit in enumerate(hits) if hit), 0.0),
        "ndcg_at_10": sum(hit / math.log2(i + 2) for i, hit in enumerate(hits)) / ideal,
    }


def read_jsonl(path: Path, key: str) -> dict[str, Any]:
    rows = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
    indexed = {row[key]: row for row in rows}
    if len(indexed) != len(rows):
        raise ValueError(f"Duplicate {key} in {path.name}")
    return indexed


def voyage_request(payload: dict[str, Any]) -> dict[str, Any]:
    key = os.environ.get("VOYAGE_API_KEY")
    if not key:
        raise ValueError("Set VOYAGE_API_KEY")
    request = urllib.request.Request(
        "https://api.voyageai.com/v1/rerank",
        data=json.dumps(payload).encode(),
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            return json.load(response)
    except urllib.error.HTTPError as exc:
        raise RuntimeError(f"Voyage reranking failed (HTTP {exc.code})") from None
    except (urllib.error.URLError, http.client.HTTPException, TimeoutError):
        raise RuntimeError("Voyage reranking request failed or timed out") from None


def validate_voyage(response: dict[str, Any], count: int) -> list[int]:
    indexes = [item["index"] for item in response["data"]]
    if len(indexes) != count or set(indexes) != set(range(count)):
        raise ValueError("Voyage returned missing or duplicate candidate indices")
    return indexes


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, required=True)
    parser.add_argument("--candidates", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--reuse-cache", type=Path, action="append", default=[])
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--preflight", action="store_true")
    args = parser.parse_args()
    if not 1 <= args.workers <= 12:
        parser.error("workers must be between 1 and 12")
    # Keep the published experiment reproducible when the runtime default advances.
    jev = JevReranker(model="jev-1.13.0")
    candidates_rows = json.loads(args.candidates.read_text())
    candidates = {r["query_id"]: r["retrieved_ids"] for r in candidates_rows}
    if len(candidates) != len(candidates_rows):
        raise ValueError("Duplicate candidate query IDs")
    datasets = {}
    tasks = []
    sources = {str(args.candidates.name): hashlib.sha256(args.candidates.read_bytes()).hexdigest()}
    for lang in ("zh", "en"):
        corpus = read_jsonl(args.data_dir / f"corpus_{lang}.jsonl", "chunk_id")
        queries = read_jsonl(args.data_dir / f"queries_{lang}.jsonl", "query_id")
        if set(candidates) != set(queries):
            raise ValueError("Candidate coverage must exactly match the query set")
        for filename in (f"corpus_{lang}.jsonl", f"queries_{lang}.jsonl"):
            sources[filename] = hashlib.sha256((args.data_dir / filename).read_bytes()).hexdigest()
        datasets[lang] = (corpus, queries)
        for qid, query in sorted(queries.items()):
            ids = candidates[qid]
            if len(ids) != 10 or len(set(ids)) != 10:
                raise ValueError("This evaluation expects exactly ten unique candidates per query")
            if not query["positive_chunk_ids"] or not set(query["positive_chunk_ids"]) <= corpus.keys():
                raise ValueError("Missing positive references")
            documents = [corpus[cid]["content"] for cid in ids]
            for provider in ("jev", "voyage"):
                payload = (
                    jev.build_request(query["query"], documents)
                    if provider == "jev"
                    else {
                        "model": "rerank-3",
                        "query": query["query"],
                        "documents": documents,
                        "top_k": len(documents),
                        "truncation": False,
                    }
                )
                tasks.append((provider, lang, qid, payload))
    for qid in candidates:
        if datasets["zh"][1][qid]["positive_chunk_ids"] != datasets["en"][1][qid]["positive_chunk_ids"]:
            raise ValueError("Translated queries must preserve positive references")
    estimate = sum(
        (len(json.dumps(p, ensure_ascii=False).encode()) + 1024) * (0.042 if provider == "jev" else 0.05) / 1e6
        for provider, _, _, p in tasks
    )
    print(json.dumps({"requests": len(tasks), "conservative_byte_based_cost_estimate_usd": estimate}), flush=True)
    if args.preflight:
        return
    args.output.mkdir(parents=True, exist_ok=True)
    cache = args.output / "cache"
    cache.mkdir(exist_ok=True)
    manifest = {
        "input_sha256": sources,
        "models": [jev.model, "rerank-3"],
        "languages": ["zh", "en"],
        "query_count_per_language": len(candidates),
        "workers": args.workers,
        "candidate_policy": "Frozen Chinese BGE-M3 top-10 IDs and order, with corresponding English translations.",
        "prompt": jev.build_request("QUERY", ["CANDIDATE"]),
    }
    manifest_path = args.output / "manifest.json"
    if manifest_path.exists() and json.loads(manifest_path.read_text()) != manifest:
        raise ValueError("Output directory contains a different evaluation manifest")
    manifest_path.write_text(json.dumps(manifest, indent=2))

    def evaluate(task):
        provider, lang, qid, payload = task
        digest = hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()
        filename = f"{provider}-{digest}.json"
        for location in [cache, *args.reuse_cache]:
            file = location / filename
            if file.exists():
                result = json.loads(file.read_text())
                break
        else:
            start = time.perf_counter()
            for attempt in range(3):
                try:
                    if provider == "jev":
                        query = datasets[lang][1][qid]["query"]
                        docs = [datasets[lang][0][cid]["content"] for cid in candidates[qid]]
                        raw = jev.evaluate(query, docs)
                    else:
                        raw = voyage_request(payload)
                    break
                except RuntimeError as exc:
                    transient = any(code in str(exc) for code in ("429", "500", "502", "503", "504"))
                    if not transient or attempt == 2:
                        raise
                    time.sleep(2 ** (attempt + 1))
            result = {"response": raw, "latency_s": time.perf_counter() - start, "attempts": attempt + 1}
        raw = result["response"]
        if provider == "jev":
            if raw.get("model") != jev.model:
                raise ValueError("Unexpected Jev model version")
            jev.scores(raw, 10)
        else:
            validate_voyage(raw, 10)
        target = cache / filename
        if not target.exists():
            with tempfile.NamedTemporaryFile(mode="w", dir=cache, suffix=".tmp", delete=False) as file:
                file.write(json.dumps(result, indent=2))
                temporary = Path(file.name)
            temporary.replace(target)
        return (provider, lang, qid), result

    responses = {}
    failures = []
    started = time.perf_counter()
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = {pool.submit(evaluate, task): task[:3] for task in tasks}
        for n, future in enumerate(as_completed(futures), 1):
            try:
                key, result = future.result()
                responses[key] = result
            except Exception as exc:
                failures.append({"task": futures[future], "error_type": type(exc).__name__})
            if n % 200 == 0:
                print(
                    json.dumps(
                        {"completed": n, "failed": len(failures), "elapsed_s": round(time.perf_counter() - started, 1)}
                    ),
                    flush=True,
                )
    (args.output / "failures.json").write_text(json.dumps(failures, indent=2))
    if failures:
        raise SystemExit(f"{len(failures)} requests failed; rerun to resume from the cache. No aggregate published.")
    details = []
    for lang, (_, queries) in datasets.items():
        for qid, query in sorted(queries.items()):
            ids = candidates[qid]
            gold = query["positive_chunk_ids"]
            scores = jev.scores(responses[("jev", lang, qid)]["response"], 10)
            jev_ids = [ids[i] for i in sorted(range(10), key=lambda i: -scores[i])]
            voyage_ids = [ids[i] for i in validate_voyage(responses[("voyage", lang, qid)]["response"], 10)]
            details.append(
                {
                    "lang": lang,
                    "query_id": qid,
                    "query_type": query["query_type"],
                    "candidate_ids": ids,
                    "jev_ids": jev_ids,
                    "voyage_ids": voyage_ids,
                    "baseline": metrics(ids, gold),
                    "jev": metrics(jev_ids, gold),
                    "voyage": metrics(voyage_ids, gold),
                }
            )
    rows = []
    for lang in ("all", "zh", "en"):
        for kind in ("all", "simple", "complex", "multi_hop"):
            subset = [
                r
                for r in details
                if (lang == "all" or r["lang"] == lang) and (kind == "all" or r["query_type"] == kind)
            ]
            if not subset:
                continue
            rows.extend(
                {
                    "language": lang,
                    "query_type": kind,
                    "method": method,
                    "n": len(subset),
                    **{m: statistics.mean(r[method][m] for r in subset) for m in subset[0][method]},
                }
                for method in ("baseline", "jev", "voyage")
            )
    usage = []
    for provider in ("jev", "voyage"):
        for lang in ("zh", "en"):
            items = [r for (p, language, _), r in responses.items() if p == provider and language == lang]
            tokens = sum(r["response"]["usage"]["input_tokens" if provider == "jev" else "total_tokens"] for r in items)
            usage.append(
                {
                    "provider": provider,
                    "language": lang,
                    "requests": len(items),
                    "tokens": tokens,
                    "estimated_cost_usd": tokens * (0.042 if provider == "jev" else 0.05) / 1e6,
                    "mean_request_latency_s": statistics.mean(r["latency_s"] for r in items),
                    "retry_attempts": sum(r.get("attempts", 1) - 1 for r in items),
                }
            )
    report = {
        "manifest": manifest,
        "metrics": rows,
        "usage": usage,
        "complete": True,
        "failed_requests": 0,
        "limitations": [
            "English is a translation, not an independent set of questions.",
            "Frozen Chinese candidates isolate reranking; this is not English end-to-end retrieval.",
            "Costs use successful-response token usage and list prices, excluding unreported failed-request usage.",
            "Latency includes network and concurrent load; some responses may be reused from prior runs.",
        ],
    }
    (args.output / "details.json").write_text(json.dumps(details, indent=2))
    (args.output / "report.json").write_text(json.dumps(report, indent=2))
    with (args.output / "metrics.csv").open("w", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=list(rows[0]), lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    print(json.dumps({"complete": True, "usage": usage}), flush=True)


if __name__ == "__main__":
    main()
