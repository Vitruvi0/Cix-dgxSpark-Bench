#!/bin/bash
# Prepares the "hybrid" checkpoint: the NVFP4 routed experts stay as published,
# the dense side layers (GDN in/out, QSA q/k/v/o, shared expert; ~15 GiB bf16)
# are rewritten as fp8 blockwise 128x128.
#
# Adapted from scripts/prepare-hybrid.sh of blazux/qwen3.8-Flash-DGX to a flat
# models directory instead of the Hugging Face cache. The sister directory
# -fp8hybrid is made of symlinks to the original files; only the 4 converted
# shards and the index, which the converter rewrites, are real files. The
# original checkpoint is not touched.
#
# Runs inside the patched image (torch + safetensors), without GPU, in about
# 10 minutes, and adds 13 GB on disk.
#
#   MODELS_DIR  directory holding Qwen3.8-Flash-Next-NVFP4
#   TOOLS       tools/ directory of the blazux clone (fp8_convert.py)
#   IMAGE       image built by build-base-image.sh
set -euo pipefail
MODELS_DIR=${MODELS_DIR:-/models}
TOOLS=${TOOLS:?tools directory of the qwen3.8-Flash-DGX clone}
IMAGE=${IMAGE:-flashnext-vllm:blazux-ad8920d}
NAME=Qwen3.8-Flash-Next-NVFP4
SRC=$MODELS_DIR/$NAME
DST=$MODELS_DIR/$NAME-fp8hybrid

[ -f "$DST/.prepared" ] && { echo ">> already prepared: $DST"; exit 0; }
rm -rf "$DST"; mkdir "$DST"
for f in "$SRC"/* "$SRC"/.cache; do [ -e "$f" ] && ln -s "../$NAME/$(basename "$f")" "$DST/$(basename "$f")"; done
# The index must be a real file: json.dump opens it for writing and would follow the symlink.
rm "$DST/model.safetensors.index.json"; cp "$SRC/model.safetensors.index.json" "$DST/"
echo ">> $(ls "$DST" | wc -l) entries in $DST; converting ($(date +%T))"
docker run --rm --name fp8convert -v "$MODELS_DIR":/modelli -v "$TOOLS":/tools:ro --entrypoint python3 "$IMAGE" \
  /tools/fp8_convert.py "/modelli/$NAME-fp8hybrid" 2>&1 | tee fp8_convert.log
n=$(python3 -c "import json;print(sum(1 for k in json.load(open('$DST/model.safetensors.index.json'))['weight_map'] if k.endswith('weight_scale_inv')))")
[ "$n" -gt 0 ] || { echo "!! no fp8 tensor produced"; exit 1; }
# The new shards were written by root inside the container.
sudo -n chown "$(id -u):$(id -g)" "$DST"/*.safetensors "$DST"/model.safetensors.index.json 2>/dev/null || true
touch "$DST/.prepared"
echo ">> ready: $n fp8 side-layer tensors ($(date +%T))"
