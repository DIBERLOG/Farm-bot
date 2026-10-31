import unittest
from unittest.mock import Mock

from research_center import upgrade_header, tree_points, start_selected, run, cost_number
import numpy as np


class ResearchChecks(unittest.TestCase):
    def test_individual_costs_read_grouped_digits_and_cyrillic_ocr(self):
        self.assertEqual(cost_number('з 600'), 3600)
        self.assertEqual(cost_number('4 800'), 4800)
        self.assertEqual(cost_number('1,2м'), 1200000)
        with self.assertRaises(Exception):
            cost_number('зздм')

    def test_stock_icon_is_not_mistaken_for_insufficient_funds(self):
        bot = Mock()
        bot.frame = np.full((1080,1920,3), 200, dtype=np.uint8)
        bot.text.side_effect = ['Технология ур. 2 » 3', '4800 3600 6000', '«*зздм 4 57,8m\nе 45m']
        bot.optional_template.return_value = (1205,942)
        bot.has.side_effect = lambda text, region=None: text in ('помощь','технология')
        self.assertTrue(start_selected(bot))
        bot.tap.assert_called_once_with(1205,942)

    def test_claiming_finished_job_continues_from_categories(self):
        bot = Mock()
        bot.lines = []
        bot.has.side_effect = lambda phrase, region=None: phrase in ('техн.', 'получить', 'готово')
        run(bot)
        bot.click.assert_called_once_with('получить', (700, 270, 930, 390))
        bot.template.assert_not_called()
        bot.log.assert_any_call('Завершённое личное исследование получено')

    def test_only_single_next_level_is_accepted(self):
        self.assertEqual(upgrade_header('Механическое проектирование ур. 1 »»2 i'),
                         ('механическое проектирование', 1, 2))
        for text in ('Макс.', 'Механическое проектирование ур. 1', 'Технология ур. 1 » 3'):
            self.assertIsNone(upgrade_header(text))

    def test_wrapped_labels_are_grouped_and_header_is_ignored(self):
        def row(text, x, y):
            return {'text':text,'words':[{'x':x,'y':y,'width':120,'height':25}]}
        self.assertEqual(tree_points([row('ИНДУСТРИЯ',200,20), row('МЕХАНИЧЕСКОЕ',340,680),
                                      row('ПРОЕКТИРОВАНИЕ',330,710), row('КРАНЫ',950,590)]),
                         [(400,595),(1010,505)])

    def test_missing_ordinary_button_never_spends(self):
        bot = Mock()
        bot.text.return_value = 'Технология ур. 1 » 2'
        bot.has.return_value = False
        bot.optional_template.return_value = None
        self.assertFalse(start_selected(bot))
        bot.tap.assert_not_called()

    def test_insufficient_resources_do_not_start_research(self):
        bot = Mock()
        bot.text.side_effect = ['Технология ур. 1 » 2', '3200 2400 4000', '100 5000 5000']
        bot.has.return_value = False
        bot.optional_template.return_value = (1205, 942)
        self.assertFalse(start_selected(bot))
        bot.tap.assert_not_called()

    def test_start_is_confirmed_by_help_or_speedup_and_matching_title(self):
        for button in ('помощь', 'ускорение'):
            bot = Mock()
            bot.text.side_effect = ['Технология ур. 1 » 2', '3200 2400 4000', '1m 1m 1m']
            bot.optional_template.return_value = (1205, 942)
            bot.has.side_effect = lambda text, region=None: text in (button, 'технология')
            self.assertTrue(start_selected(bot))
            bot.tap.assert_called_once_with(1205, 942)

    def test_active_queue_can_show_timer_instead_of_technology_name(self):
        bot = Mock()
        bot.text.side_effect = ['Краны ур. 1 » 2', '3200 2400 4000', '1m 1m 1m', '1 ч. 3 мин.']
        bot.optional_template.return_value = (1205, 942)
        bot.has.side_effect = lambda text, region=None: text == 'помощь'
        self.assertTrue(start_selected(bot))
        bot.tap.assert_called_once_with(1205, 942)
