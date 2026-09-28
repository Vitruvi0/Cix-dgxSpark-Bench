#!/usr/bin/env python3
"""Efficienza del tokenizer su corpora reali: token per parola, byte e
caratteri per token, tempo di tokenizzazione. Piu' tokenizer a confronto
(Flash-Next 248k, 27B, Qwen3 151k di riferimento) sugli stessi testi.

Perche': il vocabolario 248k di Qwen3.8 non ha dati pubblici di fertilita';
su italiano e inglese decide quanti token costa un documento RAG (TTFT,
contesto effettivo) e rende confrontabili i tok/s fra modelli con tokenizer
diversi. Gira sul host col python del venv lm-eval (ha `tokenizers`); il
resto e' stdlib.

Uso: tokenizer_eff.py --tok nome=dir [--tok ...] --corpus nome=file [...] [--out csv]
"""

import argparse
import csv
import os
import sys
import time


def metriche(tok, testo):
    t0 = time.perf_counter()
    n = len(tok.encode(testo, add_special_tokens=False).ids)
    dt = time.perf_counter() - t0
    parole = len(testo.split())
    b = len(testo.encode("utf-8"))
    return {
        "token": n,
        "parole": parole,
        "tok_per_parola": round(n / parole, 4) if parole else None,
        "byte_per_token": round(b / n, 4) if n else None,
        "char_per_token": round(len(testo) / n, 4) if n else None,
        "ms": round(dt * 1000, 1),
    }


def main():
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("--tok", action="append", required=True, help="nome=directory con tokenizer.json")
    p.add_argument("--corpus", action="append", required=True, help="nome=file di testo")
    p.add_argument("--max-char", type=int, default=2_000_000, help="taglio per corpus (default 2M caratteri)")
    p.add_argument("--out", default="tokenizer-eff.csv")
    args = p.parse_args()
    from tokenizers import Tokenizer

    toks = {}
    for spec in args.tok:
        nome, d = spec.split("=", 1)
        toks[nome] = Tokenizer.from_file(os.path.join(d, "tokenizer.json"))
        print(f"{nome}: vocab {toks[nome].get_vocab_size()}")
    righe = []
    for spec in args.corpus:
        nome, path = spec.split("=", 1)
        testo = open(path, encoding="utf-8", errors="replace").read()[: args.max_char]
        for tnome, tok in toks.items():
            m = metriche(tok, testo)
            righe.append({"corpus": nome, "tokenizer": tnome, "char": len(testo), **m})
            print(f"{nome:12s} {tnome:12s} tok/parola {m['tok_per_parola']:.3f}  byte/token {m['byte_per_token']:.2f}  ({m['ms']} ms)")
    with open(args.out, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(righe[0].keys()))
        w.writeheader()
        w.writerows(righe)
    return 0


if __name__ == "__main__":
    sys.exit(main())
