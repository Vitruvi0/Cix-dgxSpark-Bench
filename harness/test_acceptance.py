"""Test del parse dell'accettazione speculativa dai log server (SGLang/vLLM)."""

import unittest

from acceptance import estrai, riassumi

LOG = """[t] Prefill batch, #new-seq: 1
[t] Decode batch, #running-req: 1, #full token: 192, accept len: 2.02, accept rate: 0.34, gen throughput (token/s): 3.01
[t] Decode batch, #running-req: 1, #full token: 192, accept len: 2.20, accept rate: 0.40, gen throughput (token/s): 26.87
[t] Decode batch, #running-req: 2, #full token: 192, accept len: 3.00, accept rate: 0.60, gen throughput (token/s): 40.0
INFO SpecDecoding metrics: Mean acceptance length: 2.50, Accepted throughput: 10.0 tokens/s, Drafted: 100 tokens, Accepted: 60 tokens
"""


class TestAccettazione(unittest.TestCase):
    def test_estrae_sglang_e_vllm(self):
        righe = estrai(LOG)
        self.assertEqual([r["len"] for r in righe], [2.02, 2.20, 3.00, 2.50])
        self.assertEqual(righe[0]["rate"], 0.34)
        self.assertIsNone(righe[3]["rate"])

    def test_riassunto_media_min_max(self):
        r = riassumi(estrai(LOG))
        self.assertEqual(r["n"], 4)
        self.assertAlmostEqual(r["len_media"], (2.02 + 2.20 + 3.00 + 2.50) / 4, places=3)
        self.assertEqual((r["len_min"], r["len_max"]), (2.02, 3.00))
        self.assertAlmostEqual(r["rate_media"], (0.34 + 0.40 + 0.60) / 3, places=3)
