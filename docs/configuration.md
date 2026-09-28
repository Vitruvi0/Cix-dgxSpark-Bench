# Configuration

## Machine

| | |
|---|---|
| Machine | ASUS GX10 |
| Platform | NVIDIA GB10, DGX Spark class, 121 GiB unified memory |
| OS | Ubuntu 24.04.5 LTS, aarch64 |
| Kernel | 6.17.0-1032-nvidia |
| GPU driver | 580.173.02 |

The exact values of each run are in its `versions.txt`.

## Model

**Qwen3.8-Flash-Next, NVFP4**, from
<https://huggingface.co/RadixArk/Qwen3.8-Flash-Next-NVFP4>. The published
checkpoint is quantized with NVFP4 on the routed experts only. We did not
quantize it.

From it we derive the **FP8 hybrid** variant with
[`serving/prepare-hybrid-checkpoint.sh`](../serving/prepare-hybrid-checkpoint.sh):
the experts stay NVFP4, the dense side layers (300 tensors in 4 shards) are
rewritten as fp8 blockwise 128×128. The conversion needs no GPU and takes about
10 minutes.

## Serving image

Three layers, each built locally:

1. `vllm/vllm-openai:qwen38-flash-next@sha256:fc120ece…5bf8`, the official
   vLLM image. vLLM inside it is commit `8e685d198`.
2. The patches of
   [blazux/qwen3.8-Flash-DGX](https://github.com/blazux/qwen3.8-Flash-DGX) at
   commit `ad8920d`, Apache-2.0, built with
   [`serving/build-base-image.sh`](../serving/build-base-image.sh). That
   Dockerfile also downloads, pinned by commit and checksum, the deterministic
   top-k kernel from the jschmied repository.
3. Our one-line fix to the tool-call parser, in
   [`serving/tool-choice-patch/`](../serving/tool-choice-patch/).

The patches of layer 2 are not ours and are not copied into this repository.
To rebuild the image you need a clone of the blazux repository at that commit.

### The tool-call parser fix

A request without tools has `tool_choice="none"` by default, but vLLM's parser
engine suppressed tool calls only when tools were present. In streaming, when
the model wrote tool-call markup on its own, the response ended with
`finish_reason="tool_calls"` although the client had offered no tool.

The fix changes one condition in `vllm/parser/engine/parser_engine.py`:

```diff
-            if tool_choice == "none" and tools:
+            if tool_choice == "none":
```

The patch script applies it only to the file with the reviewed hash and keeps
a copy of the original. Known limits: an explicit `tool_choice: null` is not
suppressed, and the branch with tools and `required` or a named tool is not
touched.

## Launch command

[`serving/launch-flashnext.sh`](../serving/launch-flashnext.sh).

| Setting | Value | Why |
|---|---|---|
| Speculative decoding | MTP, 2 speculative tokens | |
| `--enable-prefix-caching` | on | |
| `--max-num-seqs` | 8 | Upper bound on concurrent sequences |
| `--enable-chunked-prefill`, `--max-num-batched-tokens` | 8192 | Prefill proceeds in chunks of 8192 tokens |
| `--max-model-len` | 262144 | |
| `--gpu-memory-utilization` | 0.85 | 0.92 does not start on this machine |
| `--kv-cache-dtype` | auto | |
| Thinking | off by default | `--default-chat-template-kwargs '{"enable_thinking": false}'` |
| Tool calling | `--enable-auto-tool-choice --tool-call-parser qwen3_coder` | |
| Reasoning parser | `qwen3` | |
| CUDA graphs | `PIECEWISE`, with 12 splitting ops | The memory-mapped lookup runs outside the graphs |

### Environment variables

| Variable | Value | Effect |
|---|---|---|
| `VLLM_PLE_MMAP` | 1 | Keeps the n-gram lookup table (44–47 GiB) on NVMe through a memory map instead of loading it. Resident weights go from 122 to about 76 GiB |
| `VLLM_PLE_MMAP_WORKERS` | 32 | Workers of the memory-mapped lookup |
| `VLLM_PLE_MMAP_PREWARM` | 0 | Prewarm off. With it on we saw no reduction of the first request's TTFT |
| `VLLM_PLE_MMAP_MADVISE` | random | No readahead on the memory maps |
| `VLLM_QSA_EXACT_TOPK` | 0 | Turns off the older exact top-k workaround, replaced by the deterministic kernel |
| `VLLM_QSA_DET_TOPK`, `VLLM_QSA_DET_LIB` | 1, path of `_C_det.so` | Deterministic top-k kernel for the sparse attention |
| `VLLM_FP8_PAD_M4` | 0 | Turns off a padding operation that is on by default on this hardware; kept off for comparability with earlier runs |
| `VLLM_FP8_HYBRID` | 1 | Uses the FP8 hybrid checkpoint |
| `VLLM_USE_FLASHINFER_SAMPLER` | 1 | Taken as is from the blazux serving script |
| `VLLM_USE_DEEP_GEMM` | 0 | Part of the hybrid recipe |

`VLLM_MTP_DRAFT_VOCAB` is not set: the final recipe does not use a draft
vocabulary.

## A note on `versions.txt`

The lines starting with `patch:` list files such as `patch_fp8.py` and
`qwen4_exp_nvfp4.py`. Those are patches for the SGLang track. They are hashed
in every run because the script hashes the whole patch directory, but they are
not in the vLLM image. The lines starting with `terze:` are third-party
repositories; for vLLM only `qwen3.8-Flash-DGX` matters.

## The 27B baseline

Qwen3.8-27B NVFP4 on vLLM with MTP at depth 1 and prefix caching off:

```
vllm serve /modelli/Qwen3.8-27B-NVFP4 --served-model-name qwen27b --gpu-memory-utilization 0.85 \
  --default-chat-template-kwargs '{"enable_thinking": false}' \
  --speculative-config '{"method":"mtp","num_speculative_tokens":1}' \
  --enable-auto-tool-choice --tool-call-parser qwen3_coder --reasoning-parser qwen3
```

## What we dropped

**SGLang.** With speculative decoding on, the recipe we started from produced
garbled text under sustained load. See section 4 of
[results.md](results.md) for the counts and for the mitigation we found.
