# Harness

Measurement tools for OpenAI-compatible endpoints with streaming. Python
standard library only, so they run on the machine under test without
installing anything. Two optional exceptions are noted below.

Flags and CSV columns are in Italian; see [the glossary](../docs/glossary.md).

```bash
python3 -m unittest discover -s harness   # from the repository root
```

## `latency.py`: one user

TTFT, prefill, decode and inter-token latency at batch 1. Prompt classes by
length, 2 warm-up runs and 6 measured runs per class, each with a unique
prompt head.

```bash
# short (~100 tokens) and long (8000 tokens) prompts on real text
python3 latency.py --url http://localhost:8000 --model flashnext \
  --corpus corpora/text.txt --out latency.csv

# smoke test
python3 latency.py --model flashnext --run 1 --warmup 1 --max-tokens 32 --out /tmp/smoke.csv
```

`--tokenizer-locale <checkpoint dir>` calibrates prompt length with the local
tokenizer instead of the server's `/tokenize`; it needs the `tokenizers`
package. Without `--corpus` the prompt is a repeated sentence, the ideal case
for speculative decoding: use real text for numbers you intend to publish.

## `concurrency.py`: several users

Sends N requests at the same time for each level and writes two files: one row
per request, and `<out>-aggregates.csv` with one row per level.

```bash
python3 concurrency.py --url http://localhost:8000 --model flashnext \
  --livelli 1,2,4,8 --prompts prompts.txt --out concurrency.csv
```

One pass per level: run it again for repetitions. A failed request is a row
with `esito=errore` and the exit code is 1.

## `validity.py`: is the output real text

```bash
python3 latency.py ... --salva-output run.jsonl
python3 validity.py --output run.jsonl        # exit 1 if any row is flagged
```

## Other tools

| Tool | Purpose |
|---|---|
| `monitor_mem.py --out mem.csv [--pid N]` | RAM, page cache, swap, major faults, disk sectors and GPU temperature every 2 s |
| `phase_memory.py mem-*.csv` | Peak and deltas of a phase, as a markdown table |
| `grid_table.py <phase>-*.csv` | Median and quartiles table from `latency.py` files |
| `acceptance.py server.log` | Acceptance length of speculative decoding, from SGLang or vLLM server logs |
| `tokenizer_eff.py --tok n=dir --corpus n=file` | Tokens per word and bytes per token; needs `tokenizers` |
| `versions.sh <run dir> <model dir> [images]` | Writes `versions.txt` |
| `driver-lib.sh` | Shell functions for unattended runs: wait for `/health`, drop the page cache, monitor, grid, validity. `DRY=1` prints the commands |
| `auto-drop.sh <status file>` | Drops the page cache when a driver asks for it |

`driver-lib.sh` reads `MODELLO_DIR`, `CORPUS_IT`, `CORPUS_CODE`, `PYVENV` and
`PORTA` from the environment.
