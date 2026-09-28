"""L'archivio deve attestare il corpo HTTP inviato, senza conservare il prompt.

Il trasporto e' finto per verificare il contratto senza server o benchmark.
"""

import csv
import io
import json
import tempfile
import threading
import unittest
from contextlib import contextmanager, redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import concurrency
import latency
import grid_table


STREAM = (
    b'data: {"choices":[{"delta":{"content":"risposta "}}]}\n'
    b'data: {"choices":[{"delta":{"content":"ecco"},"finish_reason":"stop"}]}\n'
    b'data: {"choices":[],"usage":{"prompt_tokens":10,"completion_tokens":2}}\n'
    b'data: [DONE]\n'
)


@contextmanager
def trasporto_finto(client):
    inviati = []
    if client is concurrency:
        def connessione(*args, **kwargs):
            conn = Mock()
            risposta = io.BytesIO(STREAM)
            risposta.status = 200
            conn.getresponse.return_value = risposta
            conn.request.side_effect = lambda method, path, body, headers: inviati.append(json.loads(body))
            return conn

        with patch.object(concurrency.http.client, "HTTPConnection", side_effect=connessione):
            yield inviati
    else:
        def apri(req, **kwargs):
            inviati.append(json.loads(req.data))
            return io.BytesIO(STREAM)

        with patch.object(latency.urllib.request, "urlopen", side_effect=apri):
            yield inviati


class TestArchivioRichiesta(unittest.TestCase):
    def verifica_record(self, record, inviato):
        atteso = dict(inviato)
        atteso.pop("messages", None)
        atteso.pop("prompt", None)
        self.assertEqual(record["richiesta"], atteso)
        self.assertEqual(record["testo"], "risposta ecco")
        self.assertEqual(record["finish_reason"], "stop")
        self.assertNotIn("prompt riservato", json.dumps(record))

    def verifica_client(self, client):
        # Le estensioni e i parametri assenti smascherano una lista di campi
        # ricostruita dagli argomenti CLI invece che dal payload effettivo.
        casi = [
            (None, {}, ()),
            ({"enable_thinking": False}, {}, ()),
            ({"enable_thinking": True, "reasoning_effort": "medium"},
             {"temperature": 0.7, "seed": 1234, "top_p": 0.9, "top_k": 20,
              "stop": ["fine", "basta"], "min_p": None, "ignore_eos": False,
              "prompt": "prompt riservato alternativo"}, ()),
            (None, {}, ("temperature", "seed")),
        ]
        originale = concurrency.payload_chat
        with tempfile.TemporaryDirectory() as tmp:
            archivio = Path(tmp) / "output.jsonl"
            for kw, aggiunte, assenti in casi:
                with self.subTest(client=client.__name__, kw=kw, aggiunte=aggiunte, assenti=assenti):
                    args = SimpleNamespace(model="modello-test", max_tokens=17,
                                           chat_template_kwargs=kw, url="http://test.invalid",
                                           timeout=10, salva_output=str(archivio),
                                           corpus=None, tokenizer_locale=None)

                    def payload(*a, **k):
                        p = originale(*a, **k)
                        p.update(aggiunte)
                        for campo in assenti:
                            p.pop(campo, None)
                        return p

                    with patch.object(client, "payload_chat", side_effect=payload) as costruisci:
                        with trasporto_finto(client) as inviati:
                            if client is concurrency:
                                r = concurrency.con_esito(args, "prompt riservato", threading.Barrier(1), 1)
                                self.assertEqual(r["esito"], "ok")
                            else:
                                r = latency.Client(args).una_run("prompt riservato")
                    costruisci.assert_called_once()
                    self.assertEqual(len(inviati), 1)
                    self.assertEqual(inviati[0]["messages"][0]["content"], "prompt riservato")
                    self.verifica_record(r, inviati[0])
                    concurrency.salva_output(archivio, [r], {"modello": args.model})
                    record = json.loads(archivio.read_text().splitlines()[-1])
                    self.verifica_record(record, inviati[0])
            self.assertEqual(len(archivio.read_text().splitlines()), len(casi))

    def test_concorrenza_archivia_payload_http(self):
        self.verifica_client(concurrency)

    def test_latenza_archivia_payload_http(self):
        self.verifica_client(latency)

    def verifica_main(self, client, opzioni, numero):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "fase-off-it.csv"
            archivio = Path(tmp) / "output.jsonl"
            argv = [client.__name__, "--model", "modello-test", "--url", "http://test.invalid",
                    "--out", str(out), "--salva-output", str(archivio),
                    "--chat-template-kwargs", '{"enable_thinking": false}', *opzioni]
            with patch("sys.argv", argv), redirect_stdout(io.StringIO()):
                with trasporto_finto(client) as inviati:
                    client.main()
            record = [json.loads(r) for r in archivio.read_text().splitlines()]
            self.assertEqual(len(record), numero)
            for r, p in zip(record, inviati):
                self.verifica_record(r, p)
            with out.open() as f:
                reader = csv.DictReader(f)
                self.assertNotIn("richiesta", reader.fieldnames)
                self.assertNotIn("testo", reader.fieldnames)
                self.assertEqual(len(list(reader)), numero)
            if client is latency:
                tabella = io.StringIO()
                with redirect_stdout(tabella):
                    self.assertEqual(grid_table.main([str(out)]), 0)
                self.assertIn("fase-off / corto", tabella.getvalue())
            else:
                with out.with_name("fase-off-it-aggregates.csv").open() as f:
                    aggregati = list(csv.DictReader(f))
                self.assertEqual([r["richieste"] for r in aggregati], ["1", "2"])
                self.assertEqual([r["fallite"] for r in aggregati], ["0", "0"])

    def test_concorrenza_cli_preserva_csv_e_aggregati(self):
        self.verifica_main(concurrency, ["--livelli", "1,2"], 3)

    def test_latenza_cli_preserva_csv_e_tabella(self):
        # La calibrazione e' estranea al contratto da verificare e richiederebbe
        # /tokenize; la generazione passa invece per il client e writer reali.
        with patch.object(latency.Client, "prompt_di", return_value="prompt riservato"):
            self.verifica_main(latency, ["--classi", "corto=100", "--warmup", "0", "--run", "2"], 2)


if __name__ == "__main__":
    unittest.main()
