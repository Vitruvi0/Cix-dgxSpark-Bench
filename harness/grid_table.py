#!/usr/bin/env python3
"""Tabella markdown della griglia dai CSV di latency.py: per fase/colonna e
classe, mediana e Q1-Q3 di TTFT, prefill, decode, tok_s_wall, ITL p50, token
generati, piu' il conteggio dei finish_reason: i riassunti si scrivono dai
numeri e non a mano.

Uso: grid_table.py <fase>-<col>-it.csv [<fase>-<col>-code.csv ...]
     (ogni file e' una riga per classe; l'etichetta e' il nome file senza -it/-code.csv)
"""

import csv
import os
import statistics
import sys
from collections import Counter

COLONNE = [("ttft_ms", 0), ("prefill_tok_s", 0), ("decode_tok_s", 1), ("tok_s_wall", 1)]


def quartili(valori):
    """Mediana e Q1-Q3 con il metodo 'inclusive' (stesso di riassunto-f2)."""
    v = sorted(valori)
    q = statistics.quantiles(v, n=4, method="inclusive") if len(v) > 1 else [v[0]] * 3
    return statistics.median(v), q[0], q[2]


def formatta(valori, dec):
    m, q1, q3 = quartili(valori)
    f = f"{{:.{dec}f}}"
    return f"{f.format(m)} ({f.format(q1)}–{f.format(q3)})"


def righe_classe(righe):
    """Raggruppa le righe di un CSV per classe (ordine di apparizione)."""
    classi = {}
    for r in righe:
        classi.setdefault(r["classe"], []).append(r)
    return classi


def riga_markdown(etichetta, classe, righe):
    celle = [f"{etichetta} / {classe}"]
    for col, dec in COLONNE:
        celle.append(formatta([float(r[col]) for r in righe], dec))
    celle.append(f"{statistics.median(float(r['itl_ms_p50']) for r in righe):.1f}")
    tok = [int(r["completion_tokens"]) for r in righe]
    celle.append(str(statistics.median_high(tok)) if min(tok) == max(tok) else formatta(tok, 0))
    finish = Counter(r["finish_reason"] for r in righe)
    celle.append(", ".join(f"{n} {k}" for k, n in sorted(finish.items())))
    return "| " + " | ".join(celle) + " |"


def etichetta_file(percorso):
    nome = os.path.basename(percorso)
    for suffisso in ("-it.csv", "-code.csv", "-sme.csv", ".csv"):
        if nome.endswith(suffisso):
            return nome[: -len(suffisso)]
    return nome


def main(percorsi):
    print("| Fase / classe | TTFT ms | prefill tok/s | **decode tok/s** | tok_s_wall | ITL p50 ms | token generati | finish |")
    print("|---|---|---|---|---|---|---|---|")
    for p in percorsi:
        with open(p, newline="", encoding="utf-8") as f:
            righe = [r for r in csv.DictReader(f) if r.get("classe")]
        for classe, rr in righe_classe(righe).items():
            print(riga_markdown(etichetta_file(p), classe, rr))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
