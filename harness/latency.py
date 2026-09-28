#!/usr/bin/env python3
"""Client a batch 1 per TTFT, decode e inter-token latency.

Griglia del protocollo: temperature 0, N token di
decode, classi di prompt per lunghezza (default corto ~100 e lungo 8000 token,
calibrate via /tokenize), warm-up + >=5 run per classe, mediana e IQR a valle.
Ogni run ha una testa di prompt unica: i runtime hanno il prefix caching
attivo di default e prompt identici falserebbero TTFT e prefill dal secondo
run in poi. Corpo del prompt: una frase ripetuta (default) oppure fette
diverse di un corpus reale (--corpus): il prompt-lookup n-gram trova
ripetizioni a ogni passo sul testo sintetico, e il suo guadagno va misurato
anche su testo variato.

Misure per richiesta:
- TTFT = invio -> primo chunk con contenuto (percorso HTTP completo);
- prefill tok/s = prompt_tokens / TTFT (per eccesso: include tokenizzazione
  e scheduling);
- decode tok/s = (completion_tokens - 1) / (ultimo chunk - primo chunk);
- inter-token latency: media per token = 1000 / decode tok/s; p50 e p95 dei
  gap fra chunk consecutivi. Con lo speculative decoding un chunk porta piu'
  token accettati insieme: i percentili sono per chunk (n_chunk lo dichiara),
  la media resta per token.

Solo stdlib. Il parse SSE e' quello dell'harness di concorrenza (stessi
casi limite); i chunk si timbrano all'arrivo e si parsano dopo lo stream.
"""

import argparse
import csv
import json
import os
import statistics
import sys
import time
import urllib.request

from concurrency import delta_del_chunk, kwargs_da_argomento, parametri_richiesta, payload_chat, salva_output

FRASE = (
    "Le piccole e medie imprese italiane gestiscono ordini, fatture, "
    "preventivi e contratti con fornitori e clienti su mercati regionali. "
)
DOMANDA = "\nRiassumi il testo precedente in una frase."
CHAR_PER_TOKEN = 6  # sovrastima per il testo reale: la ricerca binaria taglia a misura


def piano_prompts(prompts, warmup, minimo_run=5):
    """--prompts: i primi `warmup` scaldano, gli altri sono le run misurate.
    Protocollo: almeno 5 run, altrimenti la mediana+IQR non vale."""
    if len(prompts) - warmup < minimo_run:
        raise ValueError(f"{len(prompts)} prompt con {warmup} di warm-up: meno di {minimo_run} run misurate")
    return [(p, i < warmup) for i, p in enumerate(prompts)]


def fetta_corpus(testo, inizio, passo, slot, caratteri):
    """Finestra `slot`-esima del corpus: fette diverse e non sovrapposte per run."""
    da = inizio + slot * passo
    fetta = testo[da : da + caratteri]
    if len(fetta) < caratteri:
        raise ValueError(f"corpus troppo corto per lo slot {slot} ({len(testo)} caratteri)")
    return fetta


def misura_latenza(eventi, t_invio):
    """Dai chunk (timestamp, riga SSE) alla riga di misura."""
    tempi = []
    usage = None
    finish = None
    testo, ragionamento = [], []
    for t, line in eventi:
        delta, u = delta_del_chunk(line)
        if u:
            usage = u
        if not delta:
            continue
        if delta["finish_reason"]:
            finish = delta["finish_reason"]
        if delta["content"] or delta["reasoning"]:
            tempi.append(t)
            testo.append(delta["content"])
            ragionamento.append(delta["reasoning"])
    if not tempi:
        raise ValueError("nessun chunk con contenuto ricevuto (completion vuota?)")
    ttft = tempi[0] - t_invio
    n_out = usage["completion_tokens"]
    finestra = tempi[-1] - tempi[0]
    totale = tempi[-1] - t_invio
    gap_ms = [(b - a) * 1000 for a, b in zip(tempi, tempi[1:])]
    decode = (n_out - 1) / finestra if n_out > 1 and finestra > 0 else 0.0
    riga = {
        "prompt_tokens": usage["prompt_tokens"],
        "completion_tokens": n_out,
        "ttft_ms": round(ttft * 1000, 1),
        "prefill_tok_s": round(usage["prompt_tokens"] / ttft, 1),
        "decode_tok_s": round(decode, 2),
        # completion / tempo totale, TTFT incluso: e' la metrica dello
        # sgbench di azampatti, l'unica su cui i suoi numeri si confrontano.
        "tok_s_wall": round(n_out / totale, 2) if totale > 0 else 0.0,
        "itl_ms_media": round(1000 / decode, 1) if decode else None,
        "itl_ms_p50": None,
        "itl_ms_p95": None,
        "n_chunk": len(tempi),
        "finish_reason": finish,
        "testo": "".join(testo),
        "ragionamento": "".join(ragionamento),
    }
    if gap_ms:
        riga["itl_ms_p50"] = round(statistics.median(gap_ms), 1)
        # p95 = valore al 95% dei gap ordinati (senza interpolazione: ha
        # senso anche con pochi chunk, e non inventa un valore fra due misure)
        ordinati = sorted(gap_ms)
        riga["itl_ms_p95"] = round(ordinati[min(len(ordinati) - 1, int(0.95 * len(ordinati)))], 1)
    return riga


class ContatoreLocale:
    """Conta i token col tokenizer HF del checkpoint (tokenizers.Tokenizer):
    fallback per gli engine senza /tokenize. Va lanciato con un python che
    ha `tokenizers` (sullo Spark: il venv di lm-eval), il resto e' stdlib."""

    def __init__(self, tok):
        self.tok = tok

    @classmethod
    def da_directory(cls, directory):
        from tokenizers import Tokenizer  # import pigro: solo se richiesto
        return cls(Tokenizer.from_file(os.path.join(directory, "tokenizer.json")))

    def __call__(self, testo):
        return len(self.tok.encode(testo, add_special_tokens=False).ids)


class Client:
    def __init__(self, args):
        self.args = args
        self.corpus = open(args.corpus, encoding="utf-8").read() if args.corpus else None
        self.contatore = (ContatoreLocale.da_directory(args.tokenizer_locale)
                          if args.tokenizer_locale else None)

    def post(self, path, payload):
        req = urllib.request.Request(
            self.args.url + path, data=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json"})
        return urllib.request.urlopen(req, timeout=self.args.timeout)

    def count_tokens(self, testo):
        if self.contatore:
            return self.contatore(testo)
        with self.post("/tokenize", {"model": self.args.model, "prompt": testo}) as r:
            return json.load(r)["count"]

    def prompt_di(self, target, seed, slot):
        """Prompt ~target token: testa unica + corpo (sintetico o fetta reale)."""
        testa = f"Sessione {seed:04d}. "
        if self.corpus:
            corpo = fetta_corpus(self.corpus, self.args.corpus_inizio, self.args.corpus_passo,
                                 slot, target * CHAR_PER_TOKEN)
        else:
            corpo = FRASE * (target // 8)  # sovrastima: ~30 token a frase
        parole = (testa + corpo).split(" ")
        lo, hi = 1, len(parole)
        while lo < hi:  # ricerca binaria sul numero di parole
            mid = (lo + hi) // 2
            if self.count_tokens(" ".join(parole[:mid])) < target:
                lo = mid + 1
            else:
                hi = mid
        return " ".join(parole[:lo]) + "\n" + self.args.domanda

    def una_run(self, prompt):
        payload = payload_chat(self.args.model, prompt, self.args.max_tokens,
                               self.args.chat_template_kwargs)
        eventi = []
        t_invio = time.monotonic()
        with self.post("/v1/chat/completions", payload) as r:
            for raw in r:
                eventi.append((time.monotonic(), raw.decode()))
        riga = misura_latenza(eventi, t_invio)
        riga["richiesta"] = parametri_richiesta(payload)
        return riga


def mediana_iqr(valori):
    q = statistics.quantiles(valori, n=4)
    return statistics.median(valori), q[0], q[2]


def main():
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("--url", default="http://localhost:8000")
    p.add_argument("--model", default=os.environ.get("BENCH_MODEL", "/modelli/Qwen3.8-27B-NVFP4"))
    p.add_argument("--out", default="latency.csv")
    p.add_argument("--classi", default="corto=100,lungo8k=8000",
                   help="classi di prompt nome=token target, separate da virgola")
    p.add_argument("--run", type=int, default=6, help="run misurati per classe (protocollo: >=5)")
    p.add_argument("--warmup", type=int, default=2)
    p.add_argument("--max-tokens", type=int, default=256)
    p.add_argument("--timeout", type=float, default=600)
    p.add_argument("--corpus", help="file di testo reale: fette diverse per run al posto della frase ripetuta")
    p.add_argument("--prompts", help="file con un prompt per riga (classe 'sme': prompt PMI reali, niente corpus ne' domanda); i primi --warmup scaldano, gli altri misurano")
    p.add_argument("--corpus-inizio", type=int, default=20_000, help="offset in caratteri della prima fetta")
    p.add_argument("--corpus-passo", type=int, default=60_000, help="distanza in caratteri fra le fette")
    p.add_argument("--chat-template-kwargs", default=None,
                   help='JSON passato come chat_template_kwargs, es. {"enable_thinking": false}')
    p.add_argument("--salva-output", default=None,
                   help="file JSONL (append) col testo generato per run, per validity.py")
    p.add_argument("--domanda", default=DOMANDA.strip(),
                   help="richiesta appesa al corpo del prompt (default: riassunto in una frase)")
    p.add_argument("--tokenizer-locale", default=None,
                   help="directory del checkpoint: calibra le classi col tokenizer HF invece di /tokenize")
    args = p.parse_args()
    args.chat_template_kwargs = kwargs_da_argomento(args.chat_template_kwargs)
    classi = {k: int(v) for k, v in (c.split("=") for c in args.classi.split(","))}

    client = Client(args)
    righe = []
    if args.prompts:
        prompts = [l.rstrip("\n") for l in open(args.prompts, encoding="utf-8") if l.strip()]
        classi = {"sme": None}
        n = 0
        for prompt, scalda in piano_prompts(prompts, args.warmup):
            r = client.una_run(prompt)
            if scalda:
                print("[sme] warm-up", flush=True)
                continue
            n += 1
            r.update(classe="sme", run=n, timestamp=time.strftime("%Y-%m-%dT%H:%M:%S%z"))
            righe.append(r)
            print(f"[sme] run {n}: {r}", flush=True)
    for classe, target in (classi.items() if not args.prompts else []):
        for i in range(args.warmup):
            client.una_run(client.prompt_di(target, seed=9000 + i, slot=i))
            print(f"[{classe}] warm-up {i + 1}/{args.warmup}", flush=True)
        for i in range(args.run):
            r = client.una_run(client.prompt_di(target, seed=i, slot=args.warmup + i))
            r.update(classe=classe, run=i + 1, timestamp=time.strftime("%Y-%m-%dT%H:%M:%S%z"))
            righe.append(r)
            print(f"[{classe}] run {i + 1}/{args.run}: {r}", flush=True)

    # Testi e parametri vanno nel JSONL: il CSV conserva lo schema delle
    # misure per restare compatibile con le griglie e le tabelle esistenti.
    if args.salva_output:
        salva_output(args.salva_output, righe, {"modello": args.model, "out": args.out})
    campi = [k for k in righe[0] if k not in ("testo", "ragionamento", "richiesta")]
    with open(args.out, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=campi, extrasaction="ignore")
        w.writeheader()
        w.writerows(righe)

    print("\n== mediana (Q1-Q3) per classe ==")
    for classe in classi:
        gruppo = [r for r in righe if r["classe"] == classe]
        for m in ("ttft_ms", "prefill_tok_s", "decode_tok_s", "itl_ms_media", "itl_ms_p50", "itl_ms_p95"):
            valori = [r[m] for r in gruppo if r[m] is not None]
            if len(valori) < 2:
                continue
            med, q1, q3 = mediana_iqr(valori)
            print(f"{classe:8s} {m:15s} {med:10.1f}  ({q1:.1f}-{q3:.1f})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
