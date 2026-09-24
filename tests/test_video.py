# -*- coding: utf-8 -*-
"""Misure dei video: Wan vuole lati multipli di 32 e 4k+1 fotogrammi."""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from imagecreator.core import config, presets  # noqa: E402


class TestVideo(unittest.TestCase):
    def test_lati_multipli_di_32(self):
        for aspect in config.ASPECT_RATIOS:
            for quality in config.VIDEO_QUALITY:
                w, h = config.video_resolution(aspect, quality)
                self.assertEqual((w % 32, h % 32), (0, 0), (aspect, quality))

    def test_misure_misurate_su_12_gb(self):
        vero = config.detect_gpu
        try:
            config.detect_gpu = lambda: {"vram_gb": 12.0}
            self.assertEqual(config.video_resolution("16:9", "draft"), (832, 480))
            self.assertEqual(config.video_resolution("16:9", "standard"), (960, 544))
            self.assertEqual(config.video_resolution("16:9", "high"), (960, 544))
            config.detect_gpu = lambda: {"vram_gb": 24.0}
            self.assertEqual(config.video_resolution("16:9", "high"), (1280, 704))
            self.assertEqual(config.video_resolution("9:16", "high"), (704, 1280))
        finally:
            config.detect_gpu = vero

    def test_fotogrammi_4k_piu_1(self):
        for secondi in (1, 1.5, 2, 3, 4, 5):
            n = config.video_frames(secondi)
            self.assertEqual((n - 1) % 4, 0, secondi)
            self.assertLessEqual(abs(n - secondi * config.VIDEO_FPS), 4)
        self.assertEqual(config.video_frames(5), 121)

    def test_segmenti_oltre_5_secondi(self):
        self.assertEqual(config.video_segments(config.video_frames(5)), 1)
        self.assertEqual(config.video_segments(config.video_frames(10)), 2)
        self.assertEqual(config.video_segments(config.video_frames(15)), 3)
        self.assertEqual(config.video_segments(config.video_frames(20)), 4)

    def test_esempi_video(self):
        video = [p for p in presets.load() if p.kind == "video"]
        self.assertGreaterEqual(len(video), 4)
        self.assertTrue(any(p.refs == 1 for p in video), "serve un esempio foto->video")
        self.assertIn("Video", presets.grouped(video))


if __name__ == "__main__":
    unittest.main()
