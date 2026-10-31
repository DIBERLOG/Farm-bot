"""UI contract checks. No game input or persistent settings changes."""
import tkinter as tk
import unittest
from unittest.mock import Mock, patch

from app import App
from plans import PRESETS
from widgets import Button
from production import DEFAULT


class PanelChecks(unittest.TestCase):
    def test_ordered_manufacturing_replaces_fixed_daily_boards(self):
        bot = Mock()
        with patch('bot.Bot', return_value=bot):
            self.app.run('cycle', 'Ферма', False, list(next(iter(PRESETS.values()))), DEFAULT)
        bot.daily_actions.assert_called_once_with(send_officers=True, skip_materials=True)
        bot.production.assert_called_once_with(DEFAULT)
        self.app.poll()

    @classmethod
    def setUpClass(cls):
        cls.root = tk.Tk()
        cls.root.withdraw()
        cls.app = App(cls.root)
        cls.production_save_patch = patch('production_panel.save_config')
        cls.production_save_patch.start()
        cls.save_patch = patch('app.save_plan')
        cls.saved = cls.save_patch.start()
        cls.log_patch = patch.object(cls.app, 'append')
        cls.log_patch.start()

    @classmethod
    def tearDownClass(cls):
        cls.save_patch.stop()
        cls.production_save_patch.stop()
        cls.log_patch.stop()
        cls.root.destroy()

    def test_only_current_page_is_mapped(self):
        for name in self.app.pages:
            self.app.show_page(name)
            self.assertEqual([key for key, page in self.app.pages.items() if page.winfo_manager()], [name])

    def test_preset_and_custom_scheme_preserve_all_five_slots(self):
        app = self.app
        name = next(iter(PRESETS))
        app.preset.set(name)
        app.apply_preset()
        self.assertEqual([value.get() for value in app.plan], PRESETS[name])
        self.assertEqual(app.stat_counts['Ферма'].get(), '2')
        app.plan[0].set('Не отправлять')
        app.customize()
        self.assertEqual(app.preset.get(), 'Своя схема')
        self.assertEqual(len(self.saved.call_args.args[1]), 5)
        self.assertEqual(self.saved.call_args.args[1][0], 'Не отправлять')
        app.preset.set(name)
        app.apply_preset()

    def test_resource_selector_only_appears_for_single_resource_search(self):
        app = self.app
        for name, task in app.tasks.items():
            app.mode.set(name)
            app.update_mode()
            self.assertEqual(bool(app.resource_frame.winfo_manager()), task == 'search_resources')
            self.assertEqual(str(app.resource_box.cget('state')), 'readonly' if task == 'search_resources' else 'disabled')

    def test_failed_worker_can_be_retried_and_controls_unlock(self):
        app = self.app
        app.mode.set(next(name for name, task in app.tasks.items() if task == 'inspect'))
        app.repeat.set(False)
        failure = Mock()
        failure.connect.side_effect = RuntimeError('Нет подключения')
        success = Mock()
        success.text.return_value = 'Экран распознан'
        with patch('bot.Bot', side_effect=[failure, success]), patch('app.winsound.MessageBeep'):
            app.start()
            app.worker.join(timeout=3)
            self.assertFalse(app.worker.is_alive())
            app.poll()
            self.assertTrue(app.status.get().startswith('ПАУЗА'))
            self.assertEqual(str(app.start_button.cget('state')), 'normal')
            self.assertTrue(all(str(control.cget('state')) == 'readonly' for control in app.plan_controls))
            app.start()
            app.worker.join(timeout=3)
            app.poll()
            self.assertEqual(app.status.get(), 'Проход завершён')
            failure.close.assert_called_once()
            success.close.assert_called_once()

    def test_disabled_primary_button_does_not_invoke_action(self):
        command = Mock()
        button = Button(self.root, 'Проверка', command)
        button.configure(state='disabled')
        button.invoke()
        command.assert_not_called()
        button.configure(state='normal')
        button.invoke()
        command.assert_called_once()
        button.destroy()

    def test_missing_backend_does_not_leave_controls_locked(self):
        app = self.app
        app.mode.set(next(name for name, task in app.tasks.items() if task == 'inspect'))
        app.repeat.set(False)
        with patch.dict('sys.modules', {'bot': None}), patch('app.winsound.MessageBeep'):
            app.start()
            app.worker.join(timeout=3)
            app.poll()
        self.assertTrue(app.status.get().startswith('ПАУЗА'))
        self.assertEqual(str(app.start_button.cget('state')), 'normal')


if __name__ == '__main__':
    unittest.main()
