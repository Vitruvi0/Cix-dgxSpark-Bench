"""Test della misura per richiesta del client a batch 1 (TTFT, decode,
inter-token latency) e della costruzione dei prompt. Il giro HTTP si valida
con lo smoke reale contro vllm (vedi README)."""

import unittest

from latency import fetta_corpus, misura_latenza


def chunk(testo):
    return f'data: {{"choices":[{{"delta":{{"content":"{testo}"}}}}]}}'


USAGE = 'data: {"choices":[],"usage":{"prompt_tokens":8000,"completion_tokens":5}}'


class TestMisuraLatenza(unittest.TestCase):
    def test_ttft_decode_e_itl_dai_timestamp(self):
        # 5 token in 5 chunk: gap 0.1, 0.1, 0.3, 0.1 s
        eventi = [(1.0, chunk("a")), (1.1, chunk("b")), (1.2, chunk("c")),
                  (1.5, chunk("d")), (1.6, chunk("e")), (1.6, USAGE)]
        r = misura_latenza(eventi, t_invio=0.5)
        self.assertEqual(r["ttft_ms"], 500.0)
        self.assertEqual(r["completion_tokens"], 5)
        self.assertEqual(r["prompt_tokens"], 8000)
        self.assertEqual(r["prefill_tok_s"], 16000.0)
        # (5-1) token / 0.6 s
        self.assertAlmostEqual(r["decode_tok_s"], 6.67, places=2)
        # ITL media per token = finestra di decode / (n-1) = 150 ms
        self.assertAlmostEqual(r["itl_ms_media"], 150.0, places=1)
        # gap per chunk: p50 = 100 ms, p95 vicino al gap lungo (300 ms)
        self.assertAlmostEqual(r["itl_ms_p50"], 100.0, places=1)
        self.assertGreater(r["itl_ms_p95"], 250.0)
        self.assertEqual(r["n_chunk"], 5)

    def test_chunk_multi_token_dello_speculative_non_falsano_la_media(self):
        # Con lo speculative decoding un chunk porta piu' token: la media
        # per token usa usage, i percentili restano per chunk (dichiarato).
        eventi = [(1.0, chunk("a")), (2.0, chunk("bcd")), (3.0, chunk("e")),
                  (3.0, USAGE)]
        r = misura_latenza(eventi, t_invio=0.0)
        self.assertEqual(r["n_chunk"], 3)
        self.assertAlmostEqual(r["itl_ms_media"], 500.0, places=1)  # 2 s / 4
        self.assertAlmostEqual(r["itl_ms_p50"], 1000.0, places=1)

    def test_un_solo_chunk_non_divide_per_zero(self):
        eventi = [(1.0, chunk("a")), (1.0, 'data: {"choices":[],"usage":{"prompt_tokens":3,"completion_tokens":1}}')]
        r = misura_latenza(eventi, t_invio=0.0)
        self.assertEqual(r["decode_tok_s"], 0.0)
        self.assertIsNone(r["itl_ms_media"])
        self.assertIsNone(r["itl_ms_p50"])

    def test_stream_vuoto_e_un_errore(self):
        with self.assertRaises(ValueError):
            misura_latenza([(1.0, USAGE)], t_invio=0.0)


class TestFettaCorpus(unittest.TestCase):
    def test_fette_diverse_per_slot_e_non_sovrapposte(self):
        testo = "".join(chr(97 + i % 26) for i in range(1000))
        a = fetta_corpus(testo, inizio=100, passo=200, slot=0, caratteri=150)
        b = fetta_corpus(testo, inizio=100, passo=200, slot=1, caratteri=150)
        self.assertEqual(len(a), 150)
        self.assertNotEqual(a, b)
        self.assertEqual(a, testo[100:250])
        self.assertEqual(b, testo[300:450])

    def test_corpus_troppo_corto_e_un_errore_non_un_prompt_vuoto(self):
        with self.assertRaises(ValueError):
            fetta_corpus("breve", inizio=0, passo=10, slot=3, caratteri=100)


if __name__ == "__main__":
    unittest.main()


class TestWallClockETokenizerLocale(unittest.TestCase):
    def test_tok_s_wall_include_il_ttft(self):
        # 5 token, invio a 0.0, ultimo chunk a 2.0: wall = 5/2.0, come lo
        # sgbench di azampatti (completion / tempo totale) — la colonna che
        # rende confrontabili i suoi numeri con i nostri.
        eventi = [(1.0, chunk("a")), (1.25, chunk("b")), (1.5, chunk("c")),
                  (1.75, chunk("d")), (2.0, chunk("e")), (2.0, USAGE)]
        r = misura_latenza(eventi, t_invio=0.0)
        self.assertAlmostEqual(r["tok_s_wall"], 2.5, places=2)
        self.assertEqual(r["finish_reason"], None)

    def test_contatore_locale_sostituisce_tokenize(self):
        from latency import ContatoreLocale

        class TokFinto:
            def encode(self, testo, add_special_tokens=False):
                class E:
                    ids = testo.split()
                return E()

        c = ContatoreLocale(TokFinto())
        self.assertEqual(c("uno due tre"), 3)


class TestPromptDaFile(unittest.TestCase):
    """--prompts: classe unica dai prompt di un file (uno per riga), niente corpus;
    i primi `warmup` prompt scaldano, gli altri misurano (protocollo: >= 5 run)."""

    def test_prompt_da_file_in_ordine_warmup_poi_run(self):
        from latency import piano_prompts
        prompts = [f"p{i}" for i in range(8)]
        piano = piano_prompts(prompts, warmup=2)
        self.assertEqual([p for p, _ in piano], prompts)
        self.assertEqual([w for _, w in piano], [True, True] + [False] * 6)

    def test_meno_prompt_del_minimo_e_un_errore(self):
        from latency import piano_prompts
        with self.assertRaises(ValueError):
            piano_prompts(["a", "b", "c"], warmup=2)   # 1 run misurata < 5
