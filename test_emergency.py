import json
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import emergency as e


class EmergencyChecks(unittest.TestCase):
    def test_unknown_nested_panel_returns_using_back_and_confirms_map(self):
        bot=Mock(); bot.text.return_value='неизвестная игровая панель'
        bot.stop=threading.Event(); bot.has.return_value=False
        bot.rewards_open.return_value=False; bot.help_open.return_value=False
        bot.optional_template.return_value=None
        bot.main.side_effect=[ValueError('panel'),ValueError('panel'),None]
        with patch.object(e,'attack_warning',return_value=False):
            self.assertTrue(e.local_recover(bot))
        self.assertEqual(bot.back.call_count,2)
        self.assertEqual(bot.main.call_count,3)

    def test_unknown_panel_back_attempts_are_bounded(self):
        bot=Mock(); bot.text.return_value='панель'; bot.stop=threading.Event()
        bot.has.return_value=False; bot.rewards_open.return_value=False
        bot.help_open.return_value=False; bot.optional_template.return_value=None
        bot.main.side_effect=ValueError('panel')
        with patch.object(e,'attack_warning',return_value=False):
            self.assertFalse(e.local_recover(bot))
        self.assertEqual(bot.back.call_count,12)

    def test_radar_recovery_uses_image_when_ocr_misses_header(self):
        bot = Mock(); bot.text.return_value=""; bot.stop = threading.Event()
        bot.has.return_value = False
        bot.rewards_open.return_value = False
        bot.help_open.return_value = False
        bot.optional_template.return_value = (270, 45)
        with patch.object(e, 'attack_warning', return_value=False):
            self.assertTrue(e.local_recover(bot))
        bot.back.assert_called_once()
        bot.main.assert_called_once()

    def test_destination_can_be_saved_without_an_api_key(self):
        with tempfile.TemporaryDirectory() as folder:
            with patch.object(e,'CONFIG',Path(folder)/'settings.json'), patch.object(e,'KEY',Path(folder)/'key'):
                e.save(False, x=12345, y=54321, destination_set=True)
                result = e.settings()
                self.assertEqual((result['x'],result['y']), (12345,54321))
                self.assertTrue(result['destination_set'])
                self.assertFalse(result['enabled'])
                with self.assertRaises(ValueError):
                    e.save(False,x=-1)

    def test_key_is_encrypted_and_round_trips_for_current_windows_user(self):
        secret = b'test-only-not-a-real-api-key'
        encrypted = e.protect(secret)
        self.assertNotIn(secret, encrypted)
        self.assertEqual(e.protect(encrypted, decrypt=True), secret)

    def test_disabled_and_stop_do_not_contact_api(self):
        with patch.object(e, 'settings', return_value={'enabled':False}), patch('urllib.request.build_opener') as network:
            self.assertEqual(e.advise('error','screen',threading.Event())[0], 'pause')
            network.assert_not_called()
        stopped = threading.Event(); stopped.set()
        with patch('urllib.request.build_opener') as network:
            self.assertEqual(e.advise('error','screen',stopped)[0], 'pause')
            network.assert_not_called()

    def test_output_is_not_arbitrary_code_or_coordinates(self):
        for action in ('tap', 'shell', 'buy', 'solve_captcha'):
            payload = {'choices':[{'finish_reason':'stop','message':{'content':json.dumps({'action':action,'reason':'x'})}}]}
            with self.assertRaises(ValueError):
                e.parse_answer(payload)

    def test_repeated_calls_have_no_hourly_quota(self):
        response = Mock()
        response.__enter__ = Mock(return_value=response)
        response.__exit__ = Mock(return_value=False)
        response.read.return_value = json.dumps({'choices':[{'finish_reason':'stop','message':{'content':json.dumps({'action':'resume_if_map','reason':'ok'})}}]}).encode()
        with patch.object(e,'settings',return_value={'enabled':True}), patch.dict('os.environ',{'DEEPSEEK_API_KEY':'test-only'}), patch('urllib.request.build_opener') as network:
            network.return_value.open.return_value=response
            for _ in range(5):
                self.assertEqual(e.advise('error','screen',threading.Event())[0],'resume_if_map')
            self.assertEqual(network.return_value.open.call_count,5)

    def test_model_cannot_teleport_or_resume_unknown_screen(self):
        bot = Mock(); bot.text.return_value=""; bot.stop = threading.Event(); bot.watch_attack = True
        bot.text.return_value = 'обычный экран'
        bot.rewards_open.return_value = False
        bot.help_open.return_value = False
        bot.has.return_value = False
        bot.main.side_effect = ValueError('not a map')
        with patch.object(e,'settings',return_value={'enabled':True}), patch.object(e,'advise',return_value=('teleport','test')):
            self.assertFalse(e.recover(bot,ValueError('error')))
        bot.tap.assert_not_called()
        self.assertTrue(bot.watch_attack)

    def test_known_menu_recovery_requires_map_confirmation(self):
        bot = Mock(); bot.text.return_value=""; bot.stop = threading.Event(); bot.watch_attack = True
        bot.has.side_effect=lambda text,region=None: text=='миссии'
        bot.text.return_value = 'миссии'; bot.rewards_open.return_value=False; bot.help_open.return_value=False
        with patch.object(e,'settings',return_value={'enabled':True}), patch.object(e,'advise',return_value=('close_known','test')):
            self.assertTrue(e.recover(bot,ValueError('error')))
        bot.mission_screen.assert_called_once()
        bot.tap.assert_called_once_with(1814,108)
        bot.main.assert_called_once()

    def test_exit_dialog_is_cancelled_before_map_confirmation(self):
        bot = Mock(); bot.text.return_value=""; bot.stop = threading.Event()
        bot.has.side_effect = lambda text, region=None: text in ('выйти из игры', 'отмена')
        bot.rewards_open.return_value = False
        bot.help_open.return_value = False
        bot.optional_template.return_value = None
        with patch.object(e, 'attack_warning', return_value=False):
            self.assertTrue(e.local_recover(bot))
        bot.click.assert_called_once_with('отмена')
        bot.main.assert_called_once()

    def test_nested_research_menus_use_observed_back_button(self):
        bot=Mock(); bot.text.return_value=""; bot.stop=threading.Event()
        bot.has.side_effect=lambda text,region=None: text=='исследования альянса'
        bot.rewards_open.return_value=False
        bot.help_open.return_value=False
        bot.optional_template.return_value=None
        bot.main.side_effect=[ValueError('menu'),ValueError('menu'),None]
        with patch.object(e,'attack_warning',return_value=False):
            self.assertTrue(e.local_recover(bot))
        self.assertEqual(bot.tap.call_count,2)
        bot.tap.assert_called_with(120,45)

    def test_unit_upgrade_card_returns_with_header_back_button(self):
        bot=Mock(); bot.text.return_value=""; bot.stop=threading.Event()
        bot.has.side_effect=lambda text,region=None: text in ('улучшение','повысить','модифицировать')
        bot.rewards_open.return_value=False
        bot.help_open.return_value=False
        bot.optional_template.return_value=None
        bot.main.side_effect=[ValueError('unit card'),None]
        with patch.object(e,'attack_warning',return_value=False):
            self.assertTrue(e.local_recover(bot))
        bot.tap.assert_called_once_with(120,45)

    def test_officer_xp_popup_and_list_are_both_closed(self):
        bot=Mock(); bot.text.return_value=""; bot.stop=threading.Event()
        state={'stage':0}
        def main():
            if state['stage']<2: raise ValueError('officer menu')
        bot.main.side_effect=main
        bot.tap.side_effect=lambda *args: state.update(stage=state['stage']+1)
        bot.has.side_effect=lambda text,region=None: text in (
            ('повышение офицера','базовый опыт офицера') if state['stage']==0
            else ('офицеры','навыки офицера'))
        bot.rewards_open.return_value=False; bot.help_open.return_value=False
        bot.optional_template.return_value=None
        with patch.object(e,'attack_warning',return_value=False):
            self.assertTrue(e.local_recover(bot))
        self.assertEqual([c.args for c in bot.tap.call_args_list],[(1536,110),(120,45)])
