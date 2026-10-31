"""Offline boundary checks; does not connect to Android or click anything."""
import unittest
from unittest.mock import Mock, patch
import tempfile
from pathlib import Path

import numpy as np

from bot import Bot, Paused, ROOT, cv2, donation_count, donation_next, search_level, campaign_progress, resource_is_free, supply_count
from plans import PRESETS, validate_plan, save_plan, load_plan


class BotChecks(unittest.TestCase):
    def setUp(self):
        tracker=patch('telemetry.record')
        tracker.start(); self.addCleanup(tracker.stop)
    def test_different_promotions_do_not_depend_on_title(self):
        for text in ('новогоднее предложение купить', 'скидка 80% 299 rub',
                     'танковый набор лимит: 1 осталось: 2 ч. 1611%'):
            with self.subTest(text=text):
                bot=Bot(log=Mock()); state={'open':True}
                bot.text=Mock(side_effect=lambda region=None:text if state['open'] else 'карта')
                bot.back=Mock(side_effect=lambda:state.update(open=False))
                self.assertTrue(bot.dismiss_offer())
                bot.back.assert_called_once()

    def test_offer_explicit_close_button_is_used(self):
        bot=Bot(log=Mock()); state={'open':True}
        bot.text=Mock(side_effect=lambda region=None:'скидка купить' if state['open'] else 'карта')
        bot.point=Mock(return_value=(1700,90))
        bot.tap=Mock(side_effect=lambda *args:state.update(open=False))
        bot.back=Mock()
        self.assertTrue(bot.dismiss_offer())
        bot.tap.assert_called_once_with(1700,90)
        bot.back.assert_not_called()

    def test_research_and_production_timers_are_not_promotions(self):
        for text in ('центр исследований осталось: 2 ч.', 'производство лимит: 33 осталось: 15 мин.'):
            bot=Bot(); bot.text=Mock(return_value=text); bot.back=Mock()
            self.assertFalse(bot.dismiss_offer())
            bot.back.assert_not_called()

    def test_energy_bundle_without_offer_heading_is_closed(self):
        bot=Bot(log=Mock())
        state={'open':True}
        bot.text=Mock(side_effect=lambda region=None:
            'повышение энергии мгновенно получите предметы на 24 120 ед. золота лимит: 1 осталось: 3 д.'
            if state['open'] else 'карта')
        bot.back=Mock(side_effect=lambda:state.update(open=False))
        self.assertTrue(bot.dismiss_offer())
        bot.back.assert_called_once()

    def test_shop_offer_is_closed_and_observed_again(self):
        bot=Bot(log=Mock())
        state={'open': True}
        bot.text=Mock(side_effect=lambda region=None:
            'специальное предложение купить 299 руб.' if state['open'] else 'карта')
        bot.back=Mock(side_effect=lambda: state.update(open=False))
        self.assertTrue(bot.dismiss_offer())
        bot.back.assert_called_once()
        self.assertFalse(bot._closing_offer)

    def test_offer_word_without_purchase_is_not_closed(self):
        bot=Bot()
        bot.text=Mock(return_value='специальное предложение')
        bot.back=Mock()
        self.assertFalse(bot.dismiss_offer())
        bot.back.assert_not_called()

    def test_stuck_offer_is_bounded_and_guard_is_reset(self):
        bot=Bot()
        bot.text=Mock(return_value='особое предложение купить')
        bot.back=Mock()
        with self.assertRaises(Paused):
            bot.dismiss_offer()
        self.assertEqual(bot.back.call_count,3)
        self.assertFalse(bot._closing_offer)

    def test_failed_collector_does_not_skip_later_collectors(self):
        bot=Bot(log=Mock())
        bot.observe=Mock(); bot.has=Mock(return_value=False)
        def dispatch(number,resource):
            if number==4: raise Paused('search unreadable')
        bot.run_collector=Mock(side_effect=dispatch)
        with patch('emergency.local_recover',return_value=True):
            bot.run_plan(['Ферма','Ферма','Шахта','Шахта','Нефть'])
        self.assertEqual([c.args[0] for c in bot.run_collector.call_args_list],[1,2,3,4,4,5])
    def test_new_tank_presentation_is_closed_without_purchase(self):
        bot=Bot(log=Mock())
        bot.text=Mock(side_effect=['новинка! hetzer истребители танков','карта'])
        bot.back=Mock()
        self.assertTrue(bot.dismiss_new_unit())
        bot.back.assert_called_once()

    def test_normal_unit_card_is_not_dismissed_as_new_reward(self):
        bot=Bot()
        bot.text=Mock(return_value='hetzer истребители танков улучшение')
        bot.back=Mock()
        self.assertFalse(bot.dismiss_new_unit())
        bot.back.assert_not_called()
    def test_supply_label_split_over_two_lines_is_collected(self):
        bot = Bot()
        bot.optional_template = Mock(return_value=None)
        bot.lines = [
            {'text': 'Воздушные', 'words': [{'x':900,'y':500,'width':160,'height':20}]},
            {'text': 'поставки', 'words': [{'x':920,'y':522,'width':120,'height':20}]}]
        self.assertEqual(bot.supply_label_point(), (980,521))
        bot.lines[1]['words'][0]['y'] = 600
        self.assertIsNone(bot.supply_label_point())

    def test_real_supply_counter_images_survive_windows_ocr(self):
        for filename, expected in [('supply-counter-13.png', 13), ('supply-counter-10.png', 10), ('supply-counter-13-day.png',13)]:
            bot = Bot()
            for method in ('main', 'tap', 'wait', 'observe', 'require', 'template'):
                setattr(bot, method, Mock())
            bot.optional_template = Mock(return_value=None)
            bot.frame = cv2.imdecode(np.fromfile(ROOT / filename, np.uint8), 1)
            self.assertEqual(bot.open_supply_menu(), expected)

    def test_existing_crates_are_checked_even_when_call_counter_is_unreadable(self):
        bot=Bot()
        bot.open_supply_menu=Mock(side_effect=Paused('counter unreadable'))
        bot.has=Mock(return_value=True)
        bot.back=Mock()
        bot.collect_supplies=Mock(return_value=2)
        with self.assertRaises(Paused):
            bot.supplies()
        bot.back.assert_called_once()
        bot.collect_supplies.assert_called_once()

    def test_unreadable_supply_counter_is_not_treated_as_a_timer(self):
        bot = Bot(log=Mock())
        for method in ('main', 'tap', 'wait', 'observe', 'require', 'template'):
            setattr(bot, method, Mock())
        bot.optional_template = Mock(return_value=None)
        bot.detail = Mock(return_value='воздушные поставки')
        bot.frame = np.zeros((1080, 1920, 3), dtype=np.uint8)
        bot.read_ocr = Mock(return_value=[])
        with self.assertRaisesRegex(Paused, 'таймер не подтверждён'):
            bot.open_supply_menu()

    def test_supply_counter_from_contrast_ocr_is_used(self):
        bot = Bot()
        for method in ('main', 'tap', 'wait', 'observe', 'require', 'template'):
            setattr(bot, method, Mock())
        bot.optional_template = Mock(return_value=None)
        bot.detail = Mock(return_value='воздушные поставки')
        bot.frame = np.zeros((1080, 1920, 3), dtype=np.uint8)
        bot.read_ocr = Mock(return_value=[{'text': '>l(1 3/1 5)'}])
        self.assertEqual(bot.open_supply_menu(), 13)

    def test_supply_cooldown_requires_a_timer_in_the_supply_caption(self):
        bot = Bot(log=Mock())
        for method in ('main', 'tap', 'wait', 'observe', 'require', 'template'):
            setattr(bot, method, Mock())
        bot.optional_template = Mock(return_value=None)
        bot.detail = Mock(side_effect=['воздушные поставки', '3 мин. 6 сек.'])
        bot.frame = np.zeros((1080, 1920, 3), dtype=np.uint8)
        bot.read_ocr = Mock(return_value=[])
        self.assertIsNone(bot.open_supply_menu())
        self.assertIn('подтверждён таймер', bot.log.call_args.args[0])

    def test_supply_label_near_bottom_of_map_is_found_but_chat_is_excluded(self):
        bot = Bot()
        bot.optional_template = Mock(return_value=None)
        bot.lines = [{'text': 'Воздушные поставки', 'words':
                      [{'x':820,'y':880,'width':270,'height':28}]}]
        self.assertEqual(bot.supply_label_point(), (955, 894))
        bot.lines[0]['words'][0]['y'] = 990
        self.assertIsNone(bot.supply_label_point())

    def test_supply_label_fallback_finds_box_behind_hq_and_rejects_empty_map(self):
        bot = Bot()
        for filename in ('supply_loot.png', 'supply-label-tap.png', 'supply-lower-before.png'):
            bot.frame = cv2.imdecode(np.fromfile(ROOT / filename, np.uint8), 1)
            self.assertIsNotNone(bot.supply_label_point(), filename)
        bot.frame = cv2.imdecode(np.fromfile(ROOT / 'supply-collected-current.png', np.uint8), 1)
        self.assertIsNone(bot.supply_label_point())

    def test_supplies_drains_every_available_call_and_collects_after_zero(self):
        bot = Bot(log=Mock())
        bot.open_supply_menu = Mock(side_effect=[3, 2, 1, 0])
        bot.collect_supplies = Mock(side_effect=[1, 1, 1, 2])
        bot.tap = Mock(); bot.back = Mock(); bot.has = Mock(return_value=True)
        bot.template = Mock(return_value=(1190, 595))
        self.assertEqual(bot.supplies(), 5)
        self.assertEqual(bot.tap.call_count, 3)
        self.assertEqual(bot.collect_supplies.call_count, 4)
        bot.collect_supplies.assert_called_with()

    def test_supplies_does_not_repeat_a_call_when_counter_does_not_change(self):
        bot = Bot(log=Mock())
        bot.open_supply_menu = Mock(side_effect=[2, 2])
        bot.collect_supplies = Mock(return_value=1)
        bot.tap = Mock(); bot.back = Mock(); bot.has = Mock(return_value=True)
        bot.template = Mock(return_value=(1190, 595))
        with self.assertRaisesRegex(Paused, 'не уменьшился'):
            bot.supplies()
        bot.tap.assert_called_once()

    def supply_bot(self):
        bot = Bot(log=Mock())
        for method in ('main', 'tap', 'wait', 'observe'):
            setattr(bot, method, Mock())
        bot.rewards_open = Mock(return_value=False)
        bot.optional_template = Mock(return_value=(1064, 625))
        return bot

    def test_supply_collection_waits_for_label_clicks_label_and_confirms_disappearance(self):
        bot = self.supply_bot()
        bot.supply_label_point = Mock(side_effect=[None, None, (1065, 491), None, None, None, None])
        self.assertEqual(bot.collect_supplies(), 1)
        self.assertEqual([call.args for call in bot.tap.call_args_list], [(1065, 491), (1064, 625)])
        bot.log.assert_any_call('Воздушный ящик №1: военные трофеи получены, метка ящика исчезла')

    def test_supply_that_stays_visible_is_not_reported_as_collected(self):
        bot = self.supply_bot()
        bot.supply_label_point = Mock(return_value=(1065, 491))
        with self.assertRaises(Paused):
            bot.collect_supplies()
        self.assertFalse(any('трофеи получены' in str(call) for call in bot.log.call_args_list))

    def test_new_supply_call_waits_twelve_observations_without_claiming_collection(self):
        bot = self.supply_bot()
        bot.supply_label_point = Mock(return_value=None)
        self.assertEqual(bot.collect_supplies(wait_for_drop=True), 0)
        self.assertEqual(bot.supply_label_point.call_count, 12)
        bot.wait.assert_any_call(2.5)
        bot.tap.assert_not_called()
        bot.log.assert_any_call('Поставка вызвана, но приземлившиеся ящики пока не обнаружены; проверю в следующем проходе')

    def test_uncertain_manufacturing_returns_to_map_without_blind_retry(self):
        from production import UncertainAddition
        bot = Bot(log=Mock())
        bot.require = Mock()
        bot.back = Mock()
        bot.main = Mock()
        with patch('production.fill_queues', side_effect=UncertainAddition('Счётчик изменился')) as fill:
            bot.production({'enabled': True})
        fill.assert_called_once()
        bot.back.assert_called_once()
        bot.main.assert_called_once()

    def test_active_alliance_research_is_not_a_donation_window(self):
        bot = Bot()
        bot.has = Mock(return_value=False)
        bot.frame = cv2.imdecode(np.fromfile(ROOT / 'research-progress.png', np.uint8), 1)
        self.assertTrue(bot.research_in_progress())
        bot.frame = cv2.imdecode(np.fromfile(ROOT / 'research-local-current.png', np.uint8), 1)
        self.assertFalse(bot.research_in_progress())
    def test_daily_ninety_has_visual_fallback_when_windows_ocr_omits_digits(self):
        bot = Bot()
        bot.frame = cv2.imdecode(np.fromfile(ROOT / 'daily-90.png', np.uint8), 1)
        bot.read_ocr = Mock(return_value=[])
        self.assertEqual(bot.daily_activity(), 90)
        bot.frame = cv2.imdecode(np.fromfile(ROOT / 'daily-45.png', np.uint8), 1)
        with self.assertRaises(Paused):
            bot.daily_activity()

    def test_supply_count_handles_ocr_split_digits_and_bounds(self):
        self.assertEqual(supply_count('Воздушные поставки (1 5/15)'), 15)
        self.assertEqual(supply_count('(0/15)'), 0)
        for value in ('(16/15)', '(1/20)', '3 мин. 55 сек.'):
            self.assertIsNone(supply_count(value))

    def test_disappearing_help_shortcut_uses_alliance_menu_only_from_verified_map(self):
        bot = Bot(log=Mock())
        bot.has = Mock(return_value=False)
        bot.main = Mock()
        bot.optional_template = Mock(return_value=(237, 900))
        bot.tap = Mock()
        bot.require = Mock()
        bot.help_all_point = Mock(return_value=None)
        bot.help_open = Mock(return_value=False)
        bot.require_help = Mock()
        bot.help_all()
        self.assertEqual([call.args for call in bot.tap.call_args_list],
                         [(237, 900), (1646, 1023), (1608, 955), (1536, 110)])
        bot.main.side_effect = [None, Paused('Не карта')]
        bot.tap.reset_mock()
        with self.assertRaises(Paused):
            bot.help_all()
        bot.tap.assert_called_once_with(237, 900)

    def test_help_header_and_coin_recognize_window_when_counter_ocr_is_missing(self):
        bot = Bot()
        bot.has = Mock(return_value=False)
        bot.frame = cv2.imdecode(np.fromfile(ROOT / 'help-ready.png', np.uint8), 1)
        self.assertTrue(bot.help_open())
        bot.frame = cv2.imdecode(np.fromfile(ROOT / 'map.png', np.uint8), 1)
        self.assertFalse(bot.help_open())

    def test_local_orders_accepts_only_native_oil_price_1000(self):
        bot = Bot()
        bot.require = Mock()
        bot.text = Mock(return_value='1 000')
        bot.frame = cv2.imdecode(np.fromfile(ROOT / 'research-local-current.png', np.uint8), 1)
        bot.frame[895:940, 1018:1040] = (200, 150, 100)
        bot.require_resource_button()
        bot.optional_template = Mock(return_value=None)
        with self.assertRaises(Paused):
            bot.require_resource_button()

    def test_help_all_accepts_actual_button_label_and_rejects_disabled(self):
        bot = Bot()
        ready = cv2.imdecode(np.fromfile(ROOT / 'help-ready.png', np.uint8), 1)
        bot.point = Mock(return_value=(958, 949))
        for label in ('Помощь всем', 'Помочь всем', 'Помогать всем'):
            bot.frame = ready
            bot.text = Mock(return_value=label)
            self.assertEqual(bot.help_all_point(), (958, 949))
        bot.frame = np.full_like(ready, 120)
        self.assertIsNone(bot.help_all_point())

    def test_donation_threshold_and_drain(self):
        for value in (1, 8, 14):
            self.assertTrue(donation_next(value, False))
        self.assertTrue(donation_next(15, False))
        self.assertTrue(donation_next(20, False))
        self.assertTrue(donation_next(1, True))
        for value in (None, -1, 0, 21):
            self.assertFalse(donation_next(value, True))
        self.assertEqual(donation_count('Участие: 15/20'), 15)
        self.assertEqual(donation_count('Участие: 1 [20'), 1)
        self.assertIsNone(donation_count('Участие: 21/20'))
        self.assertIsNone(donation_count('Награды за вклад 15'))

    def test_eight_available_donations_are_drained_to_zero(self):
        bot = Bot(log=Mock())
        bot.text = Mock(side_effect=[f'Участие: {n}/20' for n in range(8, -1, -1)])
        bot.require = Mock()
        bot.require_resource_button = Mock()
        bot.tap = Mock()
        bot.research_funded = Mock(return_value=False)
        bot.research_in_progress = Mock(return_value=False)
        self.assertEqual(bot.donate_current_research('экспансия'), 8)
        self.assertEqual(bot.tap.call_count, 8)

    def test_search_level_rejects_unknown(self):
        self.assertEqual(search_level('Ур. 8'), 8)
        self.assertEqual(search_level('Ур.в'), 8)
        for value in ('Ур. 80', 'Ур. -1', 'Ур. ?', '8', 'Ур. 0'):
            self.assertIsNone(search_level(value))

    def test_resource_occupancy_uses_whole_card(self):
        self.assertTrue(resource_is_free('Ферма ур. 7\nРезервы 2,25M\nШахтер\nНет'))
        self.assertTrue(resource_is_free('Нефтяник Нет'))
        self.assertTrue(resource_is_free('Нет\nШахтер'))
        self.assertFalse(resource_is_free('Нет\nШахтер [TX] Игрок'))
        self.assertFalse(resource_is_free('Шахтер [TX] Игрок'))
        self.assertFalse(resource_is_free('Резервы Нет'))

    def test_occupied_or_unreadable_resource_reopens_search_at_lower_level(self):
        bot = Bot(log=Mock())
        bot.open_resource_search = Mock(return_value=6)
        bot.slider_level = Mock(side_effect=[6, 5])
        bot.require = bot.main = bot.tap = bot.wait = bot.observe = Mock()
        bot.has = Mock(return_value=False)
        bot.detail = Mock(side_effect=['резервы ур. 6', 'шахтер [TX] игрок',
                                      'резервы ур. 5', 'нет\nшахтер'])
        bot.lines = [{'words': [{'text': 'Шахтер', 'x': 238, 'y': 494, 'height': 21}]}]
        bot.template = Mock(return_value=(960, 720))
        bot.dispatch_free_collector = Mock()
        bot.search_resources('Нефтяная вышка', 4)
        bot.open_resource_search.assert_any_call('Нефтяная вышка', target=5)
        bot.dispatch_free_collector.assert_called_once_with(4)

    def test_stop_and_stale_frame_prevent_input(self):
        bot = Bot()
        bot.command = Mock()
        with self.assertRaises(Paused):
            bot.tap(100, 100)
        bot.command.assert_not_called()
        bot = Bot()
        bot.stop.set()
        with self.assertRaises(Paused):
            bot.command('devices')

    def test_grey_and_gold_donation_buttons_are_rejected(self):
        bot = Bot()
        bot.require = Mock()
        bot.text = Mock(return_value='3 000')
        for bgr in ((120, 120, 120), (80, 180, 220)):
            bot.frame = np.full((1080, 1920, 3), bgr, dtype=np.uint8)
            with self.assertRaises(Paused):
                bot.require_resource_button()
        bot.frame = np.full((1080, 1920, 3), (200, 150, 100), dtype=np.uint8)
        bot.require_resource_button()
        bot.text.return_value = '120'
        with self.assertRaises(Paused):
            bot.require_resource_button()

    def test_plan_validation_and_roundtrip(self):
        expected = ['Ферма', 'Ферма', 'Нефть', 'Нефть', 'Шахта']
        self.assertEqual(next(iter(PRESETS.values())), expected)
        for bad in ([], expected + ['Шахта'], ['Платный отряд'] * 5, 'Ферма'):
            with self.assertRaises(ValueError):
                validate_plan(bad)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'settings.json'
            save_plan(path, expected)
            self.assertEqual(load_plan(path), expected)

    def test_free_collector_marker_excludes_busy_slots(self):
        bot = Bot()
        bot.frame = cv2.imdecode(np.fromfile(ROOT / 'collector_free.png', np.uint8), 1)
        point = bot.template('collector_free.png', (787, 475, 814, 501), (770, 470, 830, 510))
        self.assertTrue(787 <= point[0] <= 814)
        with self.assertRaises(Paused):
            bot.template('collector_free.png', (787, 475, 814, 501), (490, 470, 550, 510))

    def test_slider_levels_from_observed_screens(self):
        bot = Bot()
        for filename, expected in [('search_mine.png', 1), ('search_max_missing.png', 8)]:
            bot.frame = cv2.imdecode(np.fromfile(ROOT / filename, np.uint8), 1)
            self.assertEqual(bot.slider_level(8), expected)

    def test_selected_collector_is_matched_to_plan(self):
        bot = Bot()
        bot.frame = cv2.imdecode(np.fromfile(ROOT / 'collector_free.png', np.uint8), 1)
        bot.require = Mock()
        bot.command = Mock()
        bot.wait = Mock()
        bot.observe = Mock()
        bot.tap = Mock()
        bot.detail = Mock(return_value='отряд сбора nq2')
        bot.send_selected_collector = Mock(return_value=True)
        self.assertTrue(bot.dispatch_free_collector(2))
        bot.send_selected_collector.assert_called_once()
        bot.send_selected_collector.reset_mock()
        with self.assertRaises(Paused):
            bot.dispatch_free_collector(1)
        bot.send_selected_collector.assert_not_called()
        with self.assertRaises(Paused):
            bot.dispatch_free_collector(6)

    def test_fourth_free_collector_survives_carousel_scroll_offset(self):
        bot = Bot()
        bot.frame = cv2.imdecode(np.fromfile(ROOT / 'collector-four-free.png', np.uint8), 1)
        for method in ('require', 'command', 'wait', 'observe', 'tap'):
            setattr(bot, method, Mock())
        bot.detail = Mock(return_value='отряд сбора №4')
        bot.send_selected_collector = Mock(return_value=True)
        self.assertTrue(bot.dispatch_free_collector(4))
        bot.send_selected_collector.assert_called_once_with(4)

    def test_plan_waits_for_returning_collector(self):
        bot = Bot(log=Mock())
        for method in ('observe', 'main', 'tap', 'require', 'search_resources'):
            setattr(bot, method, Mock())
        bot.detail = Mock(side_effect=['отправить', 'до базы: 46 км'])
        bot.run_plan(['Ферма'] + ['Не отправлять'] * 4)
        self.assertIn(((155, 250), {}), bot.tap.call_args_list)
        bot.search_resources.assert_not_called()
        bot.log.assert_any_call('Отряд №1 возвращается на базу; дождусь прибытия')

    def test_single_resource_search_can_select_the_fourth_collector(self):
        bot = Bot()
        for method in ('main', 'tap', 'require', 'observe'):
            setattr(bot, method, Mock())
        bot.detail = Mock(side_effect=['отозвать', 'добыча', 'отправить', 'до базы: 10 км',
                                      'отозвать', 'до пункта назначения', 'отправить', 'ждет'])
        self.assertEqual(bot.first_free_collector(), 4)

    def test_dispatch_success_requires_collector_status_confirmation(self):
        for caption, state, expected in [('отправить', 'до базы: 46 км', False),
                                          ('отозвать', 'до пункта назначения: 3 км', True)]:
            with self.subTest(state=state):
                bot = Bot(log=Mock())
                bot.frame = np.full((1080, 1920, 3), (60, 160, 190), dtype=np.uint8)
                for method in ('require', 'template', 'tap', 'main'):
                    setattr(bot, method, Mock())
                bot.has = Mock(return_value=False)
                bot.detail = Mock(side_effect=['отправить 27 км', caption, state])
                self.assertEqual(bot.send_selected_collector(1), expected)

    def test_phrase_may_span_ocr_lines(self):
        bot = Bot()
        bot.text = Mock(return_value='поблизости не найдено\nподходящих шахт')
        self.assertTrue(bot.has('не найдено подходящих'))

    def test_daily_claimed_chests_are_skipped(self):
        bot = Bot()
        bot.frame = cv2.imdecode(np.fromfile(ROOT / 'daily.png', np.uint8), 1)
        bot.daily_screen = Mock()
        bot.tap = Mock()
        bot.daily_chests()
        bot.tap.assert_not_called()

    def test_daily_ready_cards_and_locked_chests(self):
        bot = Bot(log=Mock())
        bot.frame = cv2.imdecode(np.fromfile(ROOT / 'daily-current.png', np.uint8), 1)
        self.assertEqual(bot.daily_ready_card(), (470, 574))
        bot.daily_screen = Mock()
        bot.daily_activity = Mock(side_effect=[0, 15])
        bot.wait = Mock()
        bot.observe = Mock()
        bot.tap = Mock(side_effect=lambda *args: setattr(bot, 'frame', cv2.imdecode(np.fromfile(ROOT / 'daily-claim.png', np.uint8), 1)))
        bot.daily_task_rewards()
        bot.tap.assert_called_once()
        bot.daily_activity = Mock(return_value=15)
        bot.tap.reset_mock()
        bot.daily_chests()
        bot.tap.assert_not_called()

    def test_reward_confirmation_rejects_unrelated_screen(self):
        bot = Bot()
        bot.frame = cv2.imdecode(np.fromfile(ROOT / 'map.png', np.uint8), 1)
        bot.tap = Mock()
        self.assertFalse(bot.rewards_open())
        self.assertFalse(bot.officer_report_open())
        with self.assertRaises(Paused):
            bot.confirm_rewards()
        bot.tap.assert_not_called()

    def test_radar_collects_and_confirms_only_ready_rewards(self):
        bot = Bot(log=Mock())
        def frame(name):
            bot.frame = cv2.imdecode(np.fromfile(ROOT / name, np.uint8), 1)
        frame('map.png')
        frames = iter(['radar_after_all.png', 'radar_rewards.png', 'radar_remaining.png', 'radar_rewards.png', 'radar_remaining.png'])
        bot.main = Mock()
        bot.wait = Mock()
        bot.observe = Mock()
        bot.tap = Mock(side_effect=lambda *args: frame(next(frames)))
        bot.back = Mock()
        bot.text = Mock(return_value='сохраненные миссии: 0/35')
        bot.radar_rewards()
        self.assertEqual(bot.tap.call_count, 5)
        self.assertEqual(bot.tap.call_args_list[0].args, (74, 577))
        self.assertTrue(780 < bot.tap.call_args_list[-1].args[0] < 1140)
        bot.back.assert_called_once()
        bot.log.assert_any_call('Награды подтверждены')

    def test_radar_repeats_individual_rewards_until_zero(self):
        bot = Bot(log=Mock())
        frames = iter(['radar_after_all.png', 'radar_rewards.png', 'radar_after_all.png',
                       'radar_rewards.png', 'radar_remaining.png', 'radar_rewards.png', 'radar_remaining.png'])
        bot.tap = Mock(side_effect=lambda *args: setattr(bot, 'frame', cv2.imdecode(np.fromfile(ROOT / next(frames), np.uint8), 1)))
        bot.main = bot.wait = bot.observe = bot.back = Mock()
        bot.text = Mock(return_value='сохраненные миссии: 0/35')
        bot.radar_rewards()
        self.assertEqual(bot.tap.call_count, 7)
        bot.log.assert_any_call('Радар: сохранённые миссии 0; оставшиеся награды дополнительно проверены')

    def test_daily_thirty_is_read_when_windows_ocr_omits_digits(self):
        bot = Bot()
        bot.frame = cv2.imdecode(np.fromfile(ROOT / 'daily-activity-30.png', np.uint8), 1)
        bot.read_ocr = Mock(return_value=[])
        self.assertEqual(bot.daily_activity(), 30)

    def test_donation_waits_for_delayed_counter_without_second_click(self):
        bot = Bot(log=Mock())
        bot.text = Mock(side_effect=['участие: 1/20','участие: 1/20','участие: 0/20'])
        bot.require = bot.require_resource_button = bot.wait = bot.observe = Mock()
        bot.research_funded = bot.research_in_progress = Mock(return_value=False)
        bot.tap = Mock()
        self.assertEqual(bot.donate_current_research('завоеватель'), 1)
        bot.tap.assert_called_once()

    def test_officer_report_has_separate_confirmation(self):
        bot = Bot(log=Mock())
        bot.frame = cv2.imdecode(np.fromfile(ROOT / 'officer_report.png', np.uint8), 1)
        self.assertTrue(bot.officer_report_open())
        self.assertFalse(bot.rewards_open())
        bot.wait = Mock()
        bot.observe = Mock()
        bot.tap = Mock(side_effect=lambda *args: setattr(bot, 'frame', cv2.imdecode(np.fromfile(ROOT / 'officer_missions.png', np.uint8), 1)))
        bot.confirm_officer_report()
        bot.tap.assert_called_once()

    def test_officer_candidates_exclude_running_missions(self):
        bot = Bot()
        for name, expected in [('officer_missions.png', 2), ('officer-list-live.png', 6),
                               ('officer-running.png', 0), ('map.png', 0)]:
            with self.subTest(name=name):
                bot.frame = cv2.imdecode(np.fromfile(ROOT / name, np.uint8), 1)
                self.assertEqual(len(bot.officer_candidates()), expected)

    def test_officers_send_requires_enabled_gold_button(self):
        bot = Bot()
        bot.has = Mock(return_value=True)
        for name, expected in [('officer-select.png', False), ('officer-picked.png', True)]:
            bot.frame = cv2.imdecode(np.fromfile(ROOT / name, np.uint8), 1)
            self.assertEqual(bot.officer_send_enabled(), expected)
        bot.frame = cv2.imdecode(np.fromfile(ROOT / 'map.png', np.uint8), 1)
        with self.assertRaises(Paused):
            bot.officer_send_enabled()

    def test_campaign_outcome_is_distinguished_from_active_combat(self):
        bot = Bot()
        for name, outcome in [('battle_victory.png', 'victory'), ('campaign_defeat.png', 'defeat'),
                              ('battle.png', None), ('map.png', None)]:
            with self.subTest(name=name):
                bot.frame = cv2.imdecode(np.fromfile(ROOT / name, np.uint8), 1)
                self.assertEqual(bot.campaign_result(), outcome)

    def test_campaign_progress_joins_ocr_split_digits(self):
        self.assertEqual(campaign_progress('силы «Ворона»: 3/1 8'), (3, 18))
        self.assertEqual(campaign_progress('силы «Ворона»: 0/1 9'), (0, 19))
        self.assertIsNone(campaign_progress('силы «Ворона» (выполнено)'))
        self.assertIsNone(campaign_progress('99/18'))

    def test_campaign_waits_for_victory_button_animation(self):
        bot = Bot()
        ready = cv2.imdecode(np.fromfile(ROOT / 'battle_victory.png', np.uint8), 1)
        animating = ready.copy()
        animating[860:975, 785:1140] = 0
        frames = iter([animating, ready, cv2.imdecode(np.fromfile(ROOT / 'map.png', np.uint8), 1)])
        bot.observe = Mock(side_effect=lambda: setattr(bot, 'frame', next(frames)))
        bot.wait = Mock()
        bot.tap = Mock()
        bot.return_campaign_victory()
        bot.tap.assert_called_once()
        self.assertEqual(bot.observe.call_count, 3)

    def test_campaign_targets_enemy_badges_at_screen_and_hud_edges(self):
        bot = Bot()
        for name, expected in [('battle.png', (865, 790)), ('battle24_start.png', (1213, 740)),
                               ('battle25_start.png', (484, 350)), ('battle26_start.png', (484, 790))]:
            bot.frame = cv2.imdecode(np.fromfile(ROOT / name, np.uint8), 1)
            self.assertEqual(bot.campaign_target(), expected)
        bot.frame = cv2.imdecode(np.fromfile(ROOT / 'map.png', np.uint8), 1)
        with self.assertRaises(Paused):
            bot.campaign_target()
        source = cv2.imdecode(np.fromfile(ROOT / 'probe-01.png', np.uint8), 1)
        bot.frame = np.zeros_like(source)
        bot.frame[250:700, 650:1250] = source[250:700, 650:1250]
        with self.assertRaises(Paused):
            bot.campaign_target()


if __name__ == '__main__':
    unittest.main()


class CampaignModeChecks(unittest.TestCase):
    def test_sea_map_and_victory_have_native_templates(self):
        bot = Bot()
        bot.frame = cv2.imdecode(np.fromfile(ROOT / 'campaign-sea-map.png', np.uint8), 1)
        self.assertEqual(bot.campaign_mode(), 'sea')
        bot.frame = cv2.imdecode(np.fromfile(ROOT / 'campaign-sea-victory.png', np.uint8), 1)
        self.assertEqual(bot.campaign_result(), 'victory')
