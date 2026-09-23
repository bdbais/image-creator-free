# -*- coding: utf-8 -*-
"""Confronto delle versioni e lettura del changelog."""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from imagecreator import __version__  # noqa: E402
from imagecreator.core import aggiornamenti as ag  # noqa: E402


class TestAggiornamenti(unittest.TestCase):
    def test_versioni(self):
        self.assertEqual(ag.versione_tupla("v1.10.2"), (1, 10, 2))
        self.assertTrue(ag.piu_nuova("1.10.0", "1.9.9"))
        self.assertTrue(ag.piu_nuova("v2.0", "1.9.9"))
        self.assertFalse(ag.piu_nuova("1.1.0", "1.1.0"))
        self.assertFalse(ag.piu_nuova("", "1.0.0"))

    def test_changelog_della_versione_corrente(self):
        testo = ag.changelog()
        self.assertTrue(testo, "CHANGELOG.md deve avere la sezione %s" % __version__)
        self.assertNotIn("## ", testo)

    def test_changelog_versione_precedente(self):
        self.assertIn("Prima versione", ag.changelog("1.0.0"))


if __name__ == "__main__":
    unittest.main()
