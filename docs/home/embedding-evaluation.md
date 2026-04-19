# Embedding Model Evaluation

The Claude Code plugin ships with **ONNX bge-m3 int8** as the default embedding model. This page documents the benchmark we ran to pick it — which models we tested, what dataset we used, and why this one won.

> **Just want the setup path?** Start with [Getting Started](../getting-started.md), then see [Configuration](configuration.md) for provider settings or [For Agent Developers](for-developers.md) for integration details.


If you just want the answer: on our real-world memory-retrieval benchmark (955 chunks / 2172 bilingual queries), `gpahal/bge-m3-onnx-int8` lost only ~1% recall to the full-precision PyTorch model while cutting the on-disk model size from 2.2 GB to 558 MB and dropping the `torch` dependency entirely. It also outperforms OpenAI `text-embedding-3-small` on Chinese retrieval (Recall@5 0.776 vs 0.717), so we can ship a zero-config default that is better than the old API-key default on real user data.

---

## Goal

Pick a default embedding model for the memsearch Claude Code plugin that is:

- **Good at bilingual retrieval** — memsearch users write memory in both Chinese and English; a model that crashes on one language is unusable.
- **Local and zero-config** — no API key, no GPU requirement, no `torch` install.
- **Small enough to auto-download** on first use without scaring users.
- **Cheap on a loaded CPU** — embedding happens on every file write via the watcher.

## Dataset

We built the evaluation set from real memsearch memory logs (`.memsearch/memory/*.md`) collected across 12 projects, so the domain matches what users actually index.

1. **Collect** — Scan markdown memory files, chunk by heading using memsearch's `chunk_markdown()`.
2. **Clean** — Remove HTML comments, drop short chunks (<50 chars), sanitize sensitive data (paths, IPs, tokens).
3. **Annotate** with `gpt-4o-mini`:
    - **Simple** (1 per chunk) — straightforward factual questions.
    - **Complex** (1 per substantial chunk) — reasoning-required questions.
    - **Multi-hop** (group related chunks by project + date) — questions needing 2+ chunks to answer.
4. **Translate** — Chinese ↔ English for bilingual coverage.

Final dataset: **955 chunks × 2172 queries** (955 simple + 926 complex + 291 multi-hop), available in both Chinese and English.

## Models evaluated

12 models across four categories, plus two ONNX variants of bge-m3:

| # | Provider | Model | Size |
|---|----------|-------|------|
| 1 | openai | `text-embedding-3-small` | API |
| 2 | openai | `text-embedding-3-large` | API |
| 3 | local | `BAAI/bge-m3` (PyTorch) | 1.7 GB |
| 4 | local | `sentence-transformers/all-MiniLM-L6-v2` | 91 MB |
| 5 | local | `intfloat/multilingual-e5-small` | 471 MB |
| 6 | local | `intfloat/multilingual-e5-base` | 1.1 GB |
| 7 | local | `Qwen/Qwen3-Embedding-0.6B` | ~1.2 GB |
| 8 | local | `paraphrase-multilingual-MiniLM-L12-v2` | 471 MB |
| 9 | local | `paraphrase-multilingual-mpnet-base-v2` | 1.1 GB |
| 10 | ollama | `nomic-embed-text` | 274 MB |
| 11 | ollama | `mxbai-embed-large` | 669 MB |
| 12 | ollama | `dengcao/Qwen3-Embedding-8B` (Q5_K_M) | 5.4 GB |
| — | onnx | `bge-m3` ONNX fp32 | 2.2 GB |
| — | onnx | `gpahal/bge-m3-onnx-int8` | 558 MB |

## Metrics

For each model we measured retrieval quality using:

- **Recall@K** (K = 1, 5, 10) — does the correct chunk appear in the top-K results?
- **MRR** — Mean Reciprocal Rank; average position of the first correct result.
- **NDCG@10** — normalized discounted cumulative gain.

For the Claude Code plugin use case (the skill surfaces ~top 3–5 chunks), **Recall@5** is the primary metric and MRR is secondary.

## Results

Ranked by Chinese Recall@5 (our primary metric — English is easy mode for most multilingual models):

| Rank | Model | Size | zh R@5 | en R@5 | zh MRR | en MRR |
|------|-------|------|--------|--------|--------|--------|
| 1 | **BAAI/bge-m3** (PyTorch) | 1.7 GB | **0.783** | **0.815** | 0.637 | 0.661 |
| 2 | **bge-m3 ONNX int8** | 558 MB | **0.776** | 0.814 | 0.642 | — |
| 3 | `text-embedding-3-large` | API | 0.750 | 0.797 | 0.603 | 0.636 |
| 4 | `Qwen3-Embedding-0.6B` | ~1.2 GB | 0.739 | 0.733 | 0.588 | 0.573 |
| 5 | `text-embedding-3-small` | API | 0.717 | 0.767 | 0.574 | 0.615 |
| 6 | `multilingual-e5-small` | 471 MB | 0.653 | 0.741 | 0.520 | 0.586 |
| 7 | `multilingual-e5-base` | 1.1 GB | 0.644 | 0.733 | 0.512 | 0.586 |
| 8 | `paraphrase-multilingual-mpnet` | 1.1 GB | 0.548 | 0.672 | 0.413 | 0.519 |
| 9 | `paraphrase-multilingual-MiniLM` | 471 MB | 0.550 | 0.640 | 0.412 | 0.498 |
| 10 | `nomic-embed-text` | 274 MB | 0.402 | 0.756 | 0.287 | 0.608 |
| 11 | `mxbai-embed-large` | 669 MB | 0.377 | 0.743 | 0.269 | 0.597 |
| 12 | `all-MiniLM-L6-v2` | 91 MB | 0.203 | 0.651 | 0.129 | 0.503 |
| 13 | `Qwen3-Embedding-8B` (Q5) | 5.4 GB | 0.201 | 0.230 | 0.140 | 0.166 |

### ONNX vs PyTorch, same bge-m3 weights

| Variant | Model size | zh R@5 | Quality vs PyTorch baseline | Runtime deps |
|---------|-----------|--------|------------------------------|--------------|
| PyTorch fp32 (GPU) | 2.2 GB | 0.783 | baseline | `torch` + `sentence-transformers` (~2 GB+) |
| ONNX fp32 (CPU) | 2.2 GB | 0.791 | +1.1 % | `onnxruntime` (~200 MB) |
| ONNX int8 (CPU) | 558 MB | 0.776 | −1.1 % | `onnxruntime` (~200 MB) |

## Key findings

1. **bge-m3 is the best model overall** — it beats all 12 competitors on both Chinese and English.
2. **ONNX int8 quantization costs only ~1 %** while shrinking the model from 2.2 GB to 558 MB and the runtime deps from ~2 GB to ~200 MB.
3. **CPU is enough** — no GPU required, so any development machine can run it.
4. **Ollama English-centric models collapse on Chinese** — `nomic-embed-text` and `mxbai-embed-large` score well on English but zh R@5 < 0.40. Not safe as a bilingual default.
5. **Q5 quantization destroys embedding quality.** `Qwen3-Embedding-8B` at Q5 ranked last despite being 5.4 GB. Quantization is not free at the 5-bit level for embeddings.
6. **OpenAI large is barely better than small** — +3–4 % at double the cost. Not worth it for memory retrieval.

## Why we switched to ONNX bge-m3

The previous Claude Code plugin default was OpenAI `text-embedding-3-small`, which required every new user to obtain an API key before the plugin would work and incurred per-token cost forever after. We switched to ONNX bge-m3 int8 because:

- **No API key required** — truly zero-config; the plugin works immediately after install.
- **CPU-only** — no GPU needed, accessible on every laptop.
- **Small enough to auto-download** — 558 MB on first use, cached at `~/.cache/huggingface/hub/`.
- **Comparable or better quality** — roughly equal to OpenAI `text-embedding-3-small` on English, and **meaningfully better on Chinese** (0.776 vs 0.717 Recall@5 on our data).
- **Completely free** — no per-token API cost; everything runs locally.
- **Lightweight deps** — `onnxruntime` + `tokenizers` + `huggingface-hub` (~200 MB) instead of `torch` + `sentence-transformers` (~2 GB+).

## Backward compatibility

- **Python API users are not affected.** The Python API default remains `openai` / `text-embedding-3-small`. Only the Claude Code plugin hooks changed.
- **Existing plugin users with OpenAI-indexed memory** need to re-index after switching, because the embedding dimensions differ (1024 vs 1536):

  ```bash
  memsearch config set embedding.provider onnx
  memsearch index .memsearch/memory/ --force
  ```

- **Users with an explicit `embedding.provider` in `.memsearch.toml` or `~/.memsearch/config.toml` are unaffected** — your config still wins.

To pre-download the ONNX model instead of waiting for the first-use download:

```bash
uvx --from 'memsearch[onnx]' memsearch search --provider onnx "warmup" 2>/dev/null || true
```

## Conclusion

`gpahal/bge-m3-onnx-int8` is the Claude Code plugin default because it is the only model on our benchmark that simultaneously hits **top-tier bilingual quality, zero-config install, CPU-only execution, a <600 MB on-disk footprint, and no `torch` dependency**. Every other model in the evaluation failed on at least one of those axes.

The raw data, annotation scripts, and reproduction steps live in the `evaluation/` directory at the repo root.
