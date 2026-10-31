import unittest
from unittest.mock import Mock, patch
import numpy as np
from bot import Bot, ROOT, cv2
from alliance_research import nodes, donate_all, pan


class AllianceResearchChecks(unittest.TestCase):
    def test_tree_end_uses_stable_nodes_despite_background_animation(self):
        bot=Mock()
        bot.frame=np.zeros((1080,1920,3),dtype=np.uint8)
        bot.observe.side_effect=lambda: setattr(bot,'frame',np.full((1080,1920,3),150,dtype=np.uint8))
        with patch('alliance_research.nodes',side_effect=[[(500,300,False,b'a')],[(503,300,False,b'a')]]):
            self.assertFalse(pan(bot))
    def test_actual_tree_finds_like_and_unlocked_nodes_beyond_old_five(self):
        bot = Bot()
        bot.frame = cv2.imdecode(np.fromfile(ROOT/'alliance-tree-current.png',np.uint8),1)
        found = nodes(bot)
        self.assertGreaterEqual(len(found),12)
        self.assertTrue(found[0][2])
        self.assertLess(abs(found[0][0]-129),3)
        self.assertTrue(any(abs(x-1536)<4 for x,_,_,_ in found))
        self.assertFalse(any(x>1700 for x,_,_,_ in found))

    def test_every_category_colour_and_rectangular_skills_are_found(self):
        bot=Bot()
        for category in ['развитие','война','территория','навыки']:
            bot.frame=cv2.imdecode(np.fromfile(ROOT/('alliance-scan-'+category+'.png'),np.uint8),1)
            self.assertGreaterEqual(len(nodes(bot)),4,category)

    def donation_bot(self, recommended_funded):
        bot = Mock()
        state = {'selected':'', 'count':1}
        def tap(x,y):
            if (x,y)==(100,300): state['selected']='рекомендованная'
            if (x,y)==(400,300): state['selected']='другая'
        bot.tap.side_effect=tap
        bot.text.side_effect=lambda region: (state['selected']+' ур. 1' if region==(350,80,1480,165)
                                             else f"Участие: {state['count']}/20")
        bot.research_funded.side_effect=lambda: recommended_funded and state['selected']=='рекомендованная'
        bot.research_in_progress.return_value=False
        def donate(*args):
            state['count']=0
            return 1
        bot.donate_current_research.side_effect=donate
        return bot

    def test_recommendation_receives_donation_before_other_nodes(self):
        bot=self.donation_bot(False)
        with patch('alliance_research.pan',return_value=False), patch('alliance_research.nodes',return_value=[
            (100,300,True,b'a'),(400,300,False,b'b')]):
            self.assertEqual(donate_all(bot),1)
        bot.donate_current_research.assert_called_once_with('рекомендованная',20)

    def test_funded_recommendations_fall_back_to_other_technologies(self):
        bot=self.donation_bot(True)
        with patch('alliance_research.pan',return_value=False), patch('alliance_research.nodes',return_value=[
            (100,300,True,b'a'),(400,300,False,b'b')]):
            self.assertEqual(donate_all(bot),1)
        bot.donate_current_research.assert_called_once_with('другая',20)
        visited=[call.args for call in bot.tap.call_args_list if call.args in ((100,300),(400,300))]
        self.assertEqual(visited,[(100,300)]*5+[(400,300)])

    def test_recommended_home_price_is_read_from_real_frame(self):
        bot=Bot()
        bot.frame=cv2.imdecode(np.fromfile(ROOT/'alliance-recommended-home.png',np.uint8),1)
        bot.require=Mock()
        bot.require_resource_button()
