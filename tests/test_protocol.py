# -*- coding: utf-8 -*-
"""Avvia davvero il worker come sottoprocesso e verifica il dialogo JSON Lines.

Non serve né il modello né diffusers: si controllano handshake, comandi
sconosciuti, chiusura pulita e - se torch è installato - il comando probe.
"""
import json
import os
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORKER = ROOT / "worker" / "qwen_worker.py"


def talk(commands, timeout=180):
    """Manda i comandi al worker e restituisce la lista di eventi ricevuti."""
    env = dict(os.environ, PYTHONUNBUFFERED="1", PYTHONUTF8="1")
    proc = subprocess.run(
        [sys.executable, "-u", str(WORKER)],
        input="".join(json.dumps(c) + "\n" for c in commands),
        capture_output=True, text=True, encoding="utf-8", timeout=timeout, env=env,
    )
    events = []
    for line in proc.stdout.splitlines():
        line = line.strip()
        if line.startswith("{"):
            events.append(json.loads(line))
    return events, proc


class TestProtocollo(unittest.TestCase):
    def test_handshake_e_chiusura(self):
        events, proc = talk([{"cmd": "shutdown"}])
        self.assertEqual(proc.returncode, 0, proc.stderr[-500:])
        kinds = [e["ev"] for e in events]
        self.assertEqual(kinds[0], "hello")
        self.assertEqual(kinds[-1], "bye")
        self.assertIn("python", events[0])

    def test_comando_sconosciuto_non_uccide_il_worker(self):
        events, proc = talk([{"cmd": "banana"}, {"cmd": "shutdown"}])
        self.assertEqual(proc.returncode, 0)
        errors = [e for e in events if e["ev"] == "error"]
        self.assertTrue(errors)
        self.assertIn("banana", errors[0]["msg"])
        self.assertEqual(events[-1]["ev"], "bye")

    def test_riga_non_json_non_uccide_il_worker(self):
        env = dict(os.environ, PYTHONUNBUFFERED="1", PYTHONUTF8="1")
        proc = subprocess.run(
            [sys.executable, "-u", str(WORKER)],
            input="questa non è json\n" + json.dumps({"cmd": "shutdown"}) + "\n",
            capture_output=True, text=True, encoding="utf-8", timeout=120, env=env)
        self.assertEqual(proc.returncode, 0)
        self.assertIn('"ev": "bye"', proc.stdout.replace('"ev":"bye"', '"ev": "bye"'))

    @unittest.skipUnless(
        subprocess.run([sys.executable, "-c", "import torch"], capture_output=True).returncode == 0,
        "torch non installato in questo interprete")
    def test_probe_riporta_torch(self):
        events, _ = talk([{"cmd": "probe"}, {"cmd": "shutdown"}])
        probes = [e for e in events if e["ev"] == "probe"]
        self.assertTrue(probes)
        self.assertIn("torch", probes[0])
        self.assertIn("cuda", probes[0])

    @unittest.skipIf(
        subprocess.run([sys.executable, "-c", "import diffusers"],
                       capture_output=True).returncode == 0,
        "diffusers installato: qui si verifica solo il caso di ambiente incompleto")
    def test_load_senza_diffusers_riporta_un_errore_leggibile(self):
        events, proc = talk([{"cmd": "load"}, {"cmd": "shutdown"}])
        self.assertEqual(proc.returncode, 0)
        errors = [e for e in events if e["ev"] == "error"]
        self.assertTrue(errors, "atteso un evento error, ricevuti: %s"
                        % [e["ev"] for e in events])
        self.assertTrue(errors[0]["msg"])
        self.assertEqual(events[-1]["ev"], "bye")


if __name__ == "__main__":
    unittest.main()
