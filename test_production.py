"""Order, persistence and interruption checks; no Android input."""
import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

import numpy as np
from bot import Paused
from production import DEFAULT, validate, load_config, save_config, next_batch, fill_queues, select_material, UncertainAddition


class ProductionChecks(unittest.TestCase):
    def setUp(self):
        tracker=patch('telemetry.record')
        tracker.start(); self.addCleanup(tracker.stop)
        completed=patch('telemetry.completed_queue')
        completed.start(); self.addCleanup(completed.stop)
    def test_factory_collects_ready_first_queue_before_opening(self):
        from production import enter_factory
        bot = Mock()
        bot.has.side_effect = lambda phrase, region=None: phrase == 'агрегатный завод' or (phrase == 'получить' and region == (725, 280, 910, 380))
        enter_factory(bot)
        self.assertEqual([c.args[0] for c in bot.click.call_args_list], ['получить', 'показать'])

    def test_empty_overview_opens_production_not_show(self):
        from production import enter_factory
        bot = Mock()
        bot.has.side_effect = lambda phrase, region=None: phrase in ('агрегатный завод', 'производство')
        enter_factory(bot)
        bot.click.assert_called_once_with('производство', (725, 280, 910, 380))
        bot.require.assert_called_with('агрегатный завод', 'мастерская')

    def recipe(self):
        config = copy.deepcopy(DEFAULT)
        config.update(limit=3, repeat=False, workshops=[[{'material': 'Цемент', 'count': 2},
                                                       {'material': 'Асфальт', 'count': 1}], [], [], []])
        return config

    def test_quantities_order_wrap_and_nonrepeating_end(self):
        recipe = self.recipe()['workshops'][0]
        self.assertEqual(next_batch(recipe, [0, 0], False, 1), ('Цемент', 1, [0, 1]))
        self.assertEqual(next_batch(recipe, [0, 1], False, 4), ('Цемент', 1, [1, 0]))
        self.assertEqual(next_batch(recipe, [1, 0], True, 4), ('Асфальт', 1, [2, 0]))
        self.assertIsNone(next_batch(recipe, [2, 0], False, 4))
        self.assertEqual(next_batch(recipe, [2, 0], True, 4), ('Цемент', 2, [1, 0]))
        self.assertIsNone(next_batch(recipe, [0, 0], True, 0))
        self.assertEqual(next_batch([{'material': 'Бетон', 'count': 1}], [0, 0], True, 33),
                         ('Бетон', 5, [0, 0]))
        with self.assertRaises(ValueError):
            next_batch(recipe, [0, 10], True, 4)

    def test_configuration_rejects_invalid_workshops_prices_and_counts(self):
        config = self.recipe()
        for key, value in [('limit', 0), ('limit', 34), ('enabled', 'да'), ('workshops', [[]])]:
            with self.assertRaises(ValueError):
                validate({**config, key: value})
        for count in (True, 0, -1, 1000, 2.5):
            bad = self.recipe()
            bad['workshops'][0][0]['count'] = count
            with self.assertRaises(ValueError):
                validate(bad)
        config['workshops'][0][0]['material'] = 'Покупка за золото'
        with self.assertRaises(ValueError):
            validate(config)

    def test_configuration_roundtrip_preserves_all_four_orders(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'production.json'
            self.assertEqual(load_config(path), DEFAULT)
            candidate = self.recipe()
            save_config(path, candidate)
            self.assertEqual(load_config(path), candidate)
            self.assertFalse(path.with_suffix('.tmp').exists())

    def test_selected_material_is_not_clicked_again_and_unknown_title_gets_no_input(self):
        bot = Mock()
        bot.detail.return_value = 'цемент'
        select_material(bot, 'Цемент')
        bot.command.assert_not_called()
        bot.detail.side_effect = ['цемент', 'асфальт']
        select_material(bot, 'Асфальт')
        self.assertEqual(bot.tap.call_count, 1)
        bot.tap.assert_called_once_with(1690, 320)
        bot.tap.reset_mock()
        bot.detail.side_effect = None
        bot.detail.return_value = 'неизвестный материал'
        with self.assertRaises(Paused):
            select_material(bot, 'Асфальт')
        bot.tap.assert_not_called()

    def bot(self):
        bot = Mock()
        bot.frame = np.zeros((1080, 1920, 3), np.uint8)
        return bot

    def test_single_repeating_material_resumes_pending_and_fills_free_slot(self):
        bot=self.bot()
        config=self.recipe()
        config['repeat']=True
        config['workshops']=[[{'material':'Цемент','count':1}],[],[],[]]
        config['limit']=33
        signature=json.dumps([config['workshops'][0],True],ensure_ascii=False,sort_keys=True)
        with tempfile.TemporaryDirectory() as folder,patch('production.enter_factory'),patch('production.select_material'):
            path=Path(folder)/'state.json'
            path.write_text(json.dumps({'version':1,'workshops':{'1':{'signature':signature,'position':[0,0],'pending':True}}}),encoding='utf-8')
            with patch('daily_tasks.factory_queue',side_effect=[(32,33),(32,33),(32,33),(33,33),(33,33)]):
                fill_queues(bot,config,path)
            bot.command.assert_called_once()
            self.assertFalse(json.loads(path.read_text(encoding='utf-8'))['workshops']['1']['pending'])

    def test_enqueue_order_and_saved_cursor_prevent_duplicate_recipe(self):
        bot = self.bot()
        with tempfile.TemporaryDirectory() as folder, patch('production.enter_factory'), patch('production.select_material') as selected:
            path = Path(folder) / 'state.json'
            with patch('daily_tasks.factory_queue', side_effect=[(0, 33), (0, 33), (0, 33), (2, 33),
                                                                 (2, 33), (2, 33), (3, 33), (3, 33)]):
                fill_queues(bot, self.recipe(), path)
            self.assertEqual([call.args[1] for call in selected.call_args_list], ['Цемент', 'Асфальт'])
            state = json.loads(path.read_text(encoding='utf-8'))['workshops']['1']
            self.assertEqual(state['position'], [2, 0])
            self.assertFalse(state['pending'])
            self.assertEqual(bot.command.call_count, 3)
            bot.command.reset_mock()
            with patch('daily_tasks.factory_queue', return_value=(1, 33)):
                fill_queues(bot, self.recipe(), path)
            bot.command.assert_not_called()

    def test_uncertain_addition_blocks_retry_until_queue_empties(self):
        bot = self.bot()
        with tempfile.TemporaryDirectory() as folder, patch('production.enter_factory'), patch('production.select_material'):
            path = Path(folder) / 'state.json'
            with patch('daily_tasks.factory_queue', side_effect=[(0, 33), (0, 33), (0, 33), (1, 33)]):
                with self.assertRaises(UncertainAddition):
                    fill_queues(bot, self.recipe(), path)
            self.assertTrue(json.loads(path.read_text(encoding='utf-8'))['workshops']['1']['pending'])
            bot.command.reset_mock()
            with patch('daily_tasks.factory_queue', return_value=(1, 33)):
                fill_queues(bot, self.recipe(), path)
            bot.command.assert_not_called()

    def test_material_selection_cannot_silently_consume_a_queue_slot(self):
        bot = self.bot()
        with tempfile.TemporaryDirectory() as folder, patch('production.enter_factory'), patch('production.select_material'):
            path = Path(folder) / 'state.json'
            with patch('daily_tasks.factory_queue', side_effect=[(0, 33), (0, 33), (1, 33)]):
                with self.assertRaises(UncertainAddition):
                    fill_queues(bot, self.recipe(), path)
            bot.command.assert_not_called()
            self.assertTrue(json.loads(path.read_text(encoding='utf-8'))['workshops']['1']['pending'])

    def test_full_or_disabled_queue_never_adds_anything(self):
        bot = self.bot()
        with tempfile.TemporaryDirectory() as folder, patch('production.enter_factory'), patch('daily_tasks.factory_queue', return_value=(33, 33)):
            fill_queues(bot, self.recipe(), Path(folder) / 'state.json')
        bot.command.assert_not_called()
        with patch('production.enter_factory') as enter:
            fill_queues(bot, {**self.recipe(), 'enabled': False})
        enter.assert_not_called()


class ProductionEditorChecks(unittest.TestCase):
    def setUp(self):
        import tkinter as tk
        from production_panel import ProductionPanel
        self.folder = tempfile.TemporaryDirectory()
        self.root = tk.Tk()
        self.root.withdraw()
        self.panel = ProductionPanel(self.root, Path(self.folder.name) / 'production.json')

    def tearDown(self):
        self.root.destroy()
        self.folder.cleanup()

    def test_editor_saves_reordered_quantities_for_each_workshop(self):
        panel = self.panel
        panel.material.set('Асфальт')
        panel.count.set('7')
        panel.add()
        panel.move(-1)
        self.assertEqual(panel.snapshot()['workshops'][0], [{'material': 'Асфальт', 'count': 7},
                                                           {'material': 'Цемент', 'count': 1}])
        panel.workshop.set('Мастерская 2')
        panel.switch_workshop()
        panel.count.set('3')
        panel.tree.selection_set('0')
        panel.material.set('Бетон')
        panel.edit()
        self.assertTrue(panel.save())
        self.assertEqual(load_config(panel.path)['workshops'][1], [{'material': 'Бетон', 'count': 3}])

    def test_failed_save_preserves_draft_and_running_controls_unlock(self):
        panel = self.panel
        panel.material.set('Доска')
        panel.count.set('5')
        panel.add()
        expected = panel.snapshot()
        with patch('production_panel.save_config', side_effect=OSError('Нет доступа')):
            self.assertFalse(panel.save())
        self.assertEqual(panel.snapshot(), expected)
        self.assertIn('Не сохранено', panel.message.get())
        panel.set_running(True)
        self.assertTrue(all(str(control.cget('state')) == 'disabled' for control, _ in panel.controls))
        panel.set_running(False)
        self.assertTrue(all(str(control.cget('state')) == state for control, state in panel.controls))

    def test_invalid_input_is_not_written(self):
        self.panel.limit.set('0')
        self.assertFalse(self.panel.save())
        self.assertFalse(self.panel.path.exists())


if __name__ == '__main__':
    unittest.main()
