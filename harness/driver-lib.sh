#!/bin/bash
# Funzioni comuni ai driver non presidiati dei benchmark Flash-Next (SGLang e
# vLLM): stato, attesa del server, memoria, monitor, griglia e validita'.
# Si usa con `source`. Convenzioni: docker via `sg docker -c`,
# container -d, marker stato-driver.txt, un fallimento ferma la catena.
# DRY=1 stampa i comandi senza eseguire nulla (verifica in locale, senza GPU).
set -u
# Percorso di se stesso: HARNESS si autolocalizza invece di assumere una
# radice fissa.
HARNESS="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PYVENV=${PYVENV:-python3}   # needs `tokenizers` for --tokenizer-locale (local calibration)
MODELLO_DIR=${MODELLO_DIR:-/models/Qwen3.8-Flash-Next-NVFP4}   # override dall'ambiente per altri modelli (27B)
CORPUS_IT=${CORPUS_IT:-corpora/promessi_sposi.txt}
# The code class was measured on a proprietary source tree that is not
# published: point CORPUS_CODE at any source-code text of ~400 KB.
CORPUS_CODE=${CORPUS_CODE:-corpora/code.txt}
DRY=${DRY:-0}
PORTA=${PORTA:-8000}
URL="http://localhost:$PORTA"
KW_OFF='{"enable_thinking": false}'
KW_MEDIUM='{"enable_thinking": true, "reasoning_effort": "medium"}'

stato() { [ "$DRY" = 1 ] || echo "$* $(date +%T)" >> stato-driver.txt; echo "$*" >&2; }
fallito() { stato "FALLITO: $*"; [ "$DRY" = 1 ] || exit 1; }

# Il comando docker va in un file per fase: niente doppio parsing delle
# virgolette dentro `sg docker -c` e resta la riga esatta con cui il
# server e' partito.
lancia_server() { # fase file-comando
  local fase=$1 file=$2
  stato "avvio $fase"
  # in DRY il comando va su stderr: stdout e' catturato dal chiamante come id
  if [ "$DRY" = 1 ]; then echo "[DRY] $(cat "$file")" >&2; echo "dry-$fase"; return 0; fi
  sg docker -c "bash $file" 2> "lancio-$fase.err" || return 1
}

attendi() { # id-container [secondi max, default 1500]
  local id=$1 max=${2:-1500} i
  [ "$DRY" = 1 ] && return 0
  for ((i = 0; i < max; i += 5)); do
    curl -sf -m 3 "$URL/health" > /dev/null 2>&1 && return 0
    sg docker -c "docker ps -q --no-trunc" | grep -q "$id" || return 1
    sleep 5
  done
  return 1
}

ferma_server() { # id fase
  local id=$1 fase=$2
  [ "$DRY" = 1 ] && return 0
  sg docker -c "docker logs $id 2>&1" > "server-$fase.log"
  sg docker -c "docker stop $id" > /dev/null 2>&1
  # niente --rm nei lancio: un container morto al boot lascia il log (14:20,
  # ngram5: errore-*.log vuoto perche' il container si era gia' cancellato)
  sg docker -c "docker rm $id" > /dev/null 2>&1
  sleep 10
}

# Regola GB10: NV_ERR_NO_MEMORY con page cache piena. Il load di Flash-Next
# lascia ~100 GiB in cache: prima di ogni server si prova il drop (sudo
# senza password se il sudoers lo consente), altrimenti si attende che
# l'utente lo faccia (`! sync && sudo sysctl vm.drop_caches=3`) e tocchi il
# semaforo via-<fase>. Sotto i 10 GiB di cache si procede.
prepara_memoria() { # fase
  local fase=$1 cache_gib
  [ "$DRY" = 1 ] && { echo "[DRY] prepara_memoria $fase"; return 0; }
  sync
  cache_gib=$(awk '/^Cached:/{printf "%d", $2/1048576}' /proc/meminfo)
  [ "$cache_gib" -lt 10 ] && return 0
  if sudo -n /usr/sbin/sysctl vm.drop_caches=3 > /dev/null 2>&1; then
    stato "drop_caches eseguito ($cache_gib GiB in cache) prima di $fase"; return 0
  fi
  stato "ATTESA drop_caches ($cache_gib GiB in cache): lanciare '! sync && sudo sysctl vm.drop_caches=3' e poi 'touch via-$fase'"
  # esce anche da sola quando la cache scende sotto la soglia (drop fatto dall'operatore
  # da un altro terminale, o cache evaporata): il semaforo via-<fase> resta come alternativa
  until [ -f "via-$fase" ] || [ "$(awk '/^Cached:/{printf "%d", $2/1048576}' /proc/meminfo)" -lt 10 ]; do sleep 30; done
  rm -f "via-$fase"
}

monitor_avvia() { # fase
  [ "$DRY" = 1 ] && return 0
  python3 "$HARNESS/monitor_mem.py" --out "mem-$1.csv" --intervallo 2 &
  MONITOR_PID=$!
}
monitor_ferma() { [ -n "${MONITOR_PID:-}" ] && kill "$MONITOR_PID" 2>/dev/null; MONITOR_PID=""; }

# Griglia unificata: classi corto/8k su testo reale + classe
# code, una colonna per modalita' di thinking; JSONL dei testi per validity.py.
# Prompt corpus/code con testa unica per run: prefix cache fredda.
# PROMPTS_SME=<file>: terza chiamata sulla classe `sme` (prompt PMI, uno
# per riga; i primi 2 scaldano): il moltiplicatore speculativo "su testo
# italiano" misurato su domande, non su fette di corpus.
# Solo la classe sme, per i driver che la vogliono fuori dalla finestra del
# monitor della griglia (controlli headless: il picco si confronta con un
# riferimento che non aveva sme).
griglia_sme() { # fase modello "colonne (off medium)"
  local fase=$1 modello=$2 colonne=$3 col kw base
  for col in $colonne; do
    case $col in off) kw=$KW_OFF ;; medium) kw=$KW_MEDIUM ;; *) fallito "colonna $col sconosciuta" ;; esac
    base="$PYVENV $HARNESS/latency.py --url $URL --model $modello --run 6 --warmup 2 --max-tokens 256 --tokenizer-locale $MODELLO_DIR --salva-output $fase-$col-sme.jsonl"
    stato "griglia $fase/$col sme"
    if [ "$DRY" = 1 ]; then echo "[DRY] $base --prompts $PROMPTS_SME --out $fase-$col-sme.csv"; continue; fi
    $base --prompts "$PROMPTS_SME" --chat-template-kwargs "$kw" \
      --out "$fase-$col-sme.csv" > "$fase-$col-sme.log" 2>&1 || fallito "griglia $fase/$col (sme)"
  done
}

griglia() { # fase modello "colonne (off medium)"
  local fase=$1 modello=$2 colonne=$3 col kw base
  for col in $colonne; do
    case $col in off) kw=$KW_OFF ;; medium) kw=$KW_MEDIUM ;; *) fallito "colonna $col sconosciuta" ;; esac
    base="$PYVENV $HARNESS/latency.py --url $URL --model $modello --run 6 --warmup 2 --max-tokens 256 --tokenizer-locale $MODELLO_DIR --salva-output $fase-$col.jsonl"
    stato "griglia $fase/$col"
    if [ "$DRY" = 1 ]; then echo "[DRY] $base --classi corto=100,lungo8k=8000 --corpus $CORPUS_IT --chat-template-kwargs '$kw' --out $fase-$col-it.csv"; echo "[DRY] $base --classi code=1500 --corpus $CORPUS_CODE --corpus-inizio 0 --corpus-passo 15000 --domanda '...' --out $fase-$col-code.csv"; [ -n "${PROMPTS_SME:-}" ] && echo "[DRY] $base --prompts $PROMPTS_SME --out $fase-$col-sme.csv"; continue; fi
    $base --classi corto=100,lungo8k=8000 --corpus "$CORPUS_IT" --chat-template-kwargs "$kw" \
      --out "$fase-$col-it.csv" > "$fase-$col-it.log" 2>&1 || fallito "griglia $fase/$col (it)"
    $base --classi code=1500 --corpus $CORPUS_CODE --corpus-inizio 0 --corpus-passo 15000 \
      --domanda "Scrivi il test unitario mancante per il codice precedente (vitest, TypeScript)." \
      --chat-template-kwargs "$kw" --out "$fase-$col-code.csv" > "$fase-$col-code.log" 2>&1 || fallito "griglia $fase/$col (code)"
    [ -z "${PROMPTS_SME:-}" ] || $base --prompts "$PROMPTS_SME" --chat-template-kwargs "$kw" \
      --out "$fase-$col-sme.csv" > "$fase-$col-sme.log" 2>&1 || fallito "griglia $fase/$col (sme)"
    # validita' rossa marca la fase, non ferma la catena: il numero resta,
    # ma entra nel registro come grezzo/raw + corruzione N/M.
    python3 "$HARNESS/validity.py" --output "$fase-$col.jsonl" >> "validita-$fase.log" 2>&1 \
      || stato "VALIDITA' $fase/$col: righe invalide, vedi $fase-$col-validity.csv"
  done
}
