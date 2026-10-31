import unittest
from unittest.mock import Mock, patch
from army import refill, join_groups, load_groups, save_groups
from bot import Paused
import numpy as np
import tempfile
from pathlib import Path


class ArmyChecks(unittest.TestCase):
    def test_group_option_persists_both_values_and_rejects_non_boolean(self):
        with tempfile.TemporaryDirectory() as directory, patch('bot.ROOT', Path(directory)):
            self.assertFalse(load_groups())
            save_groups(True)
            self.assertTrue(load_groups())
            save_groups(False)
            self.assertFalse(load_groups())
            with self.assertRaises(ValueError):
                save_groups('false')

    def test_full_groups_are_not_joined_and_map_is_restored(self):
        bot = Mock()
        bot.text.side_effect = ['сформирована: 11/11', 'сформирована: 14/14']
        join_groups(bot)
        self.assertEqual(bot.tap.call_count, 4)
        bot.log.assert_called_once_with('Группы армий: свободных мест с доступной кнопкой вступления нет')

    def test_available_group_requires_confirmation_after_join(self):
        bot = Mock()
        bot.text.return_value = 'сформирована: 10/11'
        bot.frame = np.full((1080,1920,3), (210,150,100), dtype=np.uint8)
        bot.has.return_value = False
        with self.assertRaisesRegex(Paused, 'результат требует проверки'):
            join_groups(bot)
        bot.tap.assert_any_call(1505, 378)
        bot.log.assert_not_called()

    def bot(self, button=False):
        bot = Mock()
        bot.has.side_effect = lambda name, region=None: name in ('наземные войска', 'казарма') or (button and name == 'пополнить')
        bot.text.return_value = 'казарма: 84/87'
        bot.optional_template.return_value = None
        return bot

    def test_prepare_button_is_a_valid_replenishment_action(self):
        bot = self.bot()
        bot.has.side_effect = lambda name, region=None: name in ('наземные войска', 'казарма', 'подготовить')
        bot.text.side_effect = ['казарма: 0/81', 'казарма: 1/81'] + ['казарма: 81/81'] * 4
        refill(bot)
        bot.click.assert_any_call('подготовить', (1500, 140, 1880, 265))
        bot.log.assert_any_call('Казарма №1: пополнение подтверждено 0 → 1')

    def test_prepare_template_handles_truncated_ocr(self):
        bot = self.bot()
        bot.text.side_effect = ['казарма: 0/81', 'казарма: 1/81'] + ['казарма: 81/81'] * 4
        bot.optional_template.return_value = (1762, 210)
        refill(bot)
        bot.tap.assert_any_call(1762, 210)

    def test_free_personnel_spaces_without_button_do_not_trigger_refill(self):
        bot = self.bot()
        refill(bot)
        bot.click.assert_called_once_with('наземные войска', (870, 10, 1180, 100))
        bot.tap.assert_called_once_with(1855, 50)

    def test_full_barracks_never_click_even_if_button_seen(self):
        bot = self.bot(True)
        bot.text.return_value = 'казарма: 81/81'
        refill(bot)
        bot.click.assert_called_once_with('наземные войска', (870, 10, 1180, 100))

    def test_refill_requires_button_and_checks_result(self):
        bot = self.bot(True)
        bot.text.side_effect = ['казарма: 78/87', 'казарма: 84/87'] + ['казарма: 81/81'] * 4
        refill(bot)
        bot.click.assert_any_call('пополнить', (1500, 140, 1880, 265))
        bot.log.assert_any_call('Казарма №1: пополнение подтверждено 78 → 84')

    def test_unknown_count_does_not_click(self):
        bot = self.bot(True)
        bot.text.return_value = bot.detail.return_value = ''
        with self.assertRaises(Paused):
            refill(bot)
        bot.click.assert_called_once_with('наземные войска', (870, 10, 1180, 100))
