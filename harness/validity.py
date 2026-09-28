#!/usr/bin/env python3
"""Controllo di validita' dell'output generato (Flash-Next su GB10).

Perche': su sm_121 i kernel non patchati producono NaN che diventano token 0
("!!!!"), e uno stream corrotto accetta ogni draft speculativo, gonfiando i
tok/s di 2-3x (flashnext-one-spark, EXPERIMENTS_2026-08-27). Un numero di
throughput senza controllo dell'output non entra nel registro. Qui i
controlli sono euristici e dichiarati: un run "invalido" va indagato, non
scartato in silenzio.

Uso: validity.py --output run.jsonl [--out run-validity.csv]
Exit 1 se almeno una riga ha un problema (il driver marca la fase, non si ferma).
"""

import argparse
import csv
import json
import re
import statistics
import sys
import unicodedata

SOGLIA_NAN = 16          # "!" consecutivi: firma NaN -> token 0
SOGLIA_NGRAM_UNICI = 0.3  # 4-gram unici / totali sotto cui e' ripetizione
FATTORE_DECODE = 2.5      # tok/s oltre questo multiplo della mediana = sospetto


def testo_degenerato(testo):
    """Segnali di corruzione nella prosa attesa in italiano/inglese.

    Non misura correttezza o senso del testo. NaN e bassa varieta' restano
    coperti da nan_token0 e ripetizione in controlla_riga.
    """
    # Escludi anche un blocco non chiuso: con finish_reason=length il codice
    # puo' essere troncato. Lo spazio evita di unire parole ai lati del blocco.
    prosa = re.sub(r"```.*?(?:```|\Z)", " ", testo, flags=re.DOTALL)
    problemi = []
    alfabetici = [c for c in prosa if c.isalpha()]
    non_latini = sum("LATIN" not in unicodedata.name(c, "") for c in alfabetici)
    # 1,5% e' la soglia piu' prudente tra 1/1,25/1,5%, tutte senza falsi
    # positivi sulle 1194 righe: coglie il caso 59 (8/516) gia' sospetto.
    # Senza altri segnali resta il 2% per tollerare nomi/citazioni stranieri;
    # il minimo di 8 evita percentuali enormi su risposte molto corte.
    # Il segnale non vale dentro il codice inline (`!important!`, `</think>` citato):
    # li' e' una citazione, non corruzione.
    soglia_script = 0.015 if re.search(r"!\w+!|</think>", re.sub(r"`[^`\n]*`", " ", prosa)) else 0.02
    if non_latini >= 8 and non_latini > soglia_script * len(alfabetici):
        problemi.append("degenerato_script")

    # Almeno 3 gruppi sospetti: una singola enfasi (!!) e' lecita. Per punti,
    # virgole, due punti e punto e virgola ne servono 4 consecutivi (non "...").
    # Non contare **, ###, --- o ||: ricorrono nel Markdown e nelle tabelle.
    punteggiatura = re.findall(r"[!?]{2,}|!\w+!|([.,:;])\1{3,}", prosa)
    if len(punteggiatura) >= 3:
        problemi.append("degenerato_punteggiatura")

    parole = prosa.split()
    brevi = sum(bool(re.fullmatch(r"[a-zA-Z]{1,2}", p)) for p in parole)
    # Almeno 40 token per stabilizzare la quota; >40% (non 30%: 9 falsi
    # positivi nella campagna SGLang, massimo 34.6%, per articoli/preposizioni).
    # I token devono essere lettere isolate: sigle numeriche come B1 non bastano.
    if len(parole) >= 40 and brevi > 0.40 * len(parole):
        problemi.append("degenerato_lettere")
    return problemi


def controlla_riga(r):
    problemi = []
    testo = (r.get("testo") or "") + (r.get("ragionamento") or "")
    if re.search(r"!{%d,}" % SOGLIA_NAN, testo):
        problemi.append("nan_token0")
    parole = testo.split()
    if len(parole) >= 12:
        ngram = [" ".join(parole[i:i + 4]) for i in range(len(parole) - 3)]
        if len(set(ngram)) / len(ngram) < SOGLIA_NGRAM_UNICI:
            problemi.append("ripetizione")
    if "</think>" in (r.get("testo") or ""):
        problemi.append("think_in_content")
    n = r.get("completion_tokens")
    if r.get("finish_reason") == "length" and n is not None and n < 8:
        problemi.append("troncata_corta")
    # Valuta separatamente i campi: codice aperto o prosa sana in uno non
    # devono nascondere corruzione nell'altro. Ogni etichetta compare una volta.
    for campo in ("testo", "ragionamento"):
        for problema in testo_degenerato(r.get(campo) or ""):
            if problema not in problemi:
                problemi.append(problema)
    return problemi


def controlla_tutte(righe):
    """Controlli per riga piu' quello relativo: decode tok/s anomalo rispetto
    alla mediana del gruppo (stessa classe/livello nel run)."""
    esiti = [controlla_riga(r) for r in righe]
    velocita = [r.get("decode_tok_s") or r.get("tok_s") for r in righe]
    validi = [v for v in velocita if v]
    if len(validi) >= 3:
        mediana = statistics.median(validi)
        for i, v in enumerate(velocita):
            if v and v > FATTORE_DECODE * mediana:
                esiti[i].append("decode_anomalo")
    return esiti


def main():
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("--output", required=True, help="JSONL scritto da latency.py/concurrency.py --salva-output")
    p.add_argument("--out", default=None, help="CSV con l'esito per riga (default: <output>-validity.csv)")
    args = p.parse_args()
    with open(args.output, encoding="utf-8") as f:
        righe = [json.loads(l) for l in f if l.strip()]
    if not righe:
        sys.exit("nessuna riga in " + args.output)
    # gruppi omogenei: la mediana del decode ha senso solo dentro una classe/livello
    chiave = lambda r: (r.get("classe"), r.get("livello"))
    esiti = [None] * len(righe)
    for k in {chiave(r) for r in righe}:
        idx = [i for i, r in enumerate(righe) if chiave(r) == k]
        for i, e in zip(idx, controlla_tutte([righe[i] for i in idx])):
            esiti[i] = e
    out = args.out or args.output.rsplit(".", 1)[0] + "-validity.csv"
    with open(out, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["classe", "livello", "run", "completion_tokens", "finish_reason", "valido", "problemi"])
        for r, e in zip(righe, esiti):
            w.writerow([r.get("classe"), r.get("livello"), r.get("run"), r.get("completion_tokens"),
                        r.get("finish_reason"), "si" if not e else "no", " ".join(e)])
    invalidi = sum(1 for e in esiti if e)
    print(f"{len(righe)} righe, {invalidi} invalide -> {out}")
    sys.exit(1 if invalidi else 0)


if __name__ == "__main__":
    main()
