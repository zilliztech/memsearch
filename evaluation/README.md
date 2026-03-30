# Embedding Provider Evaluation

This document describes the evaluation methodology and results used to select the default embedding provider for the memsearch Claude Code plugin.

## Goal

Benchmark a wide range of embedding models — from cloud APIs to local open-source options — to find a lightweight, practical default for the memsearch Claude Code plugin. The ideal model should perform well on both Chinese and English memory retrieval, run locally without an API key or GPU, and have a small dependency footprint.

## Dataset

The evaluation dataset was built from real-world memsearch memory logs (`.memsearch/memory/*.md` files) collected across 12 projects. The pipeline:

1. **Collect** — Scan markdown memory files, chunk by heading using memsearch's `chunk_markdown()`
2. **Clean** — Remove HTML comments, short chunks (<50 chars), sanitize sensitive data (paths, IPs, tokens)
3. **Annotate** — Generate queries with `gpt-4o-mini`:
   - **Simple** (1 per chunk): straightforward factual questions
   - **Complex** (1 per substantial chunk): reasoning-required questions
   - **Multi-hop** (group related chunks by project+date): questions requiring information from 2+ chunks
4. **Translate** — Chinese→English translation for bilingual evaluation

Final dataset: **955 chunks × 2172 queries** (955 simple + 926 complex + 291 multi-hop), in both Chinese and English.

## Models Evaluated

12 embedding models were benchmarked across 4 categories:

| # | Provider | Model | Size |
|---|----------|-------|------|
| 1 | openai | text-embedding-3-small | API |
| 2 | openai | text-embedding-3-large | API |
| 3 | local | BAAI/bge-m3 (PyTorch) | 1.7GB |
| 4 | local | sentence-transformers/all-MiniLM-L6-v2 | 91MB |
| 5 | local | intfloat/multilingual-e5-small | 471MB |
| 6 | local | intfloat/multilingual-e5-base | 1.1GB |
| 7 | local | Qwen/Qwen3-Embedding-0.6B | ~1.2GB |
| 8 | local | paraphrase-multilingual-MiniLM-L12-v2 | 471MB |
| 9 | local | paraphrase-multilingual-mpnet-base-v2 | 1.1GB |
| 10 | ollama | nomic-embed-text | 274MB |
| 11 | ollama | mxbai-embed-large | 669MB |
| 12 | ollama | dengcao/Qwen3-Embedding-8B (Q5_K_M) | 5.4GB |

Additionally, ONNX variants of bge-m3 were tested:
- bge-m3 ONNX fp32 (2.2GB)
- bge-m3 ONNX int8 — `gpahal/bge-m3-onnx-int8` (558MB)

## Metrics

For each model, retrieval was evaluated on:
- **Recall@K** (K=1, 5, 10): does the correct chunk appear in top K results?
- **MRR** (Mean Reciprocal Rank): average position of first correct result
- **NDCG@10**: normalized discounted cumulative gain

For the Claude Code plugin use case (user typically sees top 3-5 results), **Recall@5** is the primary metric, with **MRR** as secondary.

## Results

Ranked by Chinese Recall@5 (primary metric):

| Rank | Model | Size | zh R@5 | en R@5 | zh MRR | en MRR |
|------|-------|------|--------|--------|--------|--------|
| 1 | **BAAI/bge-m3 (PyTorch)** | 1.7GB | **0.783** | **0.815** | 0.637 | 0.661 |
| 2 | **bge-m3 ONNX int8** | 558MB | **0.776** | 0.814 | 0.642 | — |
| 3 | openai/text-embedding-3-large | API | 0.750 | 0.797 | 0.603 | 0.636 |
| 4 | Qwen/Qwen3-Embedding-0.6B | ~1.2GB | 0.739 | 0.733 | 0.588 | 0.573 |
| 5 | openai/text-embedding-3-small | API | 0.717 | 0.767 | 0.574 | 0.615 |
| 6 | intfloat/multilingual-e5-small | 471MB | 0.653 | 0.741 | 0.520 | 0.586 |
| 7 | intfloat/multilingual-e5-base | 1.1GB | 0.644 | 0.733 | 0.512 | 0.586 |
| 8 | paraphrase-multilingual-mpnet | 1.1GB | 0.548 | 0.672 | 0.413 | 0.519 |
| 9 | paraphrase-multilingual-MiniLM | 471MB | 0.550 | 0.640 | 0.412 | 0.498 |
| 10 | nomic-embed-text | 274MB | 0.402 | 0.756 | 0.287 | 0.608 |
| 11 | mxbai-embed-large | 669MB | 0.377 | 0.743 | 0.269 | 0.597 |
| 12 | all-MiniLM-L6-v2 | 91MB | 0.203 | 0.651 | 0.129 | 0.503 |
| 13 | Qwen3-Embedding-8B (Q5) | 5.4GB | 0.201 | 0.230 | 0.140 | 0.166 |

### ONNX vs PyTorch Comparison

| Variant | Model Size | zh R@5 | Quality vs PyTorch | Dependencies |
|---------|-----------|--------|-------------------|--------------|
| PyTorch fp32 (GPU) | 2.2GB | 0.783 | baseline | torch + sentence-transformers (~2GB+) |
| ONNX fp32 (CPU) | 2.2GB | 0.791 | +1.1% | onnxruntime (~200MB) |
| ONNX int8 (CPU) | 558MB | 0.776 | -1.1% | onnxruntime (~200MB) |

## Key Findings

1. **BAAI/bge-m3 is the best model overall** — outperforms all 12 competitors on both Chinese and English
2. **ONNX int8 quantization loses only 1.1%** — model size drops from 2.2GB to 558MB, dependencies from ~2GB to ~200MB
3. **No GPU required** — ONNX runs on CPU, making it accessible to all users
4. **Ollama models perform poorly on Chinese** — nomic-embed-text and mxbai-embed-large have good English scores but zh R@5 < 0.40
5. **Q5 quantization destroys embedding quality** — Qwen3-Embedding-8B Q5 scored last despite being 5.4GB
6. **OpenAI large offers marginal improvement** — only +3-4% over OpenAI small, at double the cost

## Why We Switched to ONNX bge-m3

The previous Claude Code plugin default was OpenAI `text-embedding-3-small`, which required users to obtain and configure an API key before the plugin would work. This created friction for new users and incurred per-token API costs. The switch to ONNX bge-m3 int8 was motivated by:

- **No API key required** — zero-config experience, the plugin works immediately after installation
- **Runs entirely on CPU** — no GPU needed, accessible to all development machines
- **Small model size** — int8 quantization reduces the model from 2.2GB to 558MB, auto-downloaded on first use
- **Comparable quality** — only ~1% lower than OpenAI `text-embedding-3-small` on our benchmark, and actually outperforms it on Chinese retrieval (zh R@5: 0.776 vs 0.717)
- **Completely free** — no per-token API cost, all computation is local
- **Lightweight dependencies** — `onnxruntime` + `tokenizers` + `huggingface-hub` (~200MB) vs `torch` + `sentence-transformers` (~2GB+)

## Conclusion

Based on the benchmark results, **`gpahal/bge-m3-onnx-int8`** stands out as the best practical choice and is adopted as the Claude Code plugin default embedding model:

- **Top bilingual quality** among all local models (zh R@5=0.776, en R@5=0.814) — even outperforms OpenAI `text-embedding-3-small`
- **Minimal quality trade-off** — only 1.1% loss vs full PyTorch fp32, while model size drops from 2.2GB to 558MB
- **Zero-config** — no API key, no GPU, runs on CPU via ONNX Runtime
- **Lightweight dependencies** — `onnxruntime` + `tokenizers` + `huggingface-hub` (~200MB total) vs `torch` + `sentence-transformers` (~2GB+)
- **Auto-downloaded** on first use (558MB), cached locally for subsequent sessions

### Backward Compatibility

- **Python API users**: not affected. The Python API default remains `openai` / `text-embedding-3-small`
- **Claude Code plugin users**: the plugin hooks now default to `onnx` provider. Users with existing memory indexed by OpenAI embeddings will need to re-index (`memsearch index --force`) after switching, since the embedding dimensions differ (1024 vs 1536)
- **Explicit config**: users who have set `embedding.provider` in `.memsearch.toml` or `~/.memsearch/config.toml` are unaffected

## Upgrade Guide

For existing Claude Code plugin users who want to switch from OpenAI to the new ONNX default:

```bash
# Switch provider to ONNX
memsearch config set embedding.provider onnx

# Re-index all memory files (required — embedding dimensions differ)
memsearch index .memsearch/memory/ --force
```

The ONNX model (~558MB) will be downloaded automatically on first use and cached at `~/.cache/huggingface/hub/`. To pre-download it:

```bash
uvx --from 'memsearch[onnx]' memsearch search --provider onnx "warmup" 2>/dev/null || true
```
