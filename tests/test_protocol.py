# -*- coding: utf-8 -*-
"""Avvia davvero il worker come sottoprocesso e verifica il dialogo JSON Lines.

Non serve né il modello né diffusers: si controllano handshake, comandi
sconosciuti, chiusura pulita e - se torch è installato - il comando probe.
"""
import json
import os
import subprocess
import sys
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORKER = ROOT / "worker" / "qwen_worker.py"
sys.path.insert(0, str(ROOT / "worker"))


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
        # Prima dell'handshake il worker annuncia che sta caricando le librerie.
        self.assertIn("hello", kinds)
        self.assertEqual(kinds[-1], "bye")
        hello = next(e for e in events if e["ev"] == "hello")
        self.assertIn("python", hello)

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


    def test_cancel_arriva_mentre_il_worker_e_occupato(self):
        """Il lettore di stdin gira a parte: cancel deve agire subito, non a fine lavoro."""
        import threading

        import qwen_worker

        class FintoStdin:
            """stdin finto: la terza riga arriva solo quando il test lo consente."""

            def __init__(self, sbloccato):
                self.righe = [json.dumps({"cmd": "probe"}) + "\n",
                              json.dumps({"cmd": "cancel"}) + "\n"]
                self.coda = json.dumps({"cmd": "shutdown"}) + "\n"
                self.sbloccato = sbloccato

            def readline(self):
                if self.righe:
                    return self.righe.pop(0)
                self.sbloccato.wait(10)
                riga, self.coda = self.coda, ""
                return riga

        sbloccato = threading.Event()
        originale = qwen_worker.sys.stdin
        qwen_worker.sys.stdin = FintoStdin(sbloccato)
        qwen_worker._cancel.clear()
        ricevuti = []
        try:
            stream = qwen_worker._incoming()
            ricevuti.append(next(stream))                 # probe
            for _ in range(100):                          # il cancel non entra in coda
                if qwen_worker._cancel.is_set():
                    break
                time.sleep(0.02)
            self.assertTrue(qwen_worker._cancel.is_set(),
                            "cancel non ha alzato il flag mentre il worker era occupato")
            sbloccato.set()
            ricevuti.append(next(stream))                 # shutdown
        finally:
            sbloccato.set()
            qwen_worker.sys.stdin = originale
            qwen_worker._cancel.clear()
        self.assertEqual([c["cmd"] for c in ricevuti], ["probe", "shutdown"])

    def test_comandi_con_stdin_aperto(self):
        """Caso della GUI: chi scrive non chiude stdin e aspetta la risposta.

        Con "for line in sys.stdin" i comandi restavano nel buffer del lettore
        e il processo sembrava bloccato appena dopo l'handshake.
        """
        env = dict(os.environ, PYTHONUNBUFFERED="1", PYTHONUTF8="1")
        proc = subprocess.Popen(
            [sys.executable, "-u", str(WORKER)],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            text=True, encoding="utf-8", bufsize=1, env=env)
        try:
            proc.stdin.write(json.dumps({"cmd": "banana"}) + "\n")
            proc.stdin.flush()
            deadline = time.time() + 30
            seen = []
            while time.time() < deadline:
                line = proc.stdout.readline()
                if not line:
                    break
                if line.startswith("{"):
                    seen.append(json.loads(line))
                    if seen[-1]["ev"] == "error":
                        break
            self.assertTrue(any(e["ev"] == "error" for e in seen),
                            "nessuna risposta mentre stdin resta aperto: %s"
                            % [e["ev"] for e in seen])
        finally:
            try:
                proc.stdin.write(json.dumps({"cmd": "shutdown"}) + "\n")
                proc.stdin.flush()
                proc.wait(timeout=20)
            except Exception:
                proc.kill()


if __name__ == "__main__":
    unittest.main()
