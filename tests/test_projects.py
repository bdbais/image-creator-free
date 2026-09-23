# -*- coding: utf-8 -*-
"""Progetti: creazione, clonazione, immagini e riferimenti."""
import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from imagecreator.core import config, projects  # noqa: E402


class TestProjects(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self._prima = os.environ.get("ICF_DATA_DIR")
        os.environ["ICF_DATA_DIR"] = str(self.tmp / "dati")
        settings = config.Settings.load()
        settings.output_dir = str(self.tmp / "immagini")
        settings.save()

    def tearDown(self):
        if self._prima is None:
            os.environ.pop("ICF_DATA_DIR", None)
        else:
            os.environ["ICF_DATA_DIR"] = self._prima
        self._tmp.cleanup()

    def test_crea_salva_e_rilegge(self):
        p = projects.create("Spritz in spiaggia", {"prompt": "uno spritz", "steps": 30,
                                                   "sconosciuto": 1})
        letto = projects.load(p.id)
        self.assertEqual(letto.name, "Spritz in spiaggia")
        self.assertEqual(letto.params["prompt"], "uno spritz")
        self.assertEqual(letto.params["steps"], 30)
        self.assertNotIn("sconosciuto", letto.params)
        self.assertIn("spritz-in-spiaggia", p.id)

    def test_id_unici_anche_con_lo_stesso_nome(self):
        a = projects.create("Uguale")
        b = projects.create("Uguale")
        self.assertNotEqual(a.id, b.id)
        self.assertEqual(len(projects.list_all()), 2)

    def test_clone_copia_i_parametri_non_le_immagini(self):
        p = projects.create("Originale", {"prompt": "gatto", "seed": 42})
        projects.add_image(p, {"path": str(self.tmp / "x.png"), "seed": 42}, p.params)
        c = projects.clone(p)
        self.assertEqual(c.name, "Originale (copia)")
        self.assertEqual(c.params["prompt"], "gatto")
        self.assertEqual(c.images, [])
        self.assertEqual(c.parent, p.id)
        # Cambiare la copia non tocca l'originale.
        c.params["prompt"] = "cane"
        projects.save(c)
        self.assertEqual(projects.load(p.id).params["prompt"], "gatto")

    def test_clone_con_parametri_di_una_immagine(self):
        p = projects.create("Base", {"prompt": "gatto", "seed": None})
        c = projects.clone(p, "Variante", {**p.params, "seed": 7, "steps": 50})
        self.assertEqual((c.name, c.params["seed"], c.params["steps"]), ("Variante", 7, 50))

    def test_immagini_con_i_propri_parametri(self):
        p = projects.create("Serie", {"prompt": "primo"})
        img = self.tmp / "a.png"
        img.write_bytes(b"png")
        projects.add_image(p, {"path": str(img), "seed": 1}, {"prompt": "primo"})
        p.params["prompt"] = "secondo"
        projects.save(p)
        letto = projects.load(p.id)
        self.assertEqual(letto.images[0]["params"]["prompt"], "primo")
        self.assertEqual(letto.cover, str(img))
        img.unlink()
        self.assertEqual(projects.images_on_disk(letto), [])

    def test_riferimenti_copiati_nel_progetto(self):
        ref = self.tmp / "foto.jpg"
        ref.write_bytes(b"jpg")
        p = projects.create("Con foto", {"refs": [str(ref), str(self.tmp / "manca.jpg")]})
        refs = projects.keep_refs(p)
        self.assertEqual(len(refs), 1)
        self.assertTrue(Path(refs[0]).exists())
        self.assertIn(p.id, refs[0])
        # Una seconda volta non duplica.
        self.assertEqual(projects.keep_refs(p), refs)

    def test_elimina_lascia_le_immagini(self):
        p = projects.create("Da togliere")
        cartella = projects.output_dir(p)
        cartella.mkdir(parents=True)
        (cartella / "a.png").write_bytes(b"png")
        projects.delete(p)
        self.assertIsNone(projects.load(p.id))
        self.assertTrue((cartella / "a.png").exists())

    def test_nomi(self):
        self.assertEqual(projects.slug("Città è bella!"), "citta-e-bella")
        self.assertEqual(projects.slug("???"), "progetto")
        self.assertEqual(projects.name_from_prompt("uno due tre", 2), "uno due...")


if __name__ == "__main__":
    unittest.main()
