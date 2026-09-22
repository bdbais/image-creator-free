# -*- coding: utf-8 -*-
"""Test della parte che non richiede ne' GPU ne' modello."""
import json
import os
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "worker"))

from imagecreator.core import config, presets  # noqa: E402


class TestConfig(unittest.TestCase):
    def test_risoluzioni_multiple_di_64(self):
        for aspect in config.ASPECT_RATIOS:
            for quality in config.QUALITY:
                w, h = config.resolution_for(aspect, quality)
                self.assertEqual(w % 64, 0, "%s/%s larghezza %d" % (aspect, quality, w))
                self.assertEqual(h % 64, 0, "%s/%s altezza %d" % (aspect, quality, h))
                self.assertGreaterEqual(min(w, h), 512)

    def test_proporzioni_conservate(self):
        for aspect, (base_w, base_h) in config.ASPECT_RATIOS.items():
            w, h = config.resolution_for(aspect, "standard")
            self.assertAlmostEqual(w / h, base_w / base_h, delta=0.06, msg=aspect)

    def test_alta_qualita_come_la_model_card(self):
        self.assertEqual(config.resolution_for("1:1", "high"), (2048, 2048))
        self.assertEqual(config.QUALITY["high"]["steps"], 40)

    def test_modalita_memoria_suggerita(self):
        # Il modello pesa 33 GB in bf16 e il suo modulo piu' grande 17,5:
        # una scheda da 12 o 16 GB deve finire in offload sequenziale.
        self.assertEqual(config.suggest_memory_mode(48), "high")
        self.assertEqual(config.suggest_memory_mode(24), "balanced")
        self.assertEqual(config.suggest_memory_mode(16), "low")
        self.assertEqual(config.suggest_memory_mode(12), "low")
        self.assertEqual(config.suggest_memory_mode(8), "low")

    def test_impostazioni_salvate_e_rilette(self):
        settings = config.Settings.load()
        settings.aspect = "16:9"
        settings.save()
        self.assertEqual(config.Settings.load().aspect, "16:9")

    def test_env_worker_non_espone_telemetria(self):
        settings = config.Settings.load()
        settings.models_dir = str(ROOT)
        env = settings.env_for_worker()
        self.assertEqual(env["HF_HOME"], str(ROOT))
        self.assertEqual(env["HF_HUB_DISABLE_TELEMETRY"], "1")


class TestPresets(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.items = presets.load()

    def test_esempi_caricati(self):
        self.assertGreaterEqual(len(self.items), 30)

    def test_ogni_esempio_ha_prompt_e_titolo(self):
        for preset in self.items:
            self.assertTrue(preset.prompt.strip(), preset.id)
            self.assertTrue(preset.title_it.strip(), preset.id)
            self.assertIn(preset.mode, ("t2i", "edit"))
            self.assertIn(preset.aspect, config.ASPECT_RATIOS)

    def test_esempi_con_riferimenti_sono_di_modifica(self):
        for preset in self.items:
            if preset.refs:
                self.assertEqual(preset.mode, "edit", preset.id)
                self.assertLessEqual(preset.refs, 10, preset.id)

    def test_esempi_della_model_card_presenti(self):
        sources = {p.source for p in self.items}
        self.assertIn("model-card", sources)
        self.assertIn("demo-space", sources)
        ids = {p.id for p in self.items}
        self.assertIn("neon-shop-sign", ids)
        self.assertIn("transparent-sticker-rgba", ids)

    def test_gruppi(self):
        groups = presets.grouped(self.items)
        self.assertIn("Da testo", groups)
        self.assertIn("Modifica di immagini", groups)
        self.assertTrue(any(p.is_rgba for p in self.items))


class TestWorkerPuro(unittest.TestCase):
    """Il worker si importa senza torch: gli import pesanti stanno nelle funzioni."""

    @classmethod
    def setUpClass(cls):
        import qwen_worker
        cls.worker = qwen_worker

    def test_emit_produce_una_riga_json(self):
        import io
        buffer = io.StringIO()
        original = sys.stdout
        sys.stdout = buffer
        try:
            self.worker.emit("progress", id="x", step=3, total=10)
        finally:
            sys.stdout = original
        payload = json.loads(buffer.getvalue().strip())
        self.assertEqual(payload["ev"], "progress")
        self.assertEqual(payload["step"], 3)

    def test_filter_kwargs_toglie_parametri_non_supportati(self):
        class FintaPipeline:
            def __call__(self, prompt, num_inference_steps=1, generator=None):
                return None

        filtered = self.worker._filter_kwargs(
            FintaPipeline(), {"prompt": "a", "num_inference_steps": 2, "true_cfg_scale": 4.0})
        self.assertIn("prompt", filtered)
        self.assertNotIn("true_cfg_scale", filtered)

    def test_filter_kwargs_lascia_passare_var_keyword(self):
        class FintaPipeline:
            def __call__(self, **kwargs):
                return None

        payload = {"prompt": "a", "qualunque": 1}
        self.assertEqual(self.worker._filter_kwargs(FintaPipeline(), payload), payload)

    def test_callback_solleva_quando_annullato(self):
        callback = self.worker._make_callback("job", 0, 1, 10)
        self.worker._cancel.set()
        try:
            with self.assertRaises(self.worker.Cancelled):
                callback(None, 1, None, {})
        finally:
            self.worker._cancel.clear()

    def test_modalita_memoria_automatica(self):
        engine = self.worker.Engine()
        engine.vram_gb = 48
        self.assertEqual(engine._resolve_mode("auto"), "high")
        engine.vram_gb = 24
        self.assertEqual(engine._resolve_mode("auto"), "balanced")
        engine.vram_gb = 12
        self.assertEqual(engine._resolve_mode("auto"), "low")
        self.assertEqual(engine._resolve_mode("high"), "high")


if __name__ == "__main__":
    unittest.main()
