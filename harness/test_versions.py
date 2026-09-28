import subprocess
import tempfile
from pathlib import Path

import unittest


class TestVersioni(unittest.TestCase):
    """versions.sh must locate itself (like driver-lib.sh) and record the
    commit of the repo it lives in, not the one of another checkout."""

    def test_registra_il_commit_di_questa_repo_non_di_unaltra(self):
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            # A minimal copy of the repo with its own HEAD, so the two
            # commits cannot be confused.
            radice = d / "repo"
            radice.mkdir()
            harness = radice / "harness"
            harness.mkdir()
            script_reale = Path(__file__).resolve().parent / "versions.sh"
            (harness / "versions.sh").write_text(script_reale.read_text(encoding="utf-8"), encoding="utf-8")
            (harness / "versions.sh").chmod(0o755)
            for nome in ("latency.py", "concurrency.py", "validity.py"):
                (harness / nome).write_text("", encoding="utf-8")
            subprocess.run(["git", "init", "-q"], cwd=radice, check=True)
            subprocess.run(["git", "config", "user.email", "t@t"], cwd=radice, check=True)
            subprocess.run(["git", "config", "user.name", "t"], cwd=radice, check=True)
            (radice / "f").write_text("x", encoding="utf-8")
            subprocess.run(["git", "add", "f"], cwd=radice, check=True)
            subprocess.run(["git", "commit", "-q", "-m", "iniziale"], cwd=radice, check=True)
            commit_atteso = subprocess.run(["git", "rev-parse", "HEAD"], cwd=radice,
                                            capture_output=True, text=True, check=True).stdout.strip()

            run_dir = d / "run"
            run_dir.mkdir()
            modello_dir = d / "modello"
            modello_dir.mkdir()
            r = subprocess.run(["bash", str(harness / "versions.sh"), str(run_dir), str(modello_dir)],
                                capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, r.stderr)
            versioni_txt = (run_dir / "versions.txt").read_text(encoding="utf-8")
            self.assertIn(f"harness repo: {commit_atteso}", versioni_txt)


if __name__ == "__main__":
    unittest.main()
