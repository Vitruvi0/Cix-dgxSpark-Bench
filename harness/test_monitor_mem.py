"""Test del parse di /proc/meminfo e /proc/vmstat del monitor di memoria."""

import unittest

from monitor_mem import campione

MEMINFO = "MemTotal:       126000000 kB\nMemAvailable:    100000000 kB\nCached:  9000000 kB\nSwapTotal: 16777212 kB\nSwapFree: 15000000 kB\n"
VMSTAT = "pswpin 10\npswpout 20\npgmajfault 300\n"


class TestCampione(unittest.TestCase):
    def test_campi_in_gib_e_contatori(self):
        c = campione(MEMINFO, VMSTAT)
        self.assertAlmostEqual(c["usata_gib"], (126000000 - 100000000) / 2**20, places=2)
        self.assertAlmostEqual(c["cache_gib"], 9000000 / 2**20, places=2)
        self.assertAlmostEqual(c["swap_usato_gib"], (16777212 - 15000000) / 2**20, places=2)
        self.assertEqual(c["pswpin"], 10)
        self.assertEqual(c["pgmajfault"], 300)

    def test_temperatura_gpu_colonna_sempre_presente(self):
        # la colonna c'e' sempre (CSV omogenei fra macchine); vuota senza nvidia-smi
        c = campione(MEMINFO, VMSTAT, gpu_temp="42\n")
        self.assertEqual(c["gpu_temp_c"], 42)
        c = campione(MEMINFO, VMSTAT, gpu_temp=None)
        self.assertEqual(c["gpu_temp_c"], "")
        c = campione(MEMINFO, VMSTAT, gpu_temp="[N/A]")
        self.assertEqual(c["gpu_temp_c"], "")

DISKSTATS = (
    " 259       0 nvme0n1 284332 33980 44410554 43060 136966 94915 9975746 120081 0 25604 165575 0 0 0 0 52778 2434\n"
    " 259       1 nvme0n1p1 469 819 19310 78 2 0 2 1 0 32 80 0 0 0 0 0 0\n"
    " 259       2 nvme0n1p2 283579 33161 44382742 42973 136964 94915 9975744 120079 0 29734 163053 0 0 0 0 0 0\n"
    "   7       0 loop0 10 0 80 0 0 0 0 0 0 0 0 0 0 0 0 0 0\n"
)


class TestDiskstats(unittest.TestCase):
    def test_settori_del_disco_intero_non_delle_partizioni(self):
        # le letture del disco vanno ricostruite per fase; i settori
        # del disco intero (campi 3 e 7 di /proc/diskstats) sono i cumulativi da cui si fa la delta
        c = campione(MEMINFO, VMSTAT, diskstats=DISKSTATS)
        self.assertEqual(c["sectors_read"], 44410554)
        self.assertEqual(c["sectors_written"], 9975746)

    def test_nvme_vince_su_sd_a_prescindere_dall_ordine(self):
        usb = "   8       0 sda 5 0 40 0 1 0 8 0 0 0 0 0 0 0 0 0 0\n"
        c = campione(MEMINFO, VMSTAT, diskstats=usb + DISKSTATS)
        self.assertEqual((c["sectors_read"], c["sectors_written"]), (44410554, 9975746))
        c = campione(MEMINFO, VMSTAT, diskstats=usb)
        self.assertEqual((c["sectors_read"], c["sectors_written"]), (40, 8))

    def test_colonne_sempre_presenti_senza_nvme(self):
        c = campione(MEMINFO, VMSTAT, diskstats="   7       0 loop0 10 0 80 0 0 0 0 0 0 0 0 0 0 0 0 0 0\n")
        self.assertEqual(c["sectors_read"], "")
        self.assertEqual(c["sectors_written"], "")
        c = campione(MEMINFO, VMSTAT)
        self.assertEqual(c["sectors_read"], "")
