import io
import unittest
from contextlib import redirect_stdout

import grid_table as tg


class TestTabellaGriglia(unittest.TestCase):
    def test_quartili_sei_run(self):
        # sei run come nel protocollo: mediana fra il 3o e il 4o, Q1-Q3 inclusivi
        m, q1, q3 = tg.quartili([22.7, 22.8, 22.8, 22.9, 22.7, 22.8])
        self.assertAlmostEqual(m, 22.8)
        self.assertAlmostEqual(q1, 22.725)
        self.assertAlmostEqual(q3, 22.8)

    def test_riga_markdown(self):
        righe = [
            dict(ttft_ms="231.3", prefill_tok_s="536.0", decode_tok_s="22.79", tok_s_wall="20.69",
                 itl_ms_p50="45.3", completion_tokens="42", finish_reason="stop"),
            dict(ttft_ms="236.5", prefill_tok_s="524.3", decode_tok_s="22.84", tok_s_wall="20.53",
                 itl_ms_p50="44.9", completion_tokens="256", finish_reason="length"),
        ]
        riga = tg.riga_markdown("f2.1-nospec-off", "corto", righe)
        self.assertTrue(riga.startswith("| f2.1-nospec-off / corto | 234 (233–235) | 530 (527–533) | 22.8 (22.8–22.8) |"), riga)
        self.assertIn("| 45.1 | 149 (96–202) | 1 length, 1 stop |", riga)

    def test_etichetta_file(self):
        self.assertEqual(tg.etichetta_file("/x/f3.2-blazux-off-it.csv"), "f3.2-blazux-off")
        self.assertEqual(tg.etichetta_file("f3.2-blazux-off-code.csv"), "f3.2-blazux-off")
        self.assertEqual(tg.etichetta_file("f3.4-mmap-cold-cold-it.csv"), "f3.4-mmap-cold-cold")

    def test_main_intestazione(self):
        out = io.StringIO()
        with redirect_stdout(out):
            tg.main([])
        self.assertEqual(out.getvalue().count("\n"), 2)


if __name__ == "__main__":
    unittest.main()
