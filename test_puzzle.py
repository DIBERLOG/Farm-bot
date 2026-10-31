"""Image matching and guarded CAPTCHA input; no connection to a game."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import cv2
import numpy as np

from bot import Bot, Paused, ROOT
from puzzle import analyze_frame, load_profile, match_piece


class PuzzleChecks(unittest.TestCase):
    def test_upstream_demo_matches_known_gap(self):
        folder = ROOT / 'third_party/puzzle_captcha_solver/demo'
        piece = cv2.imdecode(np.fromfile(folder / '1_slice.png', np.uint8), -1)
        background = cv2.imdecode(np.fromfile(folder / '1_bg.png', np.uint8), 1)
        result = match_piece(piece, background)
        self.assertEqual((result.x, result.y), (187, 32))
        self.assertGreater(result.margin, .08)

    def test_blank_and_ambiguous_images_are_rejected(self):
        with self.assertRaises(ValueError):
            match_piece(np.zeros((30, 30, 3), np.uint8), np.zeros((100, 100, 3), np.uint8))
        rng = np.random.default_rng(21)
        piece = rng.integers(0, 256, (40, 40, 3), np.uint8)
        background = np.zeros((100, 200, 3), np.uint8)
        background[20:60, 20:60] = piece
        background[20:60, 120:160] = piece
        with self.assertRaisesRegex(ValueError, 'Неуверенное'):
            match_piece(piece, background)

    def test_uncalibrated_and_out_of_bounds_profiles_are_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(ValueError, 'не настроен'):
                load_profile(Path(directory) / 'absent.json')
        frame = np.zeros((1080, 1920, 3), np.uint8)
        with self.assertRaisesRegex(ValueError, 'вне снимка'):
            analyze_frame(frame, {'background': [-1, 0, 300, 200]})

    def test_inspection_never_moves_slider_and_missing_profile_pauses(self):
        image = cv2.imencode('.png', np.zeros((1080, 1920, 3), np.uint8))[1].tobytes()
        words = [{'text': 'Перетащите ползунок', 'x': 10, 'y': 10, 'width': 200, 'height': 30}]
        bot = Bot(allow_captcha=False)
        bot.command = Mock(return_value=image)
        bot.read_ocr = Mock(return_value=[{'text': 'Перетащите ползунок', 'words': words}])
        with patch.object(Path, 'write_bytes'):
            bot.observe()
            self.assertEqual(bot.command.call_count, 1)
            bot.allow_captcha = True
            with patch('puzzle.load_profile', side_effect=ValueError('не настроен')):
                with self.assertRaises(Paused):
                    bot.observe()
        self.assertTrue(all('swipe' not in call.args for call in bot.command.call_args_list))


if __name__ == '__main__':
    unittest.main()
