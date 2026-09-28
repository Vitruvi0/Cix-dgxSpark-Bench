# Results

Every number below is copied from a file in `results/` or, where the raw
material is not published, from the summary of the run that produced it.
Unless stated otherwise: Qwen3.8-Flash-Next NVFP4 (FP8 hybrid layers), vLLM
with MTP speculative decoding depth 2, thinking off, `temperature 0`,
`max_tokens 256`, no tools in the request. See
[configuration.md](configuration.md) for the recipe and
[methodology.md](methodology.md) for how each metric is defined.

**Read this first.** Each measurement comes from a single boot of the server.
The quartiles describe the spread inside that boot; they are not confidence
intervals, and boot-to-boot variability was not measured for the final recipe.
Completions in the short classes are short (33–82 tokens), and with
speculative decoding the decode formula overestimates by roughly 1–2 % on
short answers.

## 1. Single user (batch 1)

Source: `results/2026-09-16-flashnext-b6-vllm-tcnone/` — `grid-tcnone-*.csv`,
`analysis-tcnone.json`. Five repetitions per class, one request each.

| Prompt class | Prompt tokens | Decode tok/s, median (Q1–Q3) | TTFT ms, median (Q1–Q3) |
|---|---:|---:|---:|
| short | 124–130 | 30.89 (28.59–32.08) | 287.5 (285.7–288.4) |
| long8k | 8024–8028 | 30.81 (29.75–30.96) | 3510.1 (3508.6–3546.7) |
| code | ~1500 | 34.46 (34.35–36.33) | 887.1 |
| sme (small-business questions) | — | 33.14 (33.02–33.16) | 250.3 |

TTFT includes opening the HTTP connection. The `code` class was measured on a
proprietary source tree that is not published, so that row cannot be reproduced
byte for byte.

## 2. Concurrent users

Sources: `results/2026-09-16-cix-27b-concurrency-v02/06-flash/` (1, 2, 4, 8
users and 4 users with 8k-token prompts) and
`results/2026-09-17-cix-flash-n6-final-qualification/` (6 users). Five
repetitions per cell, identical frozen payloads, no retries, no outlier
removed. All cells completed every request with no HTTP error.

| Simultaneous users | Requests | Decode per request, median tok/s | Aggregate tok/s, median | TTFT median / p95 (ms) |
|---:|---:|---:|---:|---:|
| 1 | 5/5 | 28.80 | 25.07 | — |
| 2 | 10/10 | 30.48 | 38.84 | — |
| 4 | 20/20 | 22.53 | 50.63 | 524 / 529 |
| **6** | **30/30** | **20.11** | **57.32** | **597 / 687** |
| 8 | 40/40 | 18.41 | 81.66 | 562 / 695 |

At six users the per-request decode ranges from 13.73 to 31.29 tok/s
(Q1 18.81, Q3 21.73). Six users were measured in a different boot from the
other rows.

### Long prompts under concurrency

| Cell | Decode per request, median tok/s (min–max) | Aggregate tok/s | TTFT median / p95 (ms) |
|---|---:|---:|---:|
| 4 users × 8k-token prompt | 15.91 (6.77–23.75) | 13.78 | 15384 / 18416 |
| 6 users × 8k-token prompt | 10.39 (3.19–19.51) | 14.24 | 22886 / 27245 |

With six simultaneous 8k-token prompts every user receives the complete answer
29–32 s after sending. The decode distribution is bimodal: requests that start
decoding first share the scheduler with the prefill chunks of the others
(chunked prefill, 8192 tokens per step) and run at 3–9 tok/s; the last ones
decode at 17–19 tok/s.

## 3. Memory and temperature

| Window | Peak RAM used (GiB) | GPU max (°C) |
|---|---:|---:|
| 6 users, short prompts | 112.96 | 66 |
| 6 users, 8k-token prompts | 116.00 | 70 |
| 4 users, 8k-token prompts (different boot) | 117.09 | 70 |
| Batch-1 grid and concurrency, 80 min | 115.16 | 72 |
| 45-minute soak at 8 users | 115.11 | 70 |

The machine has 121 GiB of unified memory. The smallest headroom observed is
4.54 GiB. No out-of-memory kill, no crash, and the memory watchdog
(MemAvailable below 2 GiB) never triggered. Swap-out during the measurement
windows is between 0 and 11 pages.

## 4. Stability under sustained load

Batches of 8 concurrent requests, back to back, for 45 minutes. Every response
is checked by `harness/validity.py` during the run and scanned again offline.

| Engine and recipe | Boots | Responses | Flagged as degenerate |
|---|---:|---:|---:|
| **vLLM, final recipe** | 1 | 1576 | **0** |
| SGLang, speculative depth 2, `--mamba-track-interval 64` | 1 | 1456 | 9 (0.62 %) |
| SGLang, same recipe, three boots together | 3 | 2968 | 15 |
| SGLang, speculative decoding off | 2 | 2400 | 0 |
| SGLang, speculative depth 2, `--mamba-track-interval 128` | 2 | 2968 | 0 |

Sources: `results/2026-09-16-flashnext-b6-vllm-tcnone/soak-tcnone-soak-summary.csv`,
`analysis-soak.json`, and `results/2026-09-04-flashnext-sglang/soak-*-summary.csv`.
The `invalide` column of the SGLang files holds the in-run count; the offline
scan found more (9 against 4 in the 1456-response run), and the offline counts
are the ones in the table.

What this does and does not show:

- Zero flagged responses does not prove zero corrupted responses. The checks
  are heuristic (NaN tokens, repetition, non-Latin script, scattered
  characters).
- On SGLang the corruption appeared only with speculative decoding on, and
  disappeared in two boots after raising the Mamba track interval to 128. That
  is a mitigation we observed, not an identified root cause.
- The vLLM and SGLang soaks ran under different conditions (the vLLM soak
  followed 80 minutes of other measurements in the same boot). They are not a
  controlled comparison between the two engines.

vLLM aggregate throughput during the soak: median 80.26 tok/s (Q1–Q3
76.80–86.53), drift between first and last third +2.08 %, TTFT p95 median
628.1 ms.

## 5. Flash-Next against Qwen3.8-27B

Source: `results/2026-09-16-cix-27b-concurrency-v02/07-comparison/comparison.csv`.

| Cell | 27B decode median (tok/s) | Flash-Next decode median (tok/s) | Difference |
|---|---:|---:|---:|
| 1 user | 17.74 | 28.80 | +62.3 % |
| 2 users | 18.32 | 30.48 | +66.3 % |
| 4 users | 17.88 | 22.53 | +26.0 % |
| 8 users | 16.77 | 18.41 | +9.8 % |
| 4 users × 8k-token prompt | 8.07 | 15.91 | +97.2 % |

This is a descriptive comparison: model and recipe were not isolated. The 27B
ran with MTP depth 1 and prefix caching off, Flash-Next with MTP depth 2 and
prefix caching on. The advantage of Flash-Next is close to 2× only with long
prompts and shrinks as concurrency grows; on aggregate throughput with four
long prompts the 27B is 5.8 % ahead.

## 6. Tool calling and instruction following

Measured with [Inspect AI](https://inspect.aisi.org.uk/) 0.3.261 and
`inspect_evals` 0.19.0. Summary files are in `2026-09-10-inspect`,
`2026-09-10-inspect-multiturn` and `2026-09-15-flashnext-inspect-tcnone`; the
raw `.eval` logs are not published.

| Benchmark | 27B | Flash-Next, final image |
|---|---:|---:|
| BFCL single-turn, 300 items | 0.8633 ± 0.0199 | 0.7533 ± 0.0249 |
| IFEval strict, 300 prompts | 0.8400 | 0.8233 |
| BFCL multi-turn, 200 conversations | not measured | 0.565 ± 0.0351 |

- Single-turn runs were **sampled, not greedy**: Inspect dropped the
  temperature parameter, so the model's generation config applied
  (temperature 1.0, top_k 20, top_p 0.95, seed 42).
- The IFEval difference is not statistically significant (z = −0.73); that is
  not a proof of equivalence.
- The multi-turn result is marked **raw**: one conversation hit the message
  limit, so the validity gate did not pass. An earlier image scored 0.590 on
  the same set, also raw.

## 7. Behaviour inside the application

The application is a retrieval-augmented assistant over company documents with
nine tools. The evaluation set is synthetic (60 cases plus robustness cases)
and is not part of this repository, so these figures cannot be reproduced from
here.

- **Tool selection: 249 of 273 turns correct (91.2 %)** under the rule fixed
  before the run. 273 is 91 turns × 3 passes. Under a rule changed after
  seeing the data, which also accepts an explicit document search on five
  turns, the count is 260 of 273 (95.2 %); that recount is not a preregistered
  measurement.
- Quality scores in the run reports come from an LLM judge. The answers were
  also reviewed by hand by the authors; that review has no score sheet among
  the published files.

## 8. Other models and weight formats

Earlier phases of the campaign. The run column is the directory under
`results/`.

| Date | Model and setup | Engine | Decode tok/s, short / 8k prompt | Run | Notes |
|---|---|---|---:|---|---|
| 31 Aug | DeepSeek-V4-Flash, GGUF IQ2_XXS | ds4 | 16.74 at 2k context, 13.57 at 64k | `2026-08-31-ds4-bench` | **Raw**: one exploratory run, desktop session active |
| 1 Sep | Qwen3.8-27B, BF16, as shipped | vLLM 0.27.1 | 4.53 / 4.49 | `2026-09-01-vllm-baseline-qwen27b` | TTFT 366 ms / 6711 ms. Peak RAM 114.3 GiB |
| 2 Sep | Qwen3.8-27B, FP8 | vLLM 0.27.1 | — / 7.8 | `2026-09-02-vllm-lever-b-qwen27b` | |
| 2 Sep | Qwen3.8-27B, NVFP4 | vLLM 0.27.1 | 11.1 / 10.9 | `2026-09-02-vllm-ngram-prompt-real` | Real text |
| 2 Sep | Qwen3.8-27B, NVFP4, n-gram prompt lookup | vLLM 0.27.1 | 20.9 / 13.4 | `2026-09-02-vllm-ngram-prompt-real` | Real text. On a repeated sentence the gain is much larger and misleading |
| 16 Sep | Qwen3.8-27B, NVFP4, MTP depth 1 | vLLM | 17.74 | `2026-09-16-cix-27b-concurrency-v02` | One user |
| 15 Sep | Qwen3.8-Flash-Next, NVFP4 + FP8 hybrid, MTP depth 2 | vLLM | 30.89 / 30.81 | `2026-09-16-flashnext-b6-vllm-tcnone` | Section 1 |

Quality of the 27B by weight format, full test sets, measured with lm-eval
0.4.13 (`2026-09-02-lmeval-qwen27b-quant`):

| | BF16 | FP8 | NVFP4 |
|---|---:|---:|---:|
| ARC-it, 0-shot, normalized accuracy | 60.1 % | 59.8 % | 59.8 % |
| GSM8K, 5-shot, strict match | 69.9 % | 68.4 % | 72.9 % |

NVFP4 is within one standard error of BF16 on ARC-it. Part of the GSM8K
difference comes from formatting: BF16 returned 51 empty answers against 38.
