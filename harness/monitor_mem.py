#!/usr/bin/env python3
"""Monitor di memoria per fase di benchmark: RAM usata, page cache, swap e
contatori di swap-in/out e major fault, in CSV ogni N secondi.

Perche': con un modello "al limite" dei 121 GiB (Flash-Next) il picco RAM e
lo swap durante il decode sono metriche di testata; e con la tabella PLE
servita via mmap i major fault per token sono la misura diretta del costo
dello streaming da NVMe. Con --pid si campionano anche minflt/majflt del
processo server. Anche la temperatura GPU (throttling termico durante le
griglie); la colonna c'e' sempre, vuota se nvidia-smi manca o non risponde.
Anche i settori letti e scritti del disco intero (/proc/diskstats): le
letture vanno attribuite per fase, e la delta fra primo e ultimo campione
della fase e' la misura diretta; colonne sempre
presenti, vuote se non c'e' un disco nvme/sd. Solo stdlib; lo avvia e lo
ferma il driver.
"""

import argparse
import re
import subprocess
import sys
import time


def _kb(testo, chiave):
    for riga in testo.splitlines():
        if riga.startswith(chiave + ":"):
            return int(riga.split()[1])
    return 0


def _vm(testo, chiave):
    for riga in testo.splitlines():
        if riga.startswith(chiave + " "):
            return int(riga.split()[1])
    return 0


def leggi_gpu_temp():
    try:
        return subprocess.run(["nvidia-smi", "--query-gpu=temperature.gpu", "--format=csv,noheader"],
                              capture_output=True, text=True, timeout=5).stdout
    except (OSError, subprocess.SubprocessError):
        return None


def _settori(diskstats):
    # Disco intero (nvme0n1, sda), non le partizioni: i cumulativi sono quelli che SMART
    # riassume. Campi 3 e 7 dopo il nome = settori letti / scritti (512 byte l'uno).
    # Il primo nvme vince su un eventuale sd (chiavetta, disco USB): l'ordine in
    # /proc/diskstats dipende dall'enumerazione, non dal ruolo del disco.
    dischi = {}
    for riga in (diskstats or "").splitlines():
        campi = riga.split()
        if len(campi) >= 10 and re.fullmatch(r"nvme\d+n\d+|sd[a-z]+", campi[2]):
            dischi.setdefault(campi[2][:2], (int(campi[5]), int(campi[9])))
    return dischi.get("nv") or dischi.get("sd") or ("", "")


def campione(meminfo, vmstat, stat_pid=None, gpu_temp=None, diskstats=None):
    c = {
        "usata_gib": round((_kb(meminfo, "MemTotal") - _kb(meminfo, "MemAvailable")) / 2**20, 2),
        "cache_gib": round(_kb(meminfo, "Cached") / 2**20, 2),
        "swap_usato_gib": round((_kb(meminfo, "SwapTotal") - _kb(meminfo, "SwapFree")) / 2**20, 2),
        "pswpin": _vm(vmstat, "pswpin"),
        "pswpout": _vm(vmstat, "pswpout"),
        "pgmajfault": _vm(vmstat, "pgmajfault"),
    }
    c["sectors_read"], c["sectors_written"] = _settori(diskstats)
    if stat_pid:
        # /proc/<pid>/stat: campo 10 = minflt, 12 = majflt (dopo la parentesi del comm)
        campi = stat_pid.rsplit(")", 1)[1].split()
        c["pid_minflt"], c["pid_majflt"] = int(campi[7]), int(campi[9])
    try:
        c["gpu_temp_c"] = int((gpu_temp or "").strip())
    except ValueError:
        c["gpu_temp_c"] = ""
    return c


def main():
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("--out", required=True)
    p.add_argument("--intervallo", type=float, default=2.0)
    p.add_argument("--pid", type=int, default=None)
    args = p.parse_args()
    with open(args.out, "w") as f:
        intestazione = None
        while True:
            stat = open(f"/proc/{args.pid}/stat").read() if args.pid else None
            c = campione(open("/proc/meminfo").read(), open("/proc/vmstat").read(), stat, leggi_gpu_temp(),
                         open("/proc/diskstats").read())
            c = {"t": time.strftime("%H:%M:%S"), **c}
            if intestazione is None:
                intestazione = list(c)
                f.write(",".join(intestazione) + "\n")
            f.write(",".join(str(c[k]) for k in intestazione) + "\n")
            f.flush()
            time.sleep(args.intervallo)


if __name__ == "__main__":
    sys.exit(main())
