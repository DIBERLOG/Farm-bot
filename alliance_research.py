"""Visit recommended alliance technologies first, then the other unlocked nodes."""
import re
import cv2
import numpy as np


def nodes(bot):
    from bot import ROOT
    hsv = cv2.cvtColor(bot.frame, cv2.COLOR_BGR2HSV)
    mask = cv2.inRange(hsv, np.array([35,40,35]), np.array([179,240,210]))
    mask |= cv2.inRange(hsv, np.array([0,60,35]), np.array([10,240,210]))
    _, _, stats, _ = cv2.connectedComponentsWithStats(mask)
    reference = cv2.imdecode(np.fromfile(ROOT/'alliance-tree-current.png', np.uint8), 1)
    thumb = reference[201:247,21:65]
    result = []
    for x,y,w,h,area in stats[1:]:
        shape = (65 < w < 220 and 60 < h < 200) or (250 < w < 420 and 140 < h < 240)
        if not (shape and area > 1800 and 210 < y < 820):
            continue
        cx, cy = int(x+w/2), int(y+h/2)
        if not 65 < cx < 1820:
            continue
        status = (cx-95, cy+30, cx+95, cy+100)
        if bot.has('макс', status):
            continue
        crop = bot.frame[max(190,cy-100):cy+10, max(0,cx-120):cx-35]
        recommended = (crop.shape[0] >= thumb.shape[0] and crop.shape[1] >= thumb.shape[1]
                       and cv2.minMaxLoc(cv2.matchTemplate(crop,thumb,cv2.TM_CCOEFF_NORMED))[1] > .8)
        icon = cv2.resize(cv2.cvtColor(bot.frame[y:y+h,x:x+w],cv2.COLOR_BGR2GRAY),(12,12))
        key = (icon > icon.mean()).tobytes()
        result.append((cx,cy,recommended,key))
    return sorted(result, key=lambda node: (not node[2], node[0], node[1]))


def pan(bot, right=False):
    bot.require('исследования альянса')
    anchors = sorted((x,y) for x,y,_,_ in nodes(bot))
    before = cv2.resize(bot.frame[210:850], (96,40)).astype(float)
    start, end = (450,1450) if right else (1450,450)
    bot.command('-s',bot.serial,'shell','input','swipe',str(start),'500',str(end),'500','450')
    bot.wait(.7)
    bot.observe()
    moved = sorted((x,y) for x,y,_,_ in nodes(bot))
    if len(anchors) == len(moved) and all(abs(x-a)<8 and abs(y-b)<8
                                        for (x,y),(a,b) in zip(anchors,moved)):
        return False
    after = cv2.resize(bot.frame[210:850], (96,40)).astype(float)
    return np.abs(before-after).mean() > 1.5


def donate_all(bot):
    from bot import Paused, donation_count
    donated = 0
    seen = set()
    # The recommendation may be in any of the five categories, not just Development.
    for recommended_only in (True, False):
        for category, tab in [('альянс',365),('развитие',145),('война',582),('территория',800),('навыки',1010)]:
            bot.tap(tab,140)
            bot.require('исследования альянса')
            for _ in range(8):
                if not pan(bot,right=True):
                    break
            for page in range(8):
                for x,y,recommended,key in nodes(bot):
                    identity = (category,key)
                    if identity in seen or recommended != recommended_only:
                        continue
                    seen.add(identity)
                    bot.tap(x,y)
                    name = re.split(r'\s+ур\.?',bot.text((350,80,1480,165)))[0].strip()
                    try:
                        if bot.research_funded() or bot.research_in_progress():
                            bot.log(f'«{name}»: профинансировано или изучается; проверяю следующую технологию')
                            continue
                        if not bot.has('награды за вклад'):
                            bot.log(f'«{name}»: пожертвование недоступно; проверяю следующую технологию')
                            continue
                        count = donation_count(bot.text((1000,820,1440,883)))
                        if count == 0:
                            return donated
                        try:
                            bot.require_resource_button()
                        except Paused as error:
                            bot.log(f'«{name}»: {error}; проверяю следующую технологию')
                            continue
                        bot.log(f'Пожертвования: {"приоритет по лайку" if recommended else "другая доступная технология"} · {name}')
                        donated += bot.donate_current_research(name,20-donated)
                        if donated >= 20 or donation_count(bot.text((1000,820,1440,883))) == 0:
                            return donated
                    finally:
                        bot.tap(1536,110)
                        bot.require('исследования альянса')
                if not pan(bot):
                    break
            else:
                raise Paused(f'Дерево «{category}» не закончилось после восьми страниц')
    return donated
