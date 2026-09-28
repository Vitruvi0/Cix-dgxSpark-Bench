#!/usr/bin/env python3
"""Accettazione dello speculative decoding dai log del server: SGLang stampa
"accept len: X, accept rate: Y" a ogni batch di decode, vLLM
"Mean acceptance length: X". Media, min e max: quanti token accetta ogni
passo va misurato, non dichiarato.

Uso: acceptance.py server-<fase>.log [...]
"""

import re
import statistics
import sys

RE_SGLANG = re.compile(r"accept len: ([0-9.]+), accept rate: ([0-9.]+)")
RE_VLLM = re.compile(r"Mean acceptance length: ([0-9.]+)")


def estrai(testo):
    righe = []
    for line in testo.splitlines():
        m = RE_SGLANG.search(line)
        if m:
            righe.append({"len": float(m.group(1)), "rate": float(m.group(2))})
            continue
        m = RE_VLLM.search(line)
        if m:
            righe.append({"len": float(m.group(1)), "rate": None})
    return righe


def riassumi(righe):
    if not righe:
        return {"n": 0}
    lens = [r["len"] for r in righe]
    rates = [r["rate"] for r in righe if r["rate"] is not None]
    return {"n": len(lens), "len_media": statistics.fmean(lens), "len_min": min(lens), "len_max": max(lens),
            "rate_media": statistics.fmean(rates) if rates else None}


def main():
    for path in sys.argv[1:]:
        r = riassumi(estrai(open(path, errors="replace").read()))
        if r["n"] == 0:
            print(f"{path}: nessuna riga di accettazione (speculative off?)")
            continue
        rate = f", rate media {r['rate_media']:.2f}" if r["rate_media"] is not None else ""
        print(f"{path}: n={r['n']} accept len media {r['len_media']:.2f} (min {r['len_min']:.2f}, max {r['len_max']:.2f}){rate}")


if __name__ == "__main__":
    main()
