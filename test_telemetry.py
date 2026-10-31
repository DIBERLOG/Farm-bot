import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import telemetry as t


class StatisticsChecks(unittest.TestCase):
    def test_transient_incomplete_json_is_retried(self):
        with patch.object(Path,'exists',return_value=True), patch.object(Path,'read_text',side_effect=['{\n', '{"since":"test"}']), patch.object(t.time,'sleep'):
            self.assertEqual(t.load(),{'since':'test'})

    def test_broken_json_is_named_and_never_overwritten(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(t,'PATH',Path(folder)/'statistics.json'), patch.object(t.time,'sleep'):
            t.PATH.write_text('{\n',encoding='utf-8')
            with self.assertRaisesRegex(ValueError,'statistics.json'):
                t.load()
            self.assertEqual(t.PATH.read_text(),'{\n')
    def test_storage_failure_does_not_interrupt_game_action(self):
        from unittest.mock import Mock
        bot=Mock()
        t.safe(bot,Mock(side_effect=OSError('disk unavailable')))
        bot.log.assert_called_once()

    def test_gathering_only_counts_new_progress_on_tracked_trips(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(t,'PATH',Path(folder)/'stats.json'):
            t.gathering(1,'100 / 200')
            self.assertFalse(t.PATH.exists())
            t.record('dispatches','Шахта',1,level=8,collector=1)
            t.gathering(1,'1 208 432/2 020 000')
            t.gathering(1,'1 208 432/2 020 000')
            t.gathering(1,'1 300 000/2 020 000')
            self.assertEqual(t.load()['gathered']['Шахта'],1300000)
            t.record('dispatches','Нефтяная вышка',1,level=8,collector=1)
            t.gathering(1,'100/200')
            self.assertEqual(t.load()['gathered']['Нефтяная вышка'],100)
    def test_persistence_dispatch_levels_and_confirmed_production(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(t,'PATH',Path(folder)/'stats.json'):
            t.record('dispatches','Шахта',1,level=8)
            t.record('queued','Железная балка',5,workshop=2)
            self.assertEqual(t.load()['produced'],{})
            t.completed_queue(2)
            t.completed_queue(2)
            data=t.load()
            self.assertEqual(data['dispatches']['Шахта'],1)
            self.assertEqual(data['levels']['8'],1)
            self.assertEqual(data['produced']['Железная балка'],5)
            self.assertNotIn('2',data['pending'])

    def test_balance_parser_does_not_guess_unreadable_values(self):
        for text,expected in [('12,5M',12500000),('1 234',1234),('87к',87000),('не прочитано',None)]:
            self.assertEqual(t.parse_balance(text),expected)

    def test_mixed_recipe_is_counted_only_for_claimed_workshop(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(t,'PATH',Path(folder)/'stats.json'):
            t.record('queued','Бетон',5,workshop=4)
            t.record('queued','Асфальт',2,workshop=4)
            t.record('queued','Цемент',3,workshop=1)
            t.completed_queue(4)
            self.assertEqual(t.load()['produced'],{'Бетон':5,'Асфальт':2})

    def test_balance_decrease_is_not_negative_income(self):
        from unittest.mock import Mock
        with tempfile.TemporaryDirectory() as folder, patch.object(t,'PATH',Path(folder)/'stats.json'):
            bot=Mock(); bot.text.return_value='10м'
            t.snapshot(bot)
            bot.text.return_value='9м'; t.snapshot(bot)
            self.assertEqual(t.load()['inflow'],{})
            bot.text.return_value='11м'; t.snapshot(bot)
            self.assertEqual(t.load()['inflow']['Сталь'],2000000)
