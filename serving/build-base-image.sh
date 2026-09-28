#!/bin/bash
# Builds the patched vLLM image from a pinned clone of
# https://github.com/blazux/qwen3.8-Flash-DGX (Apache-2.0) at commit ad8920d.
# The Dockerfile and its patches are blazux's work and are not copied here.
#
# Before building, the script refuses a Dockerfile that is not the one we
# reviewed: the base image must be the pinned digest, and the only network
# access allowed is `ADD --checksum=sha256:` from the jschmied repository
# (deterministic top-k kernel). The build compiles _C_det.so with nvcc and
# takes 10-20 minutes.
#
#   SRC  path of the blazux clone, already checked out at ad8920d
#   DRY=1 runs the checks and stops before the build
set -eu
SRC=${SRC:?path of the qwen3.8-Flash-DGX clone}
EXPECTED=ad8920d
BASE=vllm/vllm-openai:qwen38-flash-next@sha256:fc120ece0a388cc0aa1caad4a9f1cd92113484ab7ec2fd0efadd62585be05bf8

HEAD=$(git -C "$SRC" rev-parse --short HEAD)
[ "$HEAD" = "$EXPECTED" ] || { echo "clone is at $HEAD, not $EXPECTED: review the diff before building"; exit 1; }
TAG=flashnext-vllm:blazux-$HEAD
grep -q "^FROM $BASE" "$SRC/Dockerfile" \
  || { echo "the Dockerfile is not on the reviewed base image (FROM or digest changed)"; exit 1; }
if grep -nE "pip install|curl |wget |git clone|apt" "$SRC/Dockerfile"; then
  echo "the Dockerfile uses the network beyond the pinned ADDs: stop and read it"; exit 1; fi
if grep -nE "^ADD .*https?://" "$SRC/Dockerfile" | grep -vE "^[0-9]+:ADD --checksum=sha256:[0-9a-f]{64} https://raw.githubusercontent.com/jschmied/"; then
  echo "remote ADD without checksum or towards an unexpected host: stop"; exit 1; fi
echo "build $TAG from $SRC ($(date +%T))"
[ "${DRY:-0}" = 1 ] && exit 0
DOCKER_BUILDKIT=1 docker build -t "$TAG" "$SRC" 2>&1 | tee build-base-image.log | tail -5
docker run --rm --entrypoint ls "$TAG" -la /opt/llm/draft_vocab_65536.npy /opt/llm/kernel-det/_C_det.so
echo ">> image: $TAG ($(date +%T))"
