# Methodology

## Protocol

1. **At least five runs per point, reported as median and quartiles.**
   Quartiles use the inclusive method. A single run is never a result.
2. **One variable at a time.** Two recipes are compared only if one thing
   differs between them. When that was not possible, the comparison is
   labelled descriptive.
3. **Full versioning.** Every run directory has a `versions.txt` written by
   `harness/versions.sh`: kernel, OS, GPU driver, model identity (hash of
   `config.json` and of the safetensors index, number and size of shards),
   third-party commits, and the hash of the measurement scripts. A number
   without it is not recorded.
4. **Runs outside the protocol are labelled raw** and are not compared with
   official ones.
5. **No transparent retry, no extra repetition, no outlier removed.** A failed
   request is a row with outcome `errore`, the aggregate counts survivors
   separately, and the tool exits non-zero.
6. **Generated text is checked.** A throughput number whose output was not
   validated is not recorded: a corrupted stream accepts every speculative
   draft and inflates tokens per second by 2–3×.

## Request settings

`temperature 0`, `max_tokens 256`, streaming, thinking off
(`chat_template_kwargs: {"enable_thinking": false}`), no `tools` and no
`tool_choice` in the request, token counts taken from the server's `usage`.

## Keeping the prefix cache cold

The server runs with prefix caching on. Identical prompts would make TTFT and
prefill look better from the second request onwards, so every request starts
with a unique head: a run nonce, the concurrency level and the request index.
This holds between clients of the same level and between repetitions.

For concurrency tests the prompt bodies also differ between clients. Identical
prompts inflate aggregate throughput.

## Metrics

| Metric | Definition |
|---|---|
| TTFT | Send to first chunk with content, over the full HTTP path, including opening the connection in the batch-1 client |
| Prefill tok/s | Prompt tokens divided by TTFT. An upper bound: it includes tokenization and scheduling |
| Decode tok/s | (completion tokens − 1) divided by the time between first and last chunk |
| Inter-token latency, mean | 1000 divided by decode tok/s, per token |
| Inter-token latency, p50 and p95 | Gaps between consecutive chunks, per chunk |
| Aggregate tok/s | Total tokens of a batch divided by the real window, first send to last token |

With speculative decoding one chunk carries several accepted tokens, so the
percentiles are per chunk while the mean is per token. The `n_chunk` column
says how many chunks a response had.

Chunks are timestamped on arrival and parsed after the stream ends, and in the
concurrency client the TCP connection is opened before the simultaneous start.
Neither TTFT nor the decode window contains client overhead.

## Prompt classes

| Class | Length | Body |
|---|---|---|
| `corto` (short) | ~100 tokens | Slices of *I promessi sposi* (public domain, Italian) |
| `lungo8k` (long) | 8000 tokens | Same corpus, a different slice per run |
| `code` | 1500 tokens | Source code. We used a proprietary source tree that is not published |
| `sme` | one question | Questions a small business would ask, in Italian, in `results/*/prompts/domains-b10.txt` |

Length is calibrated with the model's tokenizer. Synthetic prompts, a sentence
repeated, are the ideal case for speculative decoding and are not used for the
published numbers.

## Concurrency tests

- The harness makes **one pass per level**; repetitions come from running it
  again. The `run` column tells passes apart.
- **Payloads are frozen before the run** and hashed. No nonce is generated
  during the measurement, and no measurement payload appears in the warm-up.
- **Warm-up is by time**: 300 s of load at the start, then 60 s before each
  measurement, from a separate pool of frozen payloads.
- All repetitions of a cell run before moving to the next cell.

## Sustained load

Batches of 8 concurrent requests, back to back for 45 minutes, with a memory
watchdog that stops the run if available memory goes below 2 GiB. Each response
is validated during the run and scanned again offline.

## Validity checks

`harness/validity.py` flags, per response:

- NaN that became token 0, visible as runs of `!`;
- repetition;
- a closing `</think>` inside the content;
- an answer cut unusually short;
- decode speed above 2.5× the median of the run, the sign of a stream that
  accepts every draft;
- degenerate text: non-Latin script, repeated punctuation, scattered letters,
  code blocks excluded.

These are heuristics for Italian and English prose. Long foreign names or
quotations can be flagged, and the absence of flags does not prove the text is
correct.

## Memory and temperature

`harness/monitor_mem.py` samples every 2 seconds: RAM used, page cache, swap,
swap-in and swap-out counters, major page faults, disk sectors read and
written, GPU temperature. `harness/phase_memory.py` turns a monitor file into
the peak and the deltas for a phase.

Before each server start the page cache is dropped. On this machine a full
page cache makes the GPU allocation fail with `NV_ERR_NO_MEMORY`.

## What was not measured

- Boot-to-boot variability of the final recipe: each published point is one
  boot.
- Reuse of partial prefixes by the prefix cache.
- Anything beyond the 45-minute window of the soak.
