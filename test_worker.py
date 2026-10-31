"""Native bridge boundaries; no Android input or settings writes."""
import json
from pathlib import Path
import subprocess
import sys
import threading
import unittest
from unittest.mock import Mock, patch

from production import DEFAULT
from worker import Worker


class WorkerChecks(unittest.TestCase):
    def test_statistics_read_failure_does_not_escape_command(self):
        events=[]; worker=Worker(events.append); worker.log=Mock()
        with patch('telemetry.load',side_effect=ValueError('bad json')):
            worker.command({'command':'statistics'})
        self.assertEqual(events[-1]['event'],'statistics_error')
        with patch('telemetry.load',return_value={'since':'test'}):
            worker.command({'command':'statistics'})
        self.assertEqual(events[-1]['event'],'statistics')
    def test_every_stage_failure_is_recovered_without_skipping_later_stages(self):
        names=('help_all','supplies','radar_rewards','personal_research','army_refill',
               'run_plan','production','research','daily_actions')
        for name in names:
            with self.subTest(stage=name):
                events=[]; worker=Worker(events.append); worker.log=Mock()
                bot=Mock(); getattr(bot,name).side_effect=[RuntimeError('interrupted'),None]
                with patch('bot.Bot',return_value=bot), patch('emergency.recover',return_value=True) as recovery:
                    worker.run('cycle',False,['Ферма']*5,DEFAULT)
                self.assertEqual(getattr(bot,name).call_count,2)
                recovery.assert_called_once()
                steps=[event for event in events if event['event']=='progress'][-1]['steps']
                self.assertTrue(all(step['status']=='done' for step in steps))

    def setUp(self):
        groups=patch('army.load_groups',return_value=False)
        groups.start()
        self.addCleanup(groups.stop)
    def test_unexpected_stage_error_recovers_and_other_stages_continue(self):
        worker=Worker(Mock()); worker.log=Mock()
        bot=Mock(); bot.radar_rewards.side_effect=RuntimeError('unexpected radar failure')
        with patch('bot.Bot',return_value=bot), patch('emergency.recover',return_value=True):
            worker.run('cycle',False,['Ферма']*5,DEFAULT)
        self.assertEqual(bot.radar_rewards.call_count,2)
        bot.run_plan.assert_called_once()
        bot.daily_actions.assert_called_once()
        bot.close.assert_called_once()
    def test_group_toggle_is_saved_and_off_prevents_group_actions(self):
        events = []
        worker = Worker(events.append)
        with patch('army.save_groups') as save:
            worker.command({'command':'army_groups','enabled':True})
            save.assert_called_once_with(True)
        self.assertTrue(events[-1]['enabled'])
        worker.join_army_groups = False
        bot = Mock()
        with patch('army.join_groups') as join:
            worker.army_actions(bot)
            join.assert_not_called()
            worker.join_army_groups = True
            worker.army_actions(bot)
            join.assert_called_once_with(bot)

    def test_protocol_ready_and_eof_exit_without_game_input(self):
        result = subprocess.run([sys.executable, '-u', 'worker.py'], input='', capture_output=True,
                                encoding='utf-8', timeout=10, cwd=Path(__file__).parent)
        self.assertEqual(result.returncode, 0, result.stderr)
        event = next(json.loads(line) for line in result.stdout.splitlines() if json.loads(line)['event'] == 'ready')
        self.assertEqual(event['event'], 'ready')
        self.assertEqual(len(event['plan']), 5)

    def test_cycle_includes_all_normal_modules_and_releases_lock(self):
        events = []
        worker = Worker(events.append)
        worker.log = Mock()
        bot = Mock()
        with patch('bot.Bot', return_value=bot):
            worker.run('cycle', False, ['Ферма']*5, DEFAULT)
        for name in ('help_all', 'research', 'supplies', 'radar_rewards', 'personal_research', 'army_refill'):
            getattr(bot, name).assert_called_once()
        bot.daily_actions.assert_called_once_with(send_officers=True, skip_materials=True)
        bot.run_plan.assert_called_once_with(['Ферма']*5)
        bot.production.assert_called_once_with(DEFAULT)
        bot.close.assert_called_once()
        self.assertEqual(events[-1]['busy'], False)
        progress = [event for event in events if event['event'] == 'progress']
        self.assertEqual(len(progress[-1]['steps']), 9)
        self.assertTrue(all(step['status'] == 'done' for step in progress[-1]['steps']))

    def test_recovered_module_is_deferred_and_next_module_runs(self):
        from bot import Paused
        events = []
        worker = Worker(events.append); worker.log = Mock()
        bot = Mock(); bot.help_all.side_effect = Paused('temporary screen')
        with patch('bot.Bot',return_value=bot), patch('emergency.recover',return_value=True):
            worker.run('cycle',False,['Ферма']*5,DEFAULT)
        self.assertEqual(bot.help_all.call_count, 2)
        worker.log.assert_any_call('Помощь альянсу: temporary screen (попытка 2/2)')
        bot.research.assert_called_once()
        progress = [event for event in events if event['event']=='progress'][-1]
        self.assertEqual(progress['steps'][0]['status'],'deferred')
        self.assertEqual(progress['steps'][1]['status'],'done')

    def test_recovered_module_retries_and_daily_is_last(self):
        from bot import Paused
        events = []
        worker = Worker(events.append); worker.log = Mock()
        bot = Mock(); bot.help_all.side_effect = [Paused('temporary'), None]
        with patch('bot.Bot', return_value=bot), patch('emergency.recover', return_value=True):
            worker.run('cycle', False, ['Ферма']*5, DEFAULT)
        self.assertEqual(bot.help_all.call_count, 2)
        progress = [e for e in events if e['event'] == 'progress'][-1]
        self.assertTrue(all(s['status'] == 'done' for s in progress['steps']))
        self.assertEqual(progress['steps'][-1]['title'], 'Ежедневные действия, офицеры и пополнение')
        self.assertEqual(progress['steps'][-2]['title'], 'Пожертвования от 1/20')
        self.assertEqual(progress['steps'][1]['title'], 'Воздушные поставки: вызов и сбор')

    def test_persistent_farm_restarts_failed_session_until_stop(self):
        events = []
        worker = Worker(events.append); worker.log = Mock()
        worker.stop = Mock()
        worker.stop.is_set.side_effect = [False, True]
        worker.stop.wait.return_value = False
        worker.run_session = Mock(return_value='ПАУЗА: нет подключения')
        worker.run('cycle', True, ['Ферма']*5, DEFAULT)
        self.assertEqual(worker.run_session.call_count, 2)
        worker.stop.wait.assert_called_once_with(60)
        self.assertTrue(next(event for event in events if event['event'] == 'state')['busy'])
        self.assertFalse(events[-1]['busy'])

    def test_stop_during_reconnect_prevents_restart(self):
        worker = Worker(Mock()); worker.log = Mock()
        worker.stop = Mock(); worker.stop.is_set.return_value = False
        worker.stop.wait.return_value = True
        worker.run_session = Mock(return_value='ПАУЗА: экран')
        worker.run('cycle', True, ['Ферма']*5, DEFAULT)
        worker.run_session.assert_called_once()

    def test_unpassable_campaign_level_is_reported_in_ui(self):
        from bot import Paused
        worker = Worker(Mock()); worker.log = Mock()
        bot = Mock(); bot.campaign_level = '2-10 под радарами противника'
        bot.campaign.side_effect = Paused('Бой не продвигается')
        with patch('bot.Bot', return_value=bot), patch('emergency.recover', return_value=True), patch('pathlib.Path.write_text'):
            worker.run('campaign_sea', False, ['Ферма']*5, DEFAULT)
        worker.emit.assert_any_call({'event':'campaign_status', 'message':'2-10 под радарами противника: пока непроходим'})
        bot.campaign.assert_called_once_with('sea')

    def test_animation_events_follow_real_actions_and_recovery(self):
        from bot import Paused
        events = []
        worker = Worker(events.append); worker.log = Mock()
        bot = Mock(); bot.help_all.side_effect = [Paused('screen'), None]
        with patch('bot.Bot', return_value=bot), patch('emergency.recover', return_value=True):
            worker.run('cycle', False, ['Ферма']*5, DEFAULT)
        states = [e['state'] for e in events if e['event'] == 'animation']
        self.assertIn('recovery', states)
        self.assertIn('production', states)
        self.assertEqual(states.count('success'), 9)
        self.assertLess(states.index('recovery'), states.index('success'))
        self.assertEqual(states[-1], 'idle')

    def test_sea_animation_and_real_stop_are_distinct(self):
        events = []
        worker = Worker(events.append); worker.log = Mock()
        bot = Mock(); bot.campaign.side_effect = lambda *_: worker.stop.set()
        with patch('bot.Bot', return_value=bot):
            worker.run('campaign_sea', False, ['Ферма']*5, DEFAULT)
        states = [e['state'] for e in events if e['event'] == 'animation']
        self.assertIn('sea_campaign', states)
        self.assertEqual(states[-1], 'stopped')

    def test_invalid_production_does_not_write_collector_plan(self):
        worker = Worker(Mock())
        with patch('worker.save_plan') as save:
            with self.assertRaises(ValueError):
                worker.command({'command':'save', 'plan':['Ферма']*5, 'production':{}})
        save.assert_not_called()

    def test_campaign_is_separate_and_does_not_repeat_the_farm(self):
        worker = Worker(Mock())
        worker.log = Mock()
        bot = Mock()
        with patch('bot.Bot', return_value=bot):
            worker.run('campaign', True, ['Ферма']*5, DEFAULT)
        bot.campaign.assert_called_once_with('land')
        bot.help_all.assert_not_called()
        bot.wait.assert_not_called()
        bot.close.assert_called_once()

    def test_cancellation_stops_before_next_module(self):
        worker = Worker(Mock())
        worker.log = Mock()
        bot = Mock()
        bot.help_all.side_effect = worker.stop.set
        with patch('bot.Bot', return_value=bot):
            worker.run('cycle', False, ['Ферма']*5, DEFAULT)
        bot.research.assert_not_called()
        bot.close.assert_called_once()

    def test_second_start_is_rejected_and_close_waits(self):
        worker = Worker(Mock())
        worker.thread = Mock()
        worker.thread.is_alive.return_value = True
        with self.assertRaisesRegex(ValueError, 'уже выполняется'):
            worker.command({'command':'start', 'task':'cycle'})
        worker.close()
        self.assertTrue(worker.stop.is_set())
        worker.thread.join.assert_called_once()
