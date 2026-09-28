#!/bin/bash
# Final serving recipe: Qwen3.8-Flash-Next NVFP4 (FP8 hybrid side layers) on vLLM.
#
# Every flag and environment variable below is the one used for the published
# measurements (original command sha256 96035c23…, recorded in
# results/*/versions.txt). Only the container name, the models directory and
# the image reference are parameters here.
#
#   IMAGE       image built by tool-choice-patch/Dockerfile
#   MODELS_DIR  host directory holding Qwen3.8-Flash-Next-NVFP4-fp8hybrid
#
# --gpu-memory-utilization 0.85 is deliberate: on this machine 0.92 does not
# start, and a wrong value can reboot the host.
set -eu
IMAGE=${IMAGE:-flashnext-vllm:blazux-ad8920d-tcnone}
MODELS_DIR=${MODELS_DIR:-/models}
NAME=${NAME:-flashnext}

docker run -d --name "$NAME" --gpus all --ipc=host --shm-size 16g -p 8000:8000 -v "$MODELS_DIR":/modelli:ro -e VLLM_PLE_MMAP=1 -e VLLM_PLE_MMAP_WORKERS=32 -e VLLM_PLE_MMAP_PREWARM=0 -e VLLM_PLE_MMAP_MADVISE=random -e VLLM_QSA_EXACT_TOPK=0 -e VLLM_QSA_DET_TOPK=1 -e VLLM_QSA_DET_LIB=/opt/llm/kernel-det/_C_det.so -e VLLM_FP8_PAD_M4=0 -e VLLM_USE_FLASHINFER_SAMPLER=1 -e VLLM_FP8_HYBRID=1 -e VLLM_USE_DEEP_GEMM=0 \
  "$IMAGE" /modelli/Qwen3.8-Flash-Next-NVFP4-fp8hybrid --served-model-name flashnext --host 0.0.0.0 --port 8000 --load-format safetensors \
    --max-model-len 262144 --max-num-seqs 8 --gpu-memory-utilization 0.85 --enable-prefix-caching --enable-chunked-prefill --max-num-batched-tokens 8192 -cc.cudagraph_mode=PIECEWISE -cc.splitting_ops='["vllm::unified_attention_with_output","vllm::unified_mla_attention_with_output","vllm::mamba_mixer2","vllm::mamba_mixer","vllm::short_conv","vllm::qwen3_8_flash_next_ple_short_conv","vllm::qwen3_8_flash_next_qsa_with_output","vllm::linear_attention","vllm::qwen_gdn_attention_core","vllm::qwen_gdn_attention_core_fused_norm_packed","vllm::sparse_attn_indexer","vllm::ple_mmap_lookup"]' \
    --no-enable-flashinfer-autotune --kv-cache-dtype auto \
    --enable-auto-tool-choice --tool-call-parser qwen3_coder --reasoning-parser qwen3 --default-chat-template-kwargs '{"enable_thinking": false}' --speculative-config '{"method":"mtp","num_speculative_tokens":2}'
