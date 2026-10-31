"""Ordinary personal technologies, in tree order; never cancel or buy a queue."""
import re

from bot import Paused, ROOT, norm
from daily_tasks import resource_amounts


def upgrade_header(text):
    match = re.fullmatch(r'(.+?)\s+ур\.?\s*(\d+)\s*[>»›]+\s*(\d+)\s*[iі]?', norm(text))
    if match and int(match[3]) == int(match[2]) + 1:
        return match[1], int(match[2]), int(match[3])
    return None


def cost_number(text):
    value = re.sub(r'\s+', '', norm(text)).translate(str.maketrans('збoо', '3600'))
    match = re.fullmatch(r'(\d+(?:[.,]\d+)?)([mмkк]?)', value)
    if not match:
        raise Paused('Стоимость технологии не прочитана')
    return round(float(match[1].replace(',', '.')) * (1000000 if match[2] in ('m', 'м') else 1000 if match[2] in ('k', 'к') else 1))


def tree_points(lines):
    """Labels sit below their nodes. Group wrapped captions before selecting a node."""
    result = []
    for line in sorted(lines, key=lambda row: min((w['y'] for w in row['words']), default=9999)):
        text = norm(line['text'])
        words = line['words']
        if not words or not re.search(r'[а-я]{5}', text) or text in ('макс.', 'исследование', 'ускорение'):
            continue
        x = round((min(w['x'] for w in words) + max(w['x'] + w['width'] for w in words))/2)
        y = min(w['y'] for w in words)
        if not (85 <= x <= 1810 and 250 <= y <= 900):
            continue
        if any(abs(x-old_x) < 100 and abs(y-old_y) < 85 for old_x, old_y in result):
            continue
        result.append((x, y))
    return [(x, y-85) for x, y in sorted(result, key=lambda p: (round(p[0]/120), p[1]))]


def start_selected(bot):
    title = bot.text((350, 90, 1250, 155))
    upgrade = upgrade_header(title)
    if not upgrade:
        bot.wait(.8)
        bot.observe()
        upgrade = upgrade_header(bot.text((350, 85, 1485, 155)))
    if not upgrade:
        bot.log('Технология уже завершена или её следующий уровень не распознан; пропускаю')
        return False
    if bot.has('требования') or bot.has('недостаточно') or bot.has('очередь занята'):
        return False
    # The left gold instant button and the paid second queue are never used.
    if not bot.optional_template('technology-dialog.png', (1009, 886, 1410, 997), (985, 870, 1440, 1010)):
        bot.log(f'«{upgrade[0]}»: обычная кнопка исследования недоступна')
        return False
    try:
        try:
            costs = resource_amounts(bot.text((710, 750, 1230, 825)))
        except Paused:
            costs = [cost_number(bot.detail(region)) for region in
                     ((775, 765, 870, 815), (948, 765, 1037, 815), (1117, 765, 1214, 815))]
    except Paused:
        bot.log(f'«{upgrade[0]}»: стоимость не прочитана; пропускаю')
        return False
    try:
        stock_text = bot.text((1100, 0, 1650, 80))
        if re.search(r'[^\d\s.,mмkк]', stock_text):
            raise Paused('Значки ресурсов попали в текст запасов')
        stock = resource_amounts(stock_text)
    except Paused:
        # The game marks unaffordable costs red. Do not guess a garbled stock total.
        pixels = bot.frame[760:820, 770:1220].astype('int16')
        red = (pixels[:, :, 2] > pixels[:, :, 1]+45) & (pixels[:, :, 2] > pixels[:, :, 0]+45)
        if red.sum() > 15:
            return False
        stock = [float('inf')]*3
    if not all(0 < price <= available for price, available in zip(costs, stock)):
        bot.log(f'«{upgrade[0]}»: не хватает обычных ресурсов')
        return False
    bot.tap(1205, 942)
    # Newly started jobs show Help before the usual Speed up button.
    confirmed = False
    for _ in range(3):
        active = (bot.has('помощь', (770, 960, 935, 1050))
                  or bot.has('ускорение', (770, 960, 935, 1050)))
        # The queue alternates its caption between the technology name and remaining time.
        if active and (bot.has(upgrade[0], (330, 950, 770, 1060))
                       or re.search(r'\d+\s*(?:д\.|ч\.|мин\.|сек\.)', bot.text((460, 950, 770, 1060)))
                       or (bot.has('подписать контракт', (1000, 950, 1410, 1060))
                           and not bot.optional_template('technology-dialog.png', (1510,85,1565,135), (1490,70,1585,150)))):
            confirmed = True
            break
        bot.wait(.7)
        bot.observe()
    if not confirmed:
        raise Paused('Запуск технологии не подтверждён активной очередью')
    bot.back()
    bot.require('техн.')
    if not (bot.has('ускорение', (320, 945, 960, 1060))
            or bot.has('помощь', (320, 945, 960, 1060))):
        raise Paused('Запуск технологии не подтверждён кнопкой активной очереди')
    bot.log(f'Исследование запущено: {upgrade[0]}, уровень {upgrade[1]} → {upgrade[2]}')
    return True


def run(bot):
    bot.main()
    bot.tap(75, 337)
    bot.tap(155, 520)
    if not bot.has('техн.', (200, 190, 400, 260)) and 'техн' not in bot.detail((210, 205, 330, 260)):
        raise Paused('Не распознана вкладка личных технологий')
    if bot.has('получить', (700, 270, 930, 390)) and bot.has('готово', (330, 270, 700, 390)):
        bot.click('получить', (700, 270, 930, 390))
        bot.require('техн.')
        bot.log('Завершённое личное исследование получено')
    # Claiming a finished job opens categories directly; an idle queue opens them via its button.
    if not bot.has('техн.', (180, 0, 500, 100)):
        if not bot.has('исследование', (700, 270, 930, 390)):
            active = (bot.has('ускорение', (700, 270, 930, 390))
                      or bot.has('помощь', (700, 270, 930, 390))
                      or bot.has('показать', (700, 270, 930, 390))
                      or re.search(r'\d+\s*(?:д\.|ч\.|мин\.|сек\.)', bot.text((220, 270, 930, 390))))
            if not active:
                raise Paused('Состояние исследовательской очереди не прочитано')
            bot.log('Личное исследование уже идёт; дождусь свободной очереди')
            bot.back()
            bot.main()
            return
        bot.template('technology-overview.png', (235, 292, 420, 363), (210, 270, 470, 390))
        bot.click('исследование', (700, 270, 930, 390))
        bot.require('техн.')
    # All ordinary categories, left to right. Locked branches have no researched/total count.
    seen_categories = set()
    for category_page in range(4):
        categories = []
        for line in bot.lines:
            match = re.fullmatch(r'(\d{1,4})/(\d{1,4})', norm(line['text']))
            if match and int(match[1]) < int(match[2]) and bot.in_region(line, (180, 450, 1850, 930)):
                words = line['words']
                x = round((min(w['x'] for w in words)+max(w['x']+w['width'] for w in words))/2)
                y = min(w['y'] for w in words)
                key = (int(match[1]), int(match[2]))
                if key not in seen_categories:
                    categories.append((x, y-150, key))
        for x, y, key in sorted(categories):
            seen_categories.add(key)
            bot.tap(x, y)
            if bot.has('техн.', (180, 0, 500, 100)):
                continue
            for page in range(16):
                points = tree_points(bot.lines)
                before = bot.frame.copy()
                for point in points:
                    bot.tap(*point)
                    # A real technology dialog has both ordinary and instant research controls.
                    if bot.optional_template('technology-dialog.png', (1510, 85, 1565, 135), (1490, 70, 1585, 150)):
                        if start_selected(bot):
                            bot.back()
                            bot.main()
                            return
                        bot.tap(1536, 110)
                bot.command('-s', bot.serial, 'shell', 'input', 'swipe', '1600', '850', '420', '850', '550')
                bot.wait(.7)
                bot.observe()
                if abs(bot.frame[180:930].astype('int16')-before[180:930]).mean() < 1:
                    break
            bot.back()
            bot.require('техн.')
        bot.command('-s', bot.serial, 'shell', 'input', 'swipe', '1600', '650', '450', '650', '550')
        bot.wait(.7)
        bot.observe()
        bot.require('техн.')
    bot.back()
    bot.main()
    bot.log('Доступные технологии проверены: подходящее исследование пока не найдено')
