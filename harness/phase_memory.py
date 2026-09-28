#!/usr/bin/env python3
"""Memoria di sistema per fase dai CSV di monitor_mem.py (campione ogni 2 s):
picco usata, swap min-max, swap-out e major fault nella finestra della
griglia. pswpout > 0 durante il decode va dichiarato ("swap attivo in
decode"); il numero resta valido se l'IQR del decode non ne risente.
Anche GiB letti e scritti su NVMe nella fase; "–" nei CSV senza le colonne.

Uso: phase_memory.py mem-<fase>.csv [...]   -> tabella markdown, una riga per file
"""

import csv
import os
import sys

PAGINA = 4096
SETTORE = 512


def _delta_gib(r, colonna):
    # Un contatore che cala (riavvio, disco ricollegato) rende la delta priva di senso:
    # meglio nessun numero che una sottostima silenziosa.
    valori = [int(x[colonna]) for x in r if x.get(colonna)]
    if not valori or any(b < a for a, b in zip(valori, valori[1:])):
        return None
    return (valori[-1] - valori[0]) * SETTORE / 2**30


def riassumi(righe_csv):
    r = list(csv.DictReader(righe_csv))
    usata = [float(x["usata_gib"]) for x in r]
    swap = [float(x["swap_usato_gib"]) for x in r]
    pswpout = [int(x["pswpout"]) for x in r]
    majf = [int(x["pgmajfault"]) for x in r]
    temp = [int(x["gpu_temp_c"]) for x in r if x.get("gpu_temp_c")]   # colonna dal 04/09, celle vuote senza nvidia-smi
    return {
        "campioni": len(r), "da": r[0]["t"], "a": r[-1]["t"],
        "usata_max_gib": max(usata),
        "swap_min_gib": min(swap), "swap_max_gib": max(swap),
        "pswpout_delta": pswpout[-1] - pswpout[0],
        "pswpout_delta_gib": (pswpout[-1] - pswpout[0]) * PAGINA / 2**30,
        "pgmajfault_delta": majf[-1] - majf[0],
        "gpu_temp_max_c": max(temp) if temp else None,
        "letti_delta_gib": _delta_gib(r, "sectors_read"),
        "scritti_delta_gib": _delta_gib(r, "sectors_written"),
    }


def verdetto_swap(pswpout_delta):
    return "swap attivo in decode" if pswpout_delta > 0 else "nessuno swap-out"


def riga_markdown(fase, r):
    return (f"| {fase} | {r['usata_max_gib']:.1f} | {r['swap_min_gib']:.1f}–{r['swap_max_gib']:.1f} | "
            f"{r['pswpout_delta_gib']:.2f} | {r['pgmajfault_delta']} | {verdetto_swap(r['pswpout_delta'])} | "
            f"{r['gpu_temp_max_c'] if r['gpu_temp_max_c'] is not None else '–'} | "
            f"{_cella(r['letti_delta_gib'])} | {_cella(r['scritti_delta_gib'])} |")


def _cella(gib):
    return "–" if gib is None else f"{gib:.2f}"


def main(percorsi):
    print("| Fase | picco usata GiB | swap GiB | swap-out GiB nella griglia | major fault | swap in decode | T GPU max °C | NVMe letti GiB | NVMe scritti GiB |")
    print("|---|---|---|---|---|---|---|---|---|")
    for p in percorsi:
        fase = os.path.basename(p)
        fase = fase[4:-4] if fase.startswith("mem-") and fase.endswith(".csv") else fase
        with open(p, newline="", encoding="utf-8") as f:
            print(riga_markdown(fase, riassumi(f)))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
