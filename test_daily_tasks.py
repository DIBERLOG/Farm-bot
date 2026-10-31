"""Daily navigation and enqueue limits, using recorded game images only."""
import unittest
from unittest.mock import Mock, patch

from bot import Bot, Paused, ROOT, cv2, np
from daily_tasks import TASK_ICONS, produce_materials, inventory_cost, unit_level, upgrade_unit, task_point, task_remaining, defeat_raven, raven_target_ready, open_task
from daily_tasks import TASK_SOURCES, resource_amounts, building_materials, upgrade_selected_building, use_officer_xp, campaign_supply_tasks


class DailyChecks(unittest.TestCase):
    def test_officer_book_count_uses_wider_crop_when_ocr_adds_border(self):
        from daily_tasks import officer_xp_count
        bot=Mock(); bot.detail.side_effect=['','—322']
        self.assertEqual(officer_xp_count(bot),322)

    def test_daily_failure_does_not_skip_later_tasks_after_map_recovery(self):
        from daily_tasks import run_daily
        bot=Mock(); bot.stop.is_set.return_value=False
        with patch('daily_tasks.recruit_unit'),patch('daily_tasks.speedup_research'),patch('daily_tasks.upgrade_unit'),patch('daily_tasks.modify_unit'),patch('daily_tasks.use_officer_xp',side_effect=Paused('unreadable'),__name__='use_officer_xp'),patch('daily_tasks.campaign_supply_tasks') as supply,patch('daily_tasks.defeat_raven') as raven,patch('daily_tasks.assemble_daily_unit'),patch('emergency.local_recover',return_value=True):
            run_daily(bot,skip_materials=True)
            supply.assert_called_once_with(bot)
            raven.assert_called_once_with(bot)
            bot.mission_rewards.assert_called_once()
    def test_building_prices_preserve_separate_material_rows_and_fractional_millions(self):
        self.assertEqual(building_materials('191/116\n666/101\n7/66'), [(191, 116), (666, 101), (7, 66)])
        self.assertEqual(resource_amounts('1,62M\n1.94м\n1290к'), [1620000, 1940000, 1290000])
        for text in ('1,62M', '1,62M неизвестно 1,29M', '1,6Z 2M 3M'):
            with self.assertRaises(Paused):
                resource_amounts(text)

    def test_missing_building_materials_never_clicks_upgrade_or_purchase(self):
        bot = Mock()
        bot.text.return_value = 'ангар 2 ур. 15 »»16'
        bot.detail.return_value = '191/116\n666/101\n7/66'
        self.assertFalse(upgrade_selected_building(bot))
        bot.click.assert_not_called()
        bot.back.assert_called_once()

    def test_building_success_requires_actual_level_increase(self):
        bot = Mock()
        bot.text.return_value = 'ангар 3 ур. 14 »»15'
        bot.has.return_value = False
        bot.detail.side_effect = ['717/51\n640/44\n40/33', '1,35M\n1,62M\n1,08M',
                                  '22,5M\n54,7M\n36M', 'ангар 3 ур. 15']
        self.assertTrue(upgrade_selected_building(bot))
        bot.click.assert_called_once_with('улучшить', (1260, 920, 1700, 1040))
        bot.detail.side_effect = ['717/51\n640/44\n40/33', '1,35M\n1,62M\n1,08M',
                                  '22,5M\n54,7M\n36M', 'ангар 3 ур. 14']
        with self.assertRaises(Paused):
            upgrade_selected_building(bot)

    def test_officer_uses_only_remaining_basic_books_and_checks_each_decrement(self):
        bot = Mock()
        bot.optional_template.return_value = (310, 520)
        bot.detail.side_effect = ['273', '272', '272', '271']
        with patch('daily_tasks.open_task', return_value=2):
            use_officer_xp(bot)
        self.assertEqual(bot.click.call_count, 2)
        bot.click.assert_called_with('исп.', (1340, 380, 1540, 480))
        bot.detail.side_effect = ['273', '273']
        with patch('daily_tasks.open_task', return_value=1), self.assertRaises(Paused):
            use_officer_xp(bot)

    def test_quick_campaign_supply_never_accepts_paid_button(self):
        bot = Mock()
        bot.has.return_value = False
        with patch('daily_tasks.open_task', side_effect=[0, 1]):
            campaign_supply_tasks(bot)
        bot.click.assert_not_called()
        bot.confirm_rewards.assert_not_called()
        bot.has.return_value = True
        with patch('daily_tasks.open_task', side_effect=[0, 1]):
            campaign_supply_tasks(bot)
        bot.click.assert_called_once_with('бесплатно', (750, 690, 1170, 820))
        bot.confirm_rewards.assert_called_once()

    def test_regular_campaign_supply_is_collected_once_per_pass(self):
        bot = Mock()
        with patch('daily_tasks.open_task', side_effect=[3, 0]):
            campaign_supply_tasks(bot)
        bot.click.assert_called_once_with('получить', (750, 720, 1170, 845))

    def test_claimed_grey_card_does_not_open_even_when_template_matches(self):
        bot = Bot()
        bot.daily_screen = Mock()
        bot.frame = cv2.imdecode(np.fromfile(ROOT / 'daily-claimed-scroll.png', np.uint8), 1)
        self.assertIsNone(task_point(bot, TASK_ICONS['speedup'][0]))
        bot.frame = cv2.imdecode(np.fromfile(ROOT / 'daily-claim.png', np.uint8), 1)
        self.assertIsNotNone(task_point(bot, TASK_ICONS['speedup'][0]))

    def test_unreadable_counter_skips_action_and_returns_to_map(self):
        bot = Mock()
        bot.text.return_value = 'Ускорение (1 л)'
        bot.detail.return_value = 'Ускорение (1 л)'
        with patch('daily_tasks.task_point', return_value=(1381, 587)):
            self.assertIsNone(open_task(bot, 'speedup'))
        bot.click.assert_not_called()
        self.assertEqual([call.args for call in bot.tap.call_args_list][-2:], [(1410, 200), (1814, 108)])
        self.assertEqual(bot.main.call_count, 2)

    def test_finished_task_never_starts_more_production(self):
        bot = Mock()
        with patch('daily_tasks.open_task', return_value=0):
            produce_materials(bot)
        bot.tap.assert_not_called()
        bot.click.assert_not_called()

    def test_world_attack_requires_exact_level_one_npc_and_advantage(self):
        bot = Bot()
        bot.frame = cv2.imdecode(np.fromfile(ROOT / 'daily-raven-panel.png', np.uint8), 1)
        bot.has = Mock(return_value=True)
        self.assertTrue(raven_target_ready(bot))
        bot.has.return_value = False
        self.assertFalse(raven_target_ready(bot))
        bot.has.return_value = True
        bot.frame = cv2.imdecode(np.fromfile(ROOT / 'map.png', np.uint8), 1)
        self.assertFalse(raven_target_ready(bot))

    def test_raven_attack_stops_on_missing_progress_and_continues_after_confirmed_kill(self):
        bot = Mock()
        bot.template.return_value = (867, 728)
        with patch('daily_tasks.open_task', side_effect=[2, 2]), patch('daily_tasks.raven_target_ready', return_value=True):
            defeat_raven(bot)
        self.assertEqual(bot.tap.call_count, 2)
        bot.tap.reset_mock()
        with patch('daily_tasks.open_task', side_effect=[2, 1, 1, 0]), patch('daily_tasks.raven_target_ready', return_value=True):
            defeat_raven(bot)
        self.assertEqual(bot.tap.call_count, 4)
        bot.log.assert_any_call('Бой «Ворона» подтверждён заданием: осталось 1 → 0')

    def test_unknown_world_target_never_receives_an_attack(self):
        bot = Mock()
        with patch('daily_tasks.open_task', return_value=5), patch('daily_tasks.raven_target_ready', return_value=False):
            defeat_raven(bot)
        bot.template.assert_not_called()
        bot.tap.assert_any_call(1300, 600)

    def test_scrolled_task_uses_actual_label_position_and_scan_stops_at_end(self):
        bot = Mock()
        bot.frame = np.zeros((1080, 1920, 3), np.uint8)
        bot.optional_template.side_effect = [None, (1070, 690)]
        bot.observe.side_effect = lambda: setattr(bot, 'frame', np.full_like(bot.frame, 100))
        self.assertEqual(task_point(bot, TASK_ICONS['assemble'][0]), (1070, 690))
        self.assertEqual(bot.command.call_count, 1)
        bot.optional_template = Mock(return_value=None)
        bot.observe = Mock()
        bot.command.reset_mock()
        self.assertIsNone(task_point(bot, TASK_ICONS['assemble'][0]))
        self.assertEqual(bot.command.call_count, 1)

    def test_daily_counter_joins_split_digits_and_rejects_ambiguous_values(self):
        self.assertEqual(task_remaining('Задание (1 0 / 1 5)'), 5)
        self.assertEqual(task_remaining('(3/3)'), 0)
        for value in ('(1 в)', '(4/3)', '(0/100)', 'Нет счётчика'):
            self.assertIsNone(task_remaining(value))

    def test_inventory_prices_and_unit_levels_reject_unaffordable_or_unknown_values(self):
        self.assertEqual(inventory_cost('1 540/150', 200), (1540, 150))
        self.assertIsNone(inventory_cost('1 540/450', 200))
        self.assertIsNone(inventory_cost('100/150', 200))
        self.assertEqual(inventory_cost('0/150', 200, require_available=False), (0, 150))
        for text in ('1 540/1,5k', 'Неизвестно'):
            with self.assertRaises(Paused):
                inventory_cost(text, 200)
        self.assertEqual(unit_level('Уровень 2/80'), (2, 80))
        for text in ('Уровень 81/80', 'Уровень ?/80'):
            with self.assertRaises(Paused):
                unit_level(text)

    def test_unit_upgrade_never_interprets_millions_as_one_xp(self):
        bot = Mock()
        bot.optional_template.return_value = (945, 660)
        bot.text.side_effect = ['Уровень 70/80', '31,7M/1,51M']
        with patch('daily_tasks.open_task', return_value=1):
            upgrade_unit(bot)
        bot.click.assert_not_called()

    def test_task_names_do_not_confuse_speedup_with_campaign_refill(self):
        bot = Bot()
        bot.frame = cv2.imdecode(np.fromfile(ROOT / 'daily-claim.png', np.uint8), 1)
        for key, (rectangle, _) in TASK_ICONS.items():
            with self.subTest(key=key):
                bot.frame = cv2.imdecode(np.fromfile(ROOT / TASK_SOURCES.get(key, 'daily-claim.png'), np.uint8), 1)
                self.assertIsNotNone(bot.optional_template(TASK_SOURCES.get(key, 'daily-claim.png'), rectangle, (325, 380, 1830, 1030)))
        bot.frame = cv2.imdecode(np.fromfile(ROOT / 'daily-45.png', np.uint8), 1)
        for key in ('materials', 'recruit', 'speedup'):
            self.assertIsNone(bot.optional_template('daily-claim.png', TASK_ICONS[key][0], (325, 380, 1830, 1030)))
        self.assertIsNotNone(bot.optional_template('daily-claim.png', TASK_ICONS['upgrade'][0], (325, 380, 1830, 1030)))

    def test_selecting_material_can_enqueue_without_an_extra_click(self):
        bot = Mock()
        bot.detail.return_value = 'доска'
        with patch('daily_tasks.open_task', return_value=2), patch('daily_tasks.factory_queue',
                side_effect=[(0, 33), (1, 33), (1, 33), (2, 33)]):
            produce_materials(bot)
        bot.click.assert_any_call('производство', (1200, 830, 1740, 1000))
        self.assertEqual(bot.click.call_count, 2)  # Open workshop, then enqueue only one more.
        bot.main.assert_called_once()

    def test_existing_production_is_left_running(self):
        bot = Mock()
        with patch('daily_tasks.open_task', return_value=3), patch('daily_tasks.factory_queue', return_value=(4, 33)):
            produce_materials(bot)
        self.assertEqual(bot.click.call_count, 1)  # Only opening the production view.
        bot.main.assert_called_once()


if __name__ == '__main__':
    unittest.main()
