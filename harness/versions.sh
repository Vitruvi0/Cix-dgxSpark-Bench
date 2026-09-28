#!/bin/bash
# Genera (o aggiorna) versions.txt di una run dir: senza versioning totale il
# numero non viene registrato. Non calcola hash dei pesi
# (126 GiB letti inquinerebbero la page cache prima del load): registra
# config.json, l'indice safetensors e la lista degli shard con dimensioni.
#
# Uso: versions.sh <run-dir> <modello-dir> [immagine-docker...] 
#   TERZE=$HOME/third-party (pinned clones, optional)
#   HASHK=/models/hashk/ple_hashk_R4.pt (optional)
set -u
DIR=${1:?run dir}; MODELLO=${2:?modello dir}; shift 2
OUT="$DIR/versions.txt"
TERZE=${TERZE:-$HOME/third-party}
# Root of this repo, located from the script itself: the commit recorded
# is the one of the measurement code that actually runs.
RADICE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
{
  echo "=== generato: $(date -Is) da $(basename "$0")"
  uname -a
  grep PRETTY_NAME /etc/os-release
  nvidia-smi --query-gpu=name,driver_version --format=csv,noheader 2>/dev/null
  free -g | head -2
  for img in "$@"; do
    echo "immagine: $img -> $(sg docker -c "docker inspect --format '{{index .RepoDigests 0}}' $img" 2>/dev/null || echo 'non presente')"
  done
  echo "modello: $MODELLO"
  (cd "$MODELLO" && sha256sum config.json model.safetensors.index.json 2>/dev/null; ls -l ./*.safetensors | awk '{s+=$5; n++} END {print n " shard, " s " byte"}')
  if [ -d "$TERZE" ]; then
    for r in "$TERZE"/*/; do
      [ -d "$r/.git" ] && echo "terze: $(basename "$r") $(git -C "$r" rev-parse HEAD) $(git -C "$r" remote get-url origin 2>/dev/null)"
    done
    [ -d "$TERZE/patches" ] && (cd "$TERZE/patches" && sha256sum ./* 2>/dev/null | sed 's/^/patch: /')
  fi
  [ -n "${HASHK:-}" ] && [ -f "$HASHK" ] && echo "hashk: $(sha256sum "$HASHK") $(stat -c %s "$HASHK") byte"
  echo "harness repo: $(git -C "$RADICE" rev-parse HEAD) branch $(git -C "$RADICE" branch --show-current)"
  (cd "$DIR" && sha256sum ./*.sh ./*.py 2>/dev/null | sed 's/^/driver: /')
  (cd "$(dirname "$0")" && sha256sum latency.py concurrency.py validity.py | sed 's/^/harness: /')
} >> "$OUT"   # append: una catena puo' rigenerarlo piu' volte, e le righe aggiunte a mano (sha256 HashK) non vanno perse
echo "aggiornato $OUT"
