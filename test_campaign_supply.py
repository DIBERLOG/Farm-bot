import unittest
from unittest.mock import Mock
from campaign_supply import attempts, collect
from bot import Paused


class SupplyChecks(unittest.TestCase):
    def test_remaining_count_is_required(self):
        self.assertEqual(attempts('попыток за день: 0'), 0)
        self.assertEqual(attempts('попыток за день: 2'), 2)
        self.assertIsNone(attempts('до обновления: 12:34'))

    def test_exhausted_limit_never_purchases(self):
        bot = Mock(); bot.has.return_value = False
        bot.text.return_value = 'попыток за день: 0'
        collect(bot)
        bot.click.assert_not_called()
        bot.main.assert_called_once()

    def test_paid_action_requires_confirmed_decrement(self):
        bot = Mock(); bot.has.return_value = False
        bot.text.side_effect = ['попыток за день: 2', 'попыток за день: 2']
        bot.detail.return_value = '50'
        with self.assertRaisesRegex(Paused, 'уменьшение остатка'):
            collect(bot)
        bot.click.assert_called_once_with('забрать', (750, 690, 1170, 820))

    def test_paid_success_drains_remaining_attempts_without_extra_purchase(self):
        bot = Mock(); bot.has.return_value = False
        bot.text.side_effect = ['попыток за день: 2', 'попыток за день: 1',
                                'попыток за день: 1', 'попыток за день: 0', 'попыток за день: 0']
        bot.detail.side_effect = ['50', '100']
        collect(bot)
        self.assertEqual(bot.click.call_count, 2)
        self.assertEqual(bot.confirm_rewards.call_count, 2)
        bot.main.assert_called_once()

    def test_unknown_gold_price_does_not_purchase(self):
        bot = Mock(); bot.has.return_value = False
        bot.text.return_value = 'попыток за день: 2'
        bot.detail.return_value = '50?' 
        with self.assertRaisesRegex(Paused, 'стоимость'):
            collect(bot)
        bot.click.assert_not_called()
