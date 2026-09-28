"""Test delle metriche di efficienza del tokenizer (tok/parola, byte/token)."""

import unittest

from tokenizer_eff import metriche


class TokFinto:
    """Un token ogni 4 caratteri: 'abcd efgh' -> 3 token (spazio incluso)."""
    def encode(self, testo, add_special_tokens=False):
        class E:
            ids = list(range((len(testo) + 3) // 4))
        return E()


class TestMetriche(unittest.TestCase):
    def test_tok_per_parola_e_byte_per_token(self):
        m = metriche(TokFinto(), "abcd efgh ijkl mnop")  # 19 char -> 5 token, 4 parole
        self.assertEqual(m["token"], 5)
        self.assertEqual(m["parole"], 4)
        self.assertAlmostEqual(m["tok_per_parola"], 1.25)
        self.assertAlmostEqual(m["byte_per_token"], 19 / 5)
        self.assertAlmostEqual(m["char_per_token"], 19 / 5)

    def test_utf8_conta_i_byte_non_i_caratteri(self):
        m = metriche(TokFinto(), "èèèè")  # 4 char, 8 byte, 1 token
        self.assertEqual(m["token"], 1)
        self.assertEqual(m["byte_per_token"], 8.0)
        self.assertEqual(m["char_per_token"], 4.0)
