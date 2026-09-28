"""Test dei controlli di validita' dell'output (corruzione NaN->token 0,
ripetizione degenerata, ragionamento non separato, accettazione anomala)."""

import csv
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from validity import controlla_riga, controlla_tutte, testo_degenerato

HERE = Path(__file__).resolve().parent
FIXTURE = json.loads((HERE / "fixtures/validity-soak-8.json").read_text(encoding="utf-8"))
FIXTURE_59 = json.loads((HERE / "fixtures/validity-soak-59.json").read_text(encoding="utf-8"))
CAMPAGNA = HERE.parent / "results/2026-09-04-flashnext-sglang"
SOAK = Path(FIXTURE["fonte"]).name


def riga(testo="Risposta normale e variata sul testo dato.", **kw):
    base = {"testo": testo, "ragionamento": "", "finish_reason": "stop",
            "completion_tokens": 200, "decode_tok_s": 20.0}
    base.update(kw)
    return base


class TestControllaRiga(unittest.TestCase):
    def test_riga_sana(self):
        self.assertEqual(controlla_riga(riga()), [])

    def test_sequenza_di_punti_esclamativi_e_nan(self):
        # firma sm_121: NaN -> token 0 -> "!" ripetuto (LANDMINES.md)
        self.assertIn("nan_token0", controlla_riga(riga("ok " + "!" * 40)))

    def test_ripetizione_degenerata(self):
        self.assertIn("ripetizione", controlla_riga(riga("la la la la la la la la la la la la la la la la la la la la")))

    def test_think_chiuso_nel_contenuto(self):
        self.assertIn("think_in_content", controlla_riga(riga("pensiero</think>risposta")))

    def test_completion_corta_con_length(self):
        self.assertIn("troncata_corta", controlla_riga(riga(completion_tokens=3, finish_reason="length")))

    def test_decode_anomalo_rispetto_alla_mediana(self):
        # uno stream corrotto accetta ogni draft: tok/s 2-3x la mediana
        righe = [riga(decode_tok_s=20.0) for _ in range(5)] + [riga(decode_tok_s=70.0)]
        esiti = controlla_tutte(righe)
        self.assertIn("decode_anomalo", esiti[-1])
        self.assertEqual(esiti[0], [])


class TestTestoDegenerato(unittest.TestCase):
    def test_caso_59_script_con_tag_nel_contenuto(self):
        caso = FIXTURE_59["righe"][0]
        self.assertEqual(testo_degenerato(caso["testo"]), ["degenerato_script"])
        self.assertEqual(controlla_riga(riga(caso["testo"])),
                         ["think_in_content", "degenerato_script"])
        self.assertEqual(testo_degenerato(caso["testo"].replace("</think>", "")), [])

    def test_soglia_script_con_e_senza_altri_segnali(self):
        straniero = "漢字仮名中文測試語"
        for segnale in ("", "!x!", "</think>"):
            for totale in (600, 599):
                with self.subTest(segnale=segnale, lettere=totale):
                    # 9/600 = 1,5% esatto: protegge il confine stretto anche
                    # contando le lettere del segnale nel denominatore.
                    latine = totale - len(straniero) - sum(c.isalpha() for c in segnale)
                    testo = "a" * latine + straniero + segnale
                    attesi = ["degenerato_script"] if segnale and totale == 599 else []
                    self.assertEqual(testo_degenerato(testo), attesi)

    def test_soglia_script_sospetto_mantiene_minimo_otto(self):
        for segnale in ("!x!", "</think>"):
            with self.subTest(segnale=segnale):
                self.assertEqual(testo_degenerato("漢字仮名中文測" + segnale), [])
                self.assertEqual(testo_degenerato("a" * 400 + "漢字仮名中文測試" + segnale),
                                 ["degenerato_script"])

    def test_segnali_nel_codice_non_abbassano_soglia_script(self):
        prosa = "a" * 400 + "漢字仮名中文測試"
        for segnale in ("!x!", "</think>"):
            for chiusura in ("```", ""):
                with self.subTest(segnale=segnale, chiusura=chiusura):
                    self.assertEqual(testo_degenerato(prosa + "```\n" + segnale + chiusura), [])
            # citazione inline: `!important!` in prosa tecnica, il tag spiegato
            with self.subTest(segnale=segnale, inline=True):
                self.assertEqual(testo_degenerato(prosa + " usa `" + segnale + "` qui"), [])
                self.assertEqual(testo_degenerato(prosa + " usa " + segnale + " qui"), ["degenerato_script"])

    def test_segnali_in_altro_campo_non_abbassano_soglia_script(self):
        prosa = "a" * 400 + "漢字仮名中文測試"
        for segnale in ("!x!", "</think>"):
            for testo, ragionamento in ((prosa, segnale), (segnale, prosa)):
                with self.subTest(testo=testo, ragionamento=ragionamento):
                    attesi = ["think_in_content"] if testo == "</think>" else []
                    self.assertEqual(controlla_riga(riga(testo, ragionamento=ragionamento)), attesi)

    def test_risposte_reali_copiate_dal_soak(self):
        for caso in FIXTURE["righe"]:
            with self.subTest(riga=caso["riga"]):
                self.assertIn("degenerato_script", testo_degenerato(caso["testo"]))
                self.assertIn("degenerato_script", controlla_riga(riga(caso["testo"])))
        self.assertIn("degenerato_lettere", testo_degenerato(FIXTURE["righe"][0]["testo"]))

    def test_script_non_latini_e_soglie(self):
        for straniero in ("漢字仮名中文測試", "абвгдежз", "ابتثجحخد", "αβγδεζηθ"):
            with self.subTest(script=straniero):
                self.assertEqual(testo_degenerato("Risposta italiana " + straniero),
                                 ["degenerato_script"])
                # 8 su 400 lettere = 2%: il confine non viene segnalato.
                self.assertEqual(testo_degenerato("a" * 392 + straniero), [])
                self.assertEqual(testo_degenerato("a" * 391 + straniero),
                                 ["degenerato_script"])
        self.assertEqual(testo_degenerato("漢字仮名中文測"), [])  # solo 7 lettere

    def test_punteggiatura_ripetuta_e_soglie(self):
        for pattern in ("!!", "??", "!?", "!wsa!", "....", ",,,,", ";;;;", "::::"):
            with self.subTest(pattern=pattern):
                self.assertEqual(testo_degenerato((pattern + " testo ") * 2), [])
                self.assertEqual(testo_degenerato((pattern + " testo ") * 3),
                                 ["degenerato_punteggiatura"])
        self.assertEqual(testo_degenerato("!uno! !! ????"), ["degenerato_punteggiatura"])

    def test_lettere_sparse_e_soglie(self):
        self.assertEqual(testo_degenerato("B s B1 Bx c C B s " * 5), ["degenerato_lettere"])
        self.assertEqual(testo_degenerato("B " * 39), [])
        self.assertEqual(testo_degenerato("B " * 16 + "parola " * 24), [])  # 40%
        self.assertEqual(testo_degenerato("B " * 17 + "parola " * 23),
                         ["degenerato_lettere"])
        self.assertEqual(testo_degenerato("B1 " * 40), [])

    def test_italiano_inglese_nomi_stranieri_e_markdown(self):
        testi = [
            "Per la gestione delle fatture di una piccola impresa è utile tenere un "
            "registro con le date di emissione e di pagamento, in modo da avere "
            "una vista chiara di quanto è già stato incassato e di quanto resta da riscuotere.",
            "The application keeps a separate record for each customer and checks "
            "the invoice date before sending a reminder. You can review the monthly "
            "report to identify missing payments, update contact details and assign "
            "the remaining tasks to the appropriate team members.",
            "La riunione con François Müller, Søren Kierkegaard e Łukasz Żółć è confermata.",
            "I referenti sono 王伟 e Иван; invieranno il documento aggiornato domani.",
            "### Stato\n**Fatture**: tutto pronto!!\n---\n"
            "### Clienti\n**Ordini**: attendiamo...\n---\n"
            "### Fornitori\n**Pagamenti**: verificati...\n---\n"
            "| Nome | Stato |\n| --- | --- |\n| Rossi | Fatto |",
            "", "123 456", "L'attività è già conclusa, perché tutto è verificato.",
        ]
        for testo in testi:
            with self.subTest(testo=testo):
                self.assertEqual(testo_degenerato(testo), [])

    def test_codice_escluso_anche_se_troncato(self):
        codice = "const 名前 = '漢字仮名中文測試 абвгдежз';\n// !! !! !! !wsa!\n" + "B s B1 Bx c C B s\n" * 6
        for chiusura in ("```\nFine della spiegazione.", ""):
            with self.subTest(chiusura=chiusura):
                self.assertEqual(testo_degenerato("Ecco il codice:\n```js\n" + codice + chiusura), [])
        self.assertEqual(testo_degenerato("```js\n" + codice + "```\nTesto\n```\n" + codice + "```"), [])
        self.assertEqual(testo_degenerato("```js\n" + codice + "```\n!! !! !!"),
                         ["degenerato_punteggiatura"])

    def test_campi_separati_e_etichette_senza_duplicati(self):
        corrotto = "漢字仮名中文測試"
        for testo, ragionamento in ((corrotto, "```python\n"), ("```python\n", corrotto),
                                    (corrotto, corrotto)):
            with self.subTest(testo=testo):
                self.assertEqual(controlla_riga(riga(testo, ragionamento=ragionamento)),
                                 ["degenerato_script"])
        self.assertEqual(controlla_riga(riga(None, ragionamento=None)), [])

    def test_bassa_varieta_riusa_controlli_esistenti(self):
        self.assertEqual(controlla_riga(riga("!" * 20)), ["nan_token0"])
        self.assertIn("ripetizione", controlla_riga(riga("frase ripetuta senza varieta " * 20)))


@unittest.skipUnless(
    (CAMPAGNA / SOAK).is_file(),
    "raw model outputs of the SGLang campaign are not published",
)
class TestCampagnaSGLang(unittest.TestCase):
    def test_930_righe_zero_falsi_positivi(self):
        note = {(SOAK, caso["riga"]): caso["testo"] for caso in FIXTURE["righe"]}
        totale = 0
        trovate = set()
        for path in sorted(CAMPAGNA.glob("*.jsonl")):
            # I JSONL dei soak sono il corpus dove la corruzione e' attesa: qui si
            # verifica l'assenza di falsi positivi sulle fasi sane, piu' l'iterazione 8 nota.
            if path.name.startswith("soak-") and path.name != SOAK:
                continue
            for numero, linea in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
                if not linea.strip():
                    continue
                record = json.loads(linea)
                if "testo" not in record:
                    continue
                totale += 1
                chiave = (path.name, numero)
                with self.subTest(file=path.name, riga=numero):
                    nuovi = [p for p in controlla_riga(record) if p.startswith("degenerato_")]
                    if chiave in note:
                        trovate.add(chiave)
                        self.assertEqual(record["testo"], note[chiave])
                        self.assertTrue(nuovi)
                    else:
                        self.assertEqual(nuovi, [])
        # Evita un verde vacuo se mancano i dati o cambia la selezione dei file.
        # La dir cresce a ogni fase (griglie SME, equivalenze): basta che il corpus non si svuoti.
        self.assertGreaterEqual(totale, 1194)
        self.assertEqual(trovate, set(note))

    def test_iterazione_8_controlla_tutte_e_cli(self):
        path = CAMPAGNA / SOAK
        righe = [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines()]
        esiti = controlla_tutte(righe)
        attesi = [False, True, True, False, False, False, False, False]
        self.assertEqual([bool(e) for e in esiti], attesi)
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "validita.csv"
            risultato = subprocess.run(
                [sys.executable, str(HERE / "validity.py"), "--output", str(path), "--out", str(out)],
                capture_output=True, text=True, timeout=10)
            self.assertEqual(risultato.returncode, 1, risultato.stderr)
            self.assertIn("8 righe, 2 invalide", risultato.stdout)
            with out.open(newline="") as f:
                csv_righe = list(csv.DictReader(f))
            self.assertEqual([r["valido"] == "no" for r in csv_righe], attesi)
            self.assertEqual([r["problemi"].split() for r in csv_righe], esiti)
