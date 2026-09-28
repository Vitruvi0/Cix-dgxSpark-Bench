# Glossary: Italian to English

File names in this repository are in English. Inside the code, command-line
flags, CSV columns, identifiers and comments are still in Italian: they are
the ones that produced the published measurements, and the result files use
the same column names. This page translates what you will meet.

## Command-line flags

| Flag | Tool | Meaning |
|---|---|---|
| `--livelli 1,2,4,8` | `concurrency.py` | Concurrency levels: how many requests are sent at the same time, one pass per level |
| `--parole-prompt` | `concurrency.py` | Number of words in the synthetic prompt body |
| `--prompts <file>` | `concurrency.py`, `latency.py` | File with one prompt per line |
| `--salva-output <file>` | `concurrency.py`, `latency.py` | Append the generated text of every request to a JSONL file, the input of `validity.py` |
| `--classi corto=100,lungo8k=8000` | `latency.py` | Prompt classes as `name=length in tokens` |
| `--run` | `latency.py` | Measured runs per class (the protocol asks for at least 5) |
| `--corpus <file>` | `latency.py` | Real text: a different slice per run instead of a repeated sentence |
| `--corpus-inizio` | `latency.py` | Offset in characters of the first slice |
| `--corpus-passo` | `latency.py` | Distance in characters between slices |
| `--domanda` | `latency.py` | The question appended after the prompt body |
| `--tokenizer-locale <dir>` | `latency.py` | Calibrate prompt length with the local tokenizer instead of the server's `/tokenize` |
| `--intervallo` | `monitor_mem.py` | Sampling interval in seconds |

## CSV columns

| Column | Meaning |
|---|---|
| `run` | Identifier of one invocation of the tool |
| `livello` | Concurrency level of the request |
| `esito` | Outcome: `ok` or `errore` |
| `errore` | Error message, empty when the request succeeded |
| `conteggio` | Where the token count comes from: `usage` (reported by the server) or `chunk` (counted by the client). The two are different units and must not be compared |
| `ttft_ms` | Time to first token, milliseconds |
| `tok_s` | Decode tokens per second of the request |
| `prefill_tok_s` | Prompt tokens divided by TTFT |
| `decode_tok_s` | Decode tokens per second |
| `tok_s_wall` | Completion tokens divided by TTFT plus decode time |
| `itl_ms_media` | Inter-token latency, mean per token |
| `itl_ms_p50`, `itl_ms_p95` | Inter-token latency percentiles, per chunk |
| `n_chunk` | Number of stream chunks received |
| `t_invio`, `t_fine` | Send and end time on the monotonic clock; not comparable between runs |
| `fase` | Phase: label of the recipe or session under test |
| `punto` | Test point: the cell being measured, for example `n6` or `lungo8k` |
| `rip` | Repetition number |
| `classe` | Prompt class |
| `indice_prompt` | Index of the prompt inside its file |
| `warmup` | `True` for warm-up requests, which are excluded from the statistics |
| `modello` | Model |
| `richieste` | Requests completed |
| `fallite` | Requests failed |
| `invalide` | Responses flagged by the validity check during the run |
| `tok_s_aggregati` | Aggregate throughput: total tokens divided by the real window, from first send to last token |
| `tok_s_mediana_per_richiesta` | Median of the per-request decode tokens per second |
| `k` | Iteration number in a soak |
| `inizio_iso` | Start time, ISO 8601 |
| `durata_s` | Duration in seconds |
| `valido` | Valid: `si` or `no` |
| `problemi` | Issues found by the validity check |
| `usata_gib` | RAM used, GiB |
| `cache_gib` | Page cache, GiB |
| `swap_usato_gib` | Swap used, GiB |
| `metrica`, `cella`, `unita` | Metric, cell and unit in comparison tables |
| `delta_assoluto`, `delta_pct` | Absolute and percentage difference |

## Values and labels

| Italian | English |
|---|---|
| `corto` | short |
| `lungo8k` | long, 8000 tokens |
| `grezzo` / `raw` | A run outside the protocol: exploratory, not comparable with official runs |
| `mediana` | median |
| `righe` | rows |
| `segnalate` | flagged |
| `degenerate` | degenerate: garbled output |
| `verdetto` | verdict |
| `nessuna segnalazione` | no response flagged |
| `incompleto` | incomplete |
| `descrittivo` | descriptive: reported without a pass or fail judgement |
| `limiti` | limitations |
| `picco` | peak |
| `deriva` | drift |
| `copertura` | coverage |
| `finestra` | window |
| `ricetta` | recipe: the full serving configuration |
| `lancio` | launch command |
| `terze` | third-party repositories, in `versions.txt` |

## Run names

| Fragment | Meaning |
|---|---|
| `flashnext` | Qwen3.8-Flash-Next |
| `27b` | Qwen3.8-27B |
| `b6`, `b10` | Labels of two test series: `b6` compares engines and recipes, `b10` is multi-user load |
| `tcnone` | The image with the `tool_choice` "none" patch, which is the final one |
| `n1` … `n8` | Number of simultaneous users |
| `n4long`, `n6long` | Simultaneous users, each with an 8000-token prompt |
| `f2.12-nextn2-mamba40-…` | SGLang recipe labels: speculative depth 2, Mamba cache of 40 slots |
| `track128` | SGLang with `--mamba-track-interval 128` |
| `nospec` | Speculative decoding off |
| `soak` | Sustained load, 45 minutes |
