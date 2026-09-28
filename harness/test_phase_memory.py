import unittest

import phase_memory as mf

CSV = """t,usata_gib,cache_gib,swap_usato_gib,pswpin,pswpout,pgmajfault
11:28:12,110.0,9.0,3.0,100,1000,500
11:28:14,112.1,9.2,3.5,100,1200,700
11:28:16,114.2,8.9,6.3,100,3000,900
"""


class TestMemoriaFase(unittest.TestCase):
    def test_riassunto_fase(self):
        r = mf.riassumi(CSV.splitlines())
        self.assertEqual(r["campioni"], 3)
        self.assertEqual((r["da"], r["a"]), ("11:28:12", "11:28:16"))
        self.assertAlmostEqual(r["usata_max_gib"], 114.2)
        self.assertEqual((r["swap_min_gib"], r["swap_max_gib"]), (3.0, 6.3))
        self.assertEqual(r["pswpout_delta"], 2000)
        self.assertAlmostEqual(r["pswpout_delta_gib"], 2000 * 4096 / 2**30)
        self.assertEqual(r["pgmajfault_delta"], 400)

    def test_verdetto_swap(self):
        # swap-out durante la fase -> va dichiarato; zero -> pulito
        self.assertEqual(mf.verdetto_swap(2000), "swap attivo in decode")
        self.assertEqual(mf.verdetto_swap(0), "nessuno swap-out")

    def test_riga_markdown(self):
        r = mf.riassumi(CSV.splitlines())
        riga = mf.riga_markdown("f3.2-blazux", r)
        self.assertEqual(riga, "| f3.2-blazux | 114.2 | 3.0–6.3 | 0.01 | 400 | swap attivo in decode | – | – | – |")



class TestTemperatura(unittest.TestCase):
    def test_picco_temperatura_se_colonna_presente(self):
        csv_con = ["t,usata_gib,cache_gib,swap_usato_gib,pswpin,pswpout,pgmajfault,gpu_temp_c",
                   "10:00:00,50.0,10.0,1.0,0,0,100,40", "10:00:02,60.0,10.0,1.0,0,0,100,55", "10:00:04,55.0,10.0,1.0,0,0,100,"]
        self.assertEqual(mf.riassumi(csv_con)["gpu_temp_max_c"], 55)
        csv_senza = ["t,usata_gib,cache_gib,swap_usato_gib,pswpin,pswpout,pgmajfault",
                     "10:00:00,50.0,10.0,1.0,0,0,100"]
        self.assertIsNone(mf.riassumi(csv_senza)["gpu_temp_max_c"])


class TestDisco(unittest.TestCase):
    def test_delta_settori_in_gib_se_colonne_presenti(self):
        # la delta dei settori (512 byte) fra primo e ultimo campione attribuisce
        # letture e scritture NVMe alla fase; colonne vuote senza disco nvme/sd
        csv_con = ["t,usata_gib,cache_gib,swap_usato_gib,pswpin,pswpout,pgmajfault,sectors_read,sectors_written,gpu_temp_c",
                   "10:00:00,50.0,10.0,1.0,0,0,100,1000,500,40", "10:00:02,60.0,10.0,1.0,0,0,100,2097152,500,41",
                   "10:00:04,55.0,10.0,1.0,0,0,100,4195304,1049076,42"]
        r = mf.riassumi(csv_con)
        self.assertAlmostEqual(r["letti_delta_gib"], (4195304 - 1000) * 512 / 2**30)
        self.assertAlmostEqual(r["scritti_delta_gib"], (1049076 - 500) * 512 / 2**30)
        self.assertIn("| 2.00 | 0.50 |", mf.riga_markdown("x", r))
        csv_vuote = [csv_con[0], "10:00:00,50.0,10.0,1.0,0,0,100,,,40", "10:00:02,50.0,10.0,1.0,0,0,100,,,40"]
        self.assertIsNone(mf.riassumi(csv_vuote)["letti_delta_gib"])
        csv_senza = ["t,usata_gib,cache_gib,swap_usato_gib,pswpin,pswpout,pgmajfault", "10:00:00,50.0,10.0,1.0,0,0,100"]
        self.assertIsNone(mf.riassumi(csv_senza)["scritti_delta_gib"])
        self.assertTrue(mf.riga_markdown("x", mf.riassumi(csv_senza)).endswith("| – | – | – |"))

    def test_contatore_non_monotono_annulla_la_delta(self):
        csv_reset = ["t,usata_gib,cache_gib,swap_usato_gib,pswpin,pswpout,pgmajfault,sectors_read,sectors_written",
                     "10:00:00,50.0,10.0,1.0,0,0,100,5000,900", "10:00:02,50.0,10.0,1.0,0,0,100,10,20",
                     "10:00:04,50.0,10.0,1.0,0,0,100,9000,2000"]
        r = mf.riassumi(csv_reset)
        self.assertIsNone(r["letti_delta_gib"])
        self.assertIsNone(r["scritti_delta_gib"])


if __name__ == "__main__":
    unittest.main()
