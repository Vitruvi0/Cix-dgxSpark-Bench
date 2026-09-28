# Cix-dgxSpark-Bench

Configuration, test harness and results of a benchmark campaign on an
**ASUS GX10**, an NVIDIA GB10 machine of the DGX Spark class with 121 GiB of
unified memory. The campaign ran from 31 August to 22 September 2026.

We are building CIX, an assistant that answers questions over a company's own
documents and runs entirely on a machine in the customer's office. The question
behind the campaign was practical:

> Can one unit serve six people at once, and with which model and engine?

This repository holds what is needed to check our answer: the serving recipe,
the tools that produced the numbers, and the numbers.

The work is by [Advaisor S.r.l.](https://advaisor.it)

## The answer

Yes, with **Qwen3.8-Flash-Next** served by **vLLM**.

| | |
|---|---|
| One user, generation speed | 30.9 tokens per second |
| One user, wait for the first token | 0.29 s on a short prompt, 3.5 s on an 8000-token prompt |
| Six users at once | 30 of 30 requests served, 20.1 tokens per second each, first token in 0.6 s |
| Six users, each with an 8000-token prompt | 30 of 30 served, full answer after 29–32 s |
| Peak memory | 117 GiB of 121, no out-of-memory, no crash |
| 45 minutes at eight users | 1576 responses, none flagged as garbled |

Speeds are medians of five repetitions. **Each figure comes from a single boot
of the server**, so it tells you what the machine did, not how much it varies
from one start to the next. The full tables, with quartiles and with what the
numbers do not show, are in [docs/results.md](docs/results.md).

## Models tested

Three models, in the order we tried them.

| Model | Weight formats | Engines | Role in the campaign |
|---|---|---|---|
| DeepSeek-V4-Flash | GGUF at 2 bits (IQ2_XXS) | ds4 | First days: bring-up of the machine. Exploratory runs |
| Qwen3.8-27B | BF16, FP8, NVFP4 | vLLM | Baseline, and the model used to measure what each weight format and each setting is worth |
| **Qwen3.8-Flash-Next** | NVFP4, NVFP4 with FP8 hybrid layers | SGLang, vLLM | **The one we chose** |

Generation speed with one user:

| Model and setup | Tokens per second |
|---|---:|
| DeepSeek-V4-Flash, 2-bit GGUF, ds4 | 16.7 |
| Qwen3.8-27B, BF16, vLLM as shipped | 4.5 |
| Qwen3.8-27B, NVFP4 | 11.1 |
| Qwen3.8-27B, NVFP4, speculative depth 1 | 17.7 |
| **Qwen3.8-Flash-Next, NVFP4 with FP8 hybrid, speculative depth 2** | **30.9** |

Moving the 27B from BF16 to NVFP4 cost no measurable quality: 60.1 % against
59.8 % on ARC-it, 69.9 % against 72.9 % on GSM8K.

The DeepSeek figure is a single exploratory run. Section 8 of
[docs/results.md](docs/results.md) has the details and the run behind each
number.

### Why this model

We compared Flash-Next with the larger Qwen3.8-27B. Flash-Next generates
faster for each user: 62 % faster with one user, 26 % with four, 10 % with
eight, and close to twice as fast when prompts are long. The 27B is better at
tool calling (86 % against 75 % on BFCL), which matters less for an assistant
that mostly reads documents.

### Why this engine

We started on SGLang. With speculative decoding on, under 45 minutes of load,
it returned garbled text in 9 of 1456 responses. A setting change made the
problem disappear in two later runs, but we did not find the cause, so we
moved to vLLM.

## What is here

```
serving/    the recipe: launch command, image build, checkpoint conversion,
            and our fix to vLLM's tool-call parser
harness/    the measurement tools and their tests, Python standard library only
results/    metric files of every benchmark run of the campaign, 40 runs
docs/       configuration, methodology, results, glossary
```

| Document | Read it for |
|---|---|
| [docs/configuration.md](docs/configuration.md) | The machine, the model, how the image is built, every flag and environment variable |
| [docs/methodology.md](docs/methodology.md) | How a number becomes a result: protocol, metric definitions, prompt classes, validity checks |
| [docs/results.md](docs/results.md) | Every number with its source file and its caveats |
| [docs/glossary.md](docs/glossary.md) | Italian flags, CSV columns and labels, translated |
| [harness/README.md](harness/README.md) | How to run each tool |

## Measure your own server

The harness needs only Python 3 and an endpoint that speaks the OpenAI chat
API with streaming. It works with any model and engine.

```bash
# unit tests: no GPU, no Docker, no network
python3 -m unittest discover -s harness

# one user: first-token wait and generation speed, short and long prompt
python3 harness/latency.py --url http://localhost:8000 --model <name> \
  --corpus <a text file of at least 100 KB> --out latency.csv

# several users at once: 1, 2, 4, 6 and 8
python3 harness/concurrency.py --url http://localhost:8000 --model <name> \
  --livelli 1,2,4,6,8 \
  --prompts results/2026-09-16-flashnext-b6-vllm-tcnone/prompts/domains-b10.txt \
  --out concurrency.csv
```

Each tool writes one CSV row per request. Column names are in Italian; the
[glossary](docs/glossary.md) translates them.

## Rebuild our server

1. Get the model from
   [RadixArk/Qwen3.8-Flash-Next-NVFP4](https://huggingface.co/RadixArk/Qwen3.8-Flash-Next-NVFP4).
2. Clone [blazux/qwen3.8-Flash-DGX](https://github.com/blazux/qwen3.8-Flash-DGX)
   at commit `ad8920d` and build the image:
   `SRC=<clone> serving/build-base-image.sh`
3. Add our parser fix:
   `docker build --network none -t flashnext-vllm:blazux-ad8920d-tcnone serving/tool-choice-patch`
4. Convert the checkpoint, about 10 minutes and no GPU:
   `MODELS_DIR=<dir> TOOLS=<clone>/tools serving/prepare-hybrid-checkpoint.sh`
5. Start the server: `MODELS_DIR=<dir> serving/launch-flashnext.sh`

[docs/configuration.md](docs/configuration.md) explains each step.

## Terms used

| Term | Meaning |
|---|---|
| Token | The unit a model reads and writes; roughly three quarters of a word |
| TTFT | Time to first token: how long the user waits before text starts to appear |
| Decode | The generation phase, after the prompt has been read |
| NVFP4, FP8 | Ways of storing the model's weights in fewer bits, to fit in memory |
| MTP, speculative decoding | The model drafts several tokens ahead and keeps the ones that turn out right, which speeds up generation |
| Soak | A test under constant load for a long time, here 45 minutes |

## Language

File names and documentation are in English. Inside the code, flags such as
`--livelli`, CSV columns such as `esito`, and comments are in Italian: they are
the ones that produced the measurements, and we did not change them after the
fact.

## What is not here

- **Generated text, server logs and evaluation logs.** Only metrics are
  published. The exception is three short garbled answers in
  `harness/fixtures/`, kept as test cases for the validity check.
- **The code corpus.** One prompt class used our own source code.
- **The application's evaluation set.** The figures about the assistant, in
  section 7 of the results, cannot be reproduced from this repository.
- **The patches to vLLM by third parties.** They belong to the blazux
  repository and are fetched from there.

## License

[Apache License 2.0](LICENSE). See [NOTICE](NOTICE) for attributions.
