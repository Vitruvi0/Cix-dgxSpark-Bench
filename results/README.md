# Results

Metric files of every benchmark run of the campaign. One directory per run,
named `YYYY-MM-DD-<benchmark>`. [docs/results.md](../docs/results.md) reads
them.

## What is in a run directory

- `*.csv`: one row per request, per level or per sample, metrics only
- `versions.txt`: kernel, driver, model identity, third-party commits, hashes
  of the measurement scripts
- `analysis-*.json`, `summary-*.json`, `results*.json`: computed summaries

Files are copied byte for byte from our working repository; only names were
translated. The one exception is `versions.txt`: lines that list the
uncommitted files and the worktree of our working repository were removed,
because they describe the repository and not the measurement. The commit and
branch the measurement code was run from are still there.
[`FILE-MAP.csv`](FILE-MAP.csv) gives, for every file, the original name, the
sha256 and the number of lines removed. Column names are in Italian: see
[the glossary](../docs/glossary.md).

## Runs behind the published numbers

| Run | Content |
|---|---|
| `2026-09-16-flashnext-b6-vllm-tcnone` | vLLM, final image: one-user grid, 1 to 8 users, 45-minute soak, memory monitor |
| `2026-09-17-cix-flash-n6-final-qualification` | Flash-Next at 6 users, short and long prompts |
| `2026-09-16-cix-27b-concurrency-v02` | Qwen3.8-27B against Flash-Next at 1, 2, 4, 8 users and 4 users with long prompts |
| `2026-09-04-flashnext-sglang` | SGLang: grids, quality, and 45-minute soaks, one set of files per recipe and boot |
| `2026-09-15-flashnext-inspect-tcnone` | Tool calling and instruction following on the final image |

## All runs, by phase

| Dates | Runs | What was measured |
|---|---|---|
| 31 Aug | `ds4-bench`, `gsm8k`, `arc-it-routeA`, `arc-it-routeB` | DeepSeek-V4-Flash on ds4: speed and quality, exploratory |
| 1–2 Sep | `vllm-baseline-qwen27b`, `vllm-levers-qwen27b`, `vllm-lever-b-qwen27b`, `vllm-isolation-nvfp4`, `vllm-ngram-prompt-real`, `lmeval-qwen27b-quant` | Qwen3.8-27B: what each setting and each weight format is worth, in speed and in quality |
| 3–8 Sep | `vllm-27b-spec1`, `vllm-27b-control`, `vllm-27b-k3-quality`, `vllm-27b-spec2`, `vllm-27b-pin-boot` | Qwen3.8-27B with speculative decoding: depth 1 to 3, reproducibility between boots |
| 4 Sep | `flashnext-tokenizer` | Tokens per word of the Flash-Next tokenizer on Italian, English and code |
| 4–16 Sep | `flashnext-sglang`, `flashnext-controls`, `flashnext-b6-track128`, `flashnext-b6-sglang128-bis`, `flashnext-inspect-sglang128`, `flashnext-sglang-toolcalling` | Flash-Next on SGLang |
| 5–16 Sep | `flashnext-vllm`, `flashnext-vllm-w3`, `flashnext-vllm-head`, `flashnext-vllm-head-2`, `flashnext-vllm-head-f5`, `flashnext-b6`, `flashnext-b6-r2`, `flashnext-b6-vllm-tcnone`, `flashnext-vllm-equiv-images` | Flash-Next on vLLM, from the first build to the final image |
| 10–15 Sep | `inspect`, `inspect-multiturn`, `flashnext-inspect-tcnone` | BFCL and IFEval |
| 14–15 Sep | `flashnext-draftho-diagnosis`, `flashnext-nodraft-replay`, `flashnext-vllm-toolchoice-patch`, `flashnext-vllm-toolchoice-confirmation` | The tool-call parser problem: diagnosis, fix, confirmation |
| 16–17 Sep | `cix-27b-concurrency-v02`, `cix-flash-n6-final-qualification` | Multi-user qualification |

Many of these are steps along the way: recipes that were tried and replaced.
The runs of 31 August are exploratory, a single pass each, and are not
comparable with the others.

## Not published

Generated text, server logs, request and response bodies, evaluation logs, and
the runs of the assistant itself (retrieval and tools), whose files carry the
product's prompts.
