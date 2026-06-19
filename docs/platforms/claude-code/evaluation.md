# Embedding Provider Evaluation

The Claude Code plugin defaults to **ONNX bge-m3 int8** because it gave the best practical trade-off we found for bilingual memory retrieval:

- **Strong Chinese + English retrieval quality**
- **No API key required**
- **Runs locally on CPU**
- **Smaller dependency footprint** than PyTorch-based local stacks

## Why this page exists

The full benchmark write-up originally lived only in `ccplugin/evaluation/README.md`, which is useful in the repository but easy to miss from the documentation site. This page makes the result discoverable from the docs navigation while keeping the benchmark source material linked.

## Benchmark summary

The evaluation compared cloud APIs, local transformer models, ONNX variants, and Ollama models using bilingual memory-retrieval queries derived from real memsearch logs.

### Main conclusion

**`gpahal/bge-m3-onnx-int8`** became the plugin default because it was the best practical default for Claude Code plugin users:

- **Top-tier bilingual retrieval** among local options
- **Very small quality drop** versus full PyTorch bge-m3
- **Much lighter install/runtime cost**
- **Works out of the box** for users who do not want to configure remote API credentials

### Operational trade-off

Compared with OpenAI embeddings, the ONNX default removes first-run credential friction and per-token API cost, at the expense of a one-time local model download.

## Full methodology and raw comparison

For the complete benchmark details — dataset construction, evaluated models, Recall@K / MRR metrics, ONNX vs. PyTorch comparison tables, and migration guidance — see the source evaluation document in the repository:

- <https://github.com/zilliztech/memsearch/blob/main/ccplugin/evaluation/README.md>

## Related docs

- [Claude Code Plugin Overview](index.md)
- [Installation](installation.md)
- [How It Works](how-it-works.md)
- [Memory Recall](memory-recall.md)
- [Troubleshooting](troubleshooting.md)
