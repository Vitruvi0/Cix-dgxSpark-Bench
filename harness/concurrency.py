#!/usr/bin/env python3
"""Harness di concorrenza: TTFT e throughput con piu' utenti insieme.

Spara N richieste concorrenti a un endpoint OpenAI-compatibile in streaming
e misura per richiesta: TTFT (invio -> primo chunk con contenuto), tok/s di
decode (dal primo all'ultimo chunk), token generati. Solo stdlib: deve girare
sullo Spark senza installare nulla.

Ogni richiesta ha una testa di prompt unica (nonce di run + livello +
indice): i runtime hanno il prefix caching attivo di default e prompt
identici falserebbero TTFT e prefill — dal secondo client in poi e, senza
nonce, anche fra le >=5 ripetizioni del protocollo (run diversi, stessi
byte). Servono inoltre corpi eterogenei fra i client (--prompts): prompt
identici gonfiano il throughput aggregato.

Una richiesta fallita (HTTP, timeout, stream vuoto o malformato) produce una
riga con esito "errore", non un buco: l'aggregato conta i sopravvissuti e
dichiara i caduti, e l'exit code non-zero dice che il run non e' pulito.
"""

import argparse
import csv
import http.client
import json
import os
import statistics
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urlparse

FRASE = (
    "Le piccole e medie imprese italiane gestiscono ordini, fatture, "
    "preventivi e contratti con fornitori e clienti su mercati regionali. "
)

# Identifica il run nel CSV (le ripetizioni del protocollo si aggregano fra
# file) e fa da nonce nella testa dei prompt: ogni run parte a cache fredda.
RUN_ID = os.urandom(4).hex()


def delta_del_chunk(line):
    """Una riga SSE -> (delta, usage), con delta = {content, reasoning,
    finish_reason} oppure None se la riga non porta un delta.

    Lo spazio dopo "data:" e' opzionale nella spec SSE (llama.cpp lo omette).
    Un payload non-JSON o un oggetto {"error": ...} in-band sono un errore
    esplicito: meglio una richiesta marcata fallita che un CSV zoppo e muto.
    Con --reasoning-parser attivo (Qwen3.x) il ragionamento arriva in
    delta.reasoning_content (SGLang) o delta.reasoning (vLLM), non in
    delta.content: e' comunque testo generato e va timbrato, altrimenti TTFT
    e finestra di decode saltano tutta la fase di pensiero (03/09: su vLLM
    la colonna medium dava TTFT 5.6 s e decode 95-194 tok/s su prompt corti,
    e ValueError sugli 8k dove i 256 token sono tutti ragionamento).
    """
    line = line.strip()
    if not line.startswith("data:"):
        return None, None
    payload = line[5:].strip()
    if payload in ("", "[DONE]"):
        return None, None
    try:
        chunk = json.loads(payload)
    except json.JSONDecodeError as e:
        raise ValueError(f"chunk SSE non JSON: {payload[:80]!r}") from e
    if "error" in chunk:
        raise ValueError(f"errore in-band dal server: {chunk['error']}")
    delta = None
    # I default via `or` reggono anche i null espliciti ("delta": null nel
    # chunk finale di alcuni shim OpenAI-compatibili).
    for scelta in chunk.get("choices") or []:
        d = scelta.get("delta") or {}
        # SGLang: delta.reasoning_content; vLLM (parser qwen3): delta.reasoning
        ragionamento = d.get("reasoning_content") or d.get("reasoning") or ""
        if d.get("content") or ragionamento or scelta.get("finish_reason"):
            delta = {"content": d.get("content") or "",
                     "reasoning": ragionamento,
                     "finish_reason": scelta.get("finish_reason")}
    return delta, chunk.get("usage")


def contenuto_del_chunk(line):
    """Una riga SSE -> (testo generato nel delta, usage): None se assenti."""
    delta, usage = delta_del_chunk(line)
    if not delta:
        return None, usage
    testo = delta["content"] or delta["reasoning"]
    return (testo or None), usage


def payload_chat(model, prompt, max_tokens, chat_template_kwargs=None):
    """Corpo della richiesta /v1/chat/completions comune ai due client.

    chat_template_kwargs (es. {"enable_thinking": false}) e' la leva con cui
    si sceglie la colonna thinking off/medium per richiesta, senza riavviare
    il server: e' passata solo se richiesta, cosi' i run senza restano
    byte-identici a prima.
    """
    p = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0,
        "max_tokens": max_tokens,
        "stream": True,
        "stream_options": {"include_usage": True},
    }
    if chat_template_kwargs:
        p["chat_template_kwargs"] = chat_template_kwargs
    return p


def parametri_richiesta(payload):
    # Dal payload effettivo: una lista di parametri nota a priori perderebbe
    # le estensioni future e confonderebbe gli assenti con i default server.
    return {k: v for k, v in payload.items() if k not in ("messages", "prompt")}


def misura(eventi, t_invio, raccogli_testo=False):
    """Dai chunk timbrati all'arrivo -> la riga di misura.

    Il parse avviene qui, DOPO lo stream: dentro il loop di ricezione si
    timbra e basta, cosi' TTFT e finestra di decode non si sporcano col
    tempo di json.loads (che a 24 thread in coda sul GIL cresce proprio
    con la concorrenza, l'asse che si sta misurando).
    """
    t_primo = t_ultimo = None
    usage = None
    n_chunk = 0
    testo, ragionamento, finish = [], [], None
    for t, line in eventi:
        delta, u = delta_del_chunk(line)
        if u:
            usage = u
        if not delta:
            continue
        if delta["finish_reason"]:
            finish = delta["finish_reason"]
        if delta["content"] or delta["reasoning"]:
            t_ultimo = t
            if t_primo is None:
                t_primo = t
            n_chunk += 1
            if raccogli_testo:
                testo.append(delta["content"])
                ragionamento.append(delta["reasoning"])
    if t_primo is None:
        raise ValueError("nessun chunk con contenuto ricevuto (completion vuota?)")
    # usage e' opzionale e puo' essere parziale: senza completion_tokens si
    # ripiega sul conteggio dei chunk, ma dichiarandolo nella colonna
    # `conteggio` — un chunk non e' un token, e i due run non si confrontano.
    n_usage = (usage or {}).get("completion_tokens")
    n_out = n_usage if n_usage is not None else n_chunk
    durata = t_ultimo - t_primo
    riga = {
        "prompt_tokens": (usage or {}).get("prompt_tokens"),
        "completion_tokens": n_out,
        "conteggio": "usage" if n_usage is not None else "chunk",
        "ttft_ms": round((t_primo - t_invio) * 1000, 1),
        # durata == 0 con n_out > 1: stream bufferizzato in un chunk solo
        # (proxy, server che ignora stream). 0.0, non una divisione per zero.
        "tok_s": round((n_out - 1) / durata, 2) if n_out > 1 and durata > 0 else 0.0,
        "finish_reason": finish,
        "t_invio": t_invio,
        "t_fine": t_ultimo,
    }
    if raccogli_testo:
        riga["testo"] = "".join(testo)
        riga["ragionamento"] = "".join(ragionamento)
    return riga


def una_richiesta(args, prompt, via, livello):
    payload = payload_chat(args.model, prompt, args.max_tokens, args.chat_template_kwargs)
    corpo = json.dumps(payload)
    u = urlparse(args.url)
    classe = http.client.HTTPSConnection if u.scheme == "https" else http.client.HTTPConnection
    conn = classe(u.hostname, u.port, timeout=args.timeout)
    try:
        # Connessione PRIMA della barriera: DNS + handshake TCP di N client
        # in raffica non c'entrano col prefill e non devono stare nel TTFT.
        # Se un client non si connette la barriera si rompe per tutti: un
        # livello monco non e' una misura valida di quel livello (e senza
        # abort gli altri client resterebbero appesi per sempre).
        try:
            conn.connect()
        except Exception:
            via.abort()
            raise
        via.wait()  # partenza simultanea di tutti i client del livello
        t_invio = time.monotonic()
        conn.request("POST", "/v1/chat/completions", body=corpo,
                     headers={"Content-Type": "application/json"})
        r = conn.getresponse()
        if r.status != 200:
            raise ValueError(f"HTTP {r.status}: {r.read(200)!r}")
        eventi = []
        for raw in r:
            adesso = time.monotonic()
            # Il timeout della socket copre solo la singola lettura: un
            # server che gocciola un byte al minuto non lo farebbe mai
            # scattare. Qui e' una deadline vera per l'intera richiesta.
            if adesso - t_invio > args.timeout:
                raise TimeoutError(f"deadline di {args.timeout}s superata")
            eventi.append((adesso, raw.decode()))
        riga = misura(eventi, t_invio, raccogli_testo=bool(args.salva_output))
        riga["richiesta"] = parametri_richiesta(payload)
        return riga
    finally:
        conn.close()


def salva_output(path, righe, extra):
    """Una riga JSONL per richiesta col testo generato: e' l'input di
    validity.py. I parametri permettono di verificare il sampling per riga;
    il CSV resta dedicato alle misure."""
    with open(path, "a", encoding="utf-8") as f:
        for r in righe:
            if "testo" not in r:
                continue
            f.write(json.dumps({**extra, **{k: r.get(k) for k in (
                "livello", "run", "classe", "esito", "prompt_tokens", "completion_tokens",
                "ttft_ms", "tok_s", "decode_tok_s", "finish_reason", "testo",
                "ragionamento", "richiesta")}}, ensure_ascii=False) + "\n")


def kwargs_da_argomento(testo):
    return json.loads(testo) if testo else None


def con_esito(args, prompt, via, livello):
    """Una riga per OGNI richiesta, riuscita o no: un thread che muore in
    silenzio farebbe passare per «livello 24» un aggregato misurato su 16
    client.
    """
    base = {"run": RUN_ID, "livello": livello, "esito": "ok", "errore": ""}
    try:
        return {**base, **una_richiesta(args, prompt, via, livello)}
    except Exception as e:  # noqa: BLE001 — qualunque guasto diventa una riga
        return {**base, "esito": "errore", "errore": f"{type(e).__name__}: {e}"}


def aggrega(righe):
    """Aggregato per livello di concorrenza, ordinato per livello.

    tok/s aggregati = token totali / finestra reale (primo invio -> ultima
    fine), non la somma dei tok/s per-richiesta: e' il throughput che il
    gruppo di client ha visto davvero. p95 nearest-rank (deterministico).
    Le righe con esito "errore" non entrano nelle statistiche ma si contano
    in `fallite`: un livello dimezzato non deve passare per sano.
    """
    aggregati = []
    for livello in sorted({r["livello"] for r in righe}):
        del_livello = [r for r in righe if r["livello"] == livello]
        gruppo = [r for r in del_livello if r.get("esito", "ok") == "ok"]
        fallite = len(del_livello) - len(gruppo)
        if not gruppo:
            aggregati.append({"livello": livello, "richieste": 0, "fallite": fallite,
                              "tok_s_aggregati": None,
                              "tok_s_mediana_per_richiesta": None, "ttft_ms_p95": None})
            continue
        finestra = max(r["t_fine"] for r in gruppo) - min(r["t_invio"] for r in gruppo)
        ttft = sorted(r["ttft_ms"] for r in gruppo)
        aggregati.append({
            "livello": livello,
            "richieste": len(gruppo),
            "fallite": fallite,
            "tok_s_aggregati": sum(r["completion_tokens"] for r in gruppo) / finestra
                if finestra > 0 else None,
            "tok_s_mediana_per_richiesta": statistics.median(r["tok_s"] for r in gruppo),
            # nearest-rank: indice 0-based ceil(95n/100)-1 == (95n-1)//100.
            "ttft_ms_p95": ttft[(95 * len(ttft) - 1) // 100],
        })
    return aggregati


def prompt_unico(livello, i, parole, corpi=None):
    testa = f"Cliente {RUN_ID}-{livello}-{i}. "
    corpo = corpi[i % len(corpi)] if corpi else FRASE * max(1, parole // 20)
    return testa + corpo + "\nRiassumi il testo precedente in una frase."


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--url", default="http://localhost:8000")
    p.add_argument("--model", required=True)
    p.add_argument("--livelli", default="1,2,4,8,16,24",
                   help="livelli di concorrenza, separati da virgola")
    p.add_argument("--max-tokens", type=int, default=256)
    p.add_argument("--parole-prompt", type=int, default=150,
                   help="lunghezza approssimativa del prompt in parole")
    p.add_argument("--prompts", default=None,
                   help="file con un prompt per riga: corpi eterogenei fra i "
                        "client; senza, tutti i client condividono FRASE")
    p.add_argument("--timeout", type=float, default=600,
                   help="deadline in secondi per singola richiesta")
    p.add_argument("--out", default="concurrency.csv")
    p.add_argument("--chat-template-kwargs", default=None,
                   help='JSON passato come chat_template_kwargs, es. {"enable_thinking": false}')
    p.add_argument("--salva-output", default=None,
                   help="file JSONL (append) con il testo generato per richiesta, per validity.py")
    args = p.parse_args()
    args.chat_template_kwargs = kwargs_da_argomento(args.chat_template_kwargs)

    corpi = None
    if args.prompts:
        with open(args.prompts) as f:
            corpi = [r.strip() for r in f if r.strip()]

    campi = ["run", "livello", "esito", "errore", "prompt_tokens",
             "completion_tokens", "conteggio", "ttft_ms", "tok_s",
             "finish_reason", "t_invio", "t_fine"]
    righe = []
    # CSV aperto subito e scritto livello per livello: un run interrotto (o
    # un livello che si impianta) non deve perdere i livelli gia' misurati.
    with open(args.out, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=campi, restval="")
        w.writeheader()
        for livello in [int(x) for x in args.livelli.split(",")]:
            via = threading.Barrier(livello)
            with ThreadPoolExecutor(max_workers=livello) as ex:
                futuri = [ex.submit(con_esito, args,
                                    prompt_unico(livello, i, args.parole_prompt, corpi),
                                    via, livello)
                          for i in range(livello)]
                del_livello = [fu.result() for fu in futuri]
            righe += del_livello
            w.writerows({k: r.get(k, "") for k in campi}
                        for r in sorted(del_livello, key=lambda r: r.get("t_invio") or 0))
            f.flush()
            if args.salva_output:
                salva_output(args.salva_output, del_livello, {"run": RUN_ID, "modello": args.model})
            fallite = sum(1 for r in del_livello if r["esito"] == "errore")
            nota = f" ({fallite} fallite)" if fallite else ""
            print(f"livello {livello}: fatto{nota}", flush=True)
            for r in del_livello:
                if r["esito"] == "errore":
                    print(f"  fallita: {r['errore']}", file=sys.stderr, flush=True)

    # Anche l'aggregato su file: e' il numero da cui dipendono le decisioni, e non
    # puo' vivere solo nello scroll di un terminale. I t_invio/t_fine sono
    # monotonic (incomparabili fra run): fra run si aggregano questi CSV.
    radice, est = os.path.splitext(args.out)
    out_aggregati = f"{radice}-aggregates{est or '.csv'}"
    aggregati = aggrega(righe)
    with open(out_aggregati, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["run", "modello"] + list(aggregati[0].keys()))
        w.writeheader()
        w.writerows({"run": RUN_ID, "modello": args.model, **a} for a in aggregati)

    def fmt(x, decimali):
        return "—" if x is None else f"{x:.{decimali}f}"

    print(f"\n{'livello':>8} {'rich.':>6} {'fallite':>8} {'tok/s aggr':>11} "
          f"{'tok/s mediana':>14} {'p95 TTFT ms':>12}")
    for a in aggregati:
        print(f"{a['livello']:>8} {a['richieste']:>6} {a['fallite']:>8} "
              f"{fmt(a['tok_s_aggregati'], 2):>11} "
              f"{fmt(a['tok_s_mediana_per_richiesta'], 2):>14} "
              f"{fmt(a['ttft_ms_p95'], 1):>12}")

    if any(r["esito"] == "errore" for r in righe):
        sys.exit(1)


if __name__ == "__main__":
    main()
