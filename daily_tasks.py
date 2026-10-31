"""Daily actions using the game's own task navigation and verified queues."""
import re

from bot import Paused, norm


TASK_ICONS = {
    # Task names are distinct; the generic stopwatch also appears on campaign refills.
    'materials': ((980, 568, 1180, 628), 'произведите'),
    'building': ((394, 568, 548, 628), 'улучшите строение'),
    'research': ((650, 570, 900, 606), 'исследование'),
    'speedup': ((1290, 569, 1472, 606), 'ускорение'),
    'raven': ((1570, 568, 1795, 628), 'одолейте силы'),
    'recruit': ((348, 939, 594, 975), 'завербуйте юнит'),
    'assemble': ((651, 939, 893, 975), 'соберите юнит'),
    'upgrade': ((955, 938, 1200, 975), 'улучшите юнит'),
    'modify': ((1258, 936, 1498, 998), 'модифицируйте юнит'),
    'campaign': ((1590, 939, 1778, 975), 'кампания'),
    'officer_xp': ((672, 939, 887, 998), 'используйте опыт офицера'),
    'campaign_refill': ((1272, 568, 1473, 628), 'пополнения кампании'),
    'campaign_speedup': ((1540, 568, 1810, 628), 'ускорьте прохождение кампании'),
}
TASK_SOURCES = {key: 'daily-extra-tasks.png' for key in ('officer_xp', 'campaign_refill', 'campaign_speedup')}


def task_point(bot, rectangle, filename='daily-claim.png'):
    for page in range(3):
        bot.daily_screen()
        point = bot.optional_template(filename, rectangle, (325, 380, 1830, 1030))
        if point:
            width, height = rectangle[2] - rectangle[0], rectangle[3] - rectangle[1]
            x, y = point
            title = bot.frame[y-height//2:y+(height+1)//2, x-width//2:x+(width+1)//2]
            # The game greys claimed cards. Normalized template matching ignores this tint.
            if not title.size or (title.max(axis=2) < 130).sum() < 8:
                return None
            return point
        if page == 2:
            break
        before = bot.frame[380:1030, 325:1830].copy()
        bot.command('-s', bot.serial, 'shell', 'input', 'swipe', '1450', '960', '1450', '430', '400')
        bot.wait(.7)
        bot.observe()
        bot.daily_screen()
        if abs(bot.frame[380:1030, 325:1830].astype('int16') - before).mean() < .5:
            break
    return None


def task_remaining(text):
    found = re.search(r'\((\d+)/(\d+)\)', re.sub(r'\s+', '', text))
    if not found or not 0 <= int(found[1]) <= int(found[2]) <= 20:
        return None
    return int(found[2]) - int(found[1])


def open_task(bot, key, navigate=True):
    bot.main()
    bot.tap(74, 699)
    bot.mission_screen()
    bot.tap(165, 350)
    bot.daily_screen()
    bot.daily_top()
    bot.daily_task_rewards()
    rectangle, title = TASK_ICONS[key]
    point = task_point(bot, rectangle, TASK_SOURCES.get(key, 'daily-claim.png'))
    if point is None:
        bot.log(f'Ежедневное «{title}»: доступная карточка не найдена после проверки списка')
        bot.tap(1814, 108)
        bot.main()
        return None
    bot.tap(*point)  # The actual label position also works after scrolling the cards.
    bot.require('о миссии', title)
    text = bot.text((735, 300, 1420, 400))
    remaining = task_remaining(text)
    if remaining is None:
        text = bot.detail((745, 300, 1420, 400))
        remaining = task_remaining(text)
    if remaining is None:
        bot.log(f'Ежедневное «{title}»: счётчик не прочитан; действие пропущено')
        bot.require('о миссии', title)
        bot.tap(1410, 200)
        bot.daily_screen()
        bot.tap(1814, 108)
        bot.main()
        return None
    if not remaining or not navigate:
        bot.tap(1410, 200)
        bot.daily_screen()
        bot.tap(1814, 108)
        bot.main()
        return remaining
    bot.click('вперед', (700, 650, 1220, 830))
    bot.wait(1)
    bot.observe()
    return remaining


def factory_queue(bot):
    text = norm(bot.detail((90, 230, 400, 300)))
    found = re.search(r'очередь\s*:\s*(\d+)\s*/\s*(\d+)', text)
    if not found or not 0 <= int(found[1]) <= int(found[2]) <= 100:
        raise Paused('Очередь производства не распознана: ' + text)
    return int(found[1]), int(found[2])


def produce_materials(bot):
    remaining = open_task(bot, 'materials')
    if not remaining:
        return
    bot.template('daily-material-target.png', (824, 593, 1098, 623), (700, 500, 1200, 700))
    bot.require('произвести')
    bot.click('произвести', (1000, 620, 1240, 790))
    bot.require('агрегатный завод', 'производство')
    bot.tap(180, 175)  # Only the first workshop; existing jobs are left alone.
    queued, capacity = factory_queue(bot)
    if queued:
        bot.log(f'Материалы: уже в очереди {queued}; проверю готовность в следующем проходе')
    else:
        bot.tap(1460, 320)
        if 'доска' not in bot.detail((1310, 500, 1640, 575)):
            raise Paused('Не подтверждено производство досок')
        # Selecting an already highlighted material can enqueue it immediately.
        for _ in range(max(0, min(remaining, 3, capacity) - factory_queue(bot)[0])):
            before, _ = factory_queue(bot)
            bot.click('производство', (1200, 830, 1740, 1000))
            after, _ = factory_queue(bot)
            if after != before + 1:
                raise Paused('Добавление материала не подтверждено очередью')
            bot.log(f'Доска добавлена в производство; очередь {after}/{capacity}')
    bot.back()
    bot.main()


def run_daily(bot, send_officers=False, skip_materials=False):
    if not skip_materials:
        produce_materials(bot)
    else:
        bot.log('Ежедневное производство выполняется по пользовательским схемам мастерских')
    # Building upgrades are excluded by the user; personal technologies run separately.
    from emergency import local_recover
    for action in (recruit_unit,speedup_research,upgrade_unit,modify_unit,use_officer_xp,campaign_supply_tasks,defeat_raven,assemble_daily_unit):
        try:
            action(bot)
        except Paused as error:
            if bot.stop.is_set(): raise
            bot.log(f'Ежедневное {action.__name__}: {error}; проверяю оставшиеся задания')
            if not local_recover(bot): raise
    bot.mission_rewards(send_officers=send_officers)


def assemble_daily_unit(bot):
    if not open_task(bot,'assemble'):
        return
    bot.tap(*bot.template('assembly-daily-shortcut.png',(1060,660,1160,752)))
    bot.require('сборка','выберите юнит для сборки')
    # Only the recorded three identical, untrained four-star guns are combined.
    for x in (1010,1260,1500):
        if bot.optional_template('assembly-daily-list.png',(920,210,1120,370),
                                 (x-115,195,x+120,380)) is None:
            bot.log('Ежедневная сборка: три подходящих одинаковых юнита не подтверждены')
            bot.tap(120,45); bot.main()
            return
    bot.tap(1010,280)
    bot.require('добавьте юнит для сборки')
    bot.tap(1260,280); bot.tap(1500,280)
    bot.template('assembly-daily-confirm.png',(195,910,780,1040),(180,890,795,1060))
    bot.click('собрать',(1170,890,1600,1030))
    bot.wait(2); bot.observe()
    bot.template('assembly-daily-result.png',(85,720,350,900),(65,700,375,920))
    bot.back()
    bot.require('сборка')
    bot.tap(120,45); bot.main()
    bot.log('Ежедневная сборка: leFH 18 собрана из трёх leFH 16; результат подтверждён')


def campaign_supply_tasks(bot):
    regular = open_task(bot, 'campaign_refill', navigate=False)
    quick = open_task(bot, 'campaign_speedup', navigate=False)
    if not regular and not quick:
        return
    bot.enter_campaign()
    if regular:
        bot.tap(580, 865)
        bot.wait(1.2)
        bot.observe()
        bot.template('campaign-refill-popup.png', (484, 187, 902, 227), (465, 170, 925, 245))
        bot.require('текущие награды')
        bot.click('получить', (750, 720, 1170, 845))
        bot.require('скорость пополнения')
        bot.log('Получено обычное пополнение кампании; следующая проверка в очередном проходе')
    if quick:
        bot.tap(1325, 865)
        bot.wait(1)
        bot.observe()
        bot.require('быстрое пополнение', 'попыток за день')
        if bot.has('бесплатно', (750, 690, 1170, 820)):
            bot.click('бесплатно', (750, 690, 1170, 820))
            bot.wait(1)
            bot.observe()
            bot.confirm_rewards()
            bot.require('скорость пополнения')
            bot.log('Бесплатное быстрое пополнение кампании получено')
        else:
            bot.log('Быстрое пополнение: бесплатной попытки нет; платная кнопка пропущена')
            bot.tap(1410, 200)
            bot.require('скорость пополнения')
    bot.tap(100, 50)
    bot.main()


def officer_xp_count(bot):
    text = re.sub(r'\s+', '', bot.detail((461, 454, 513, 480)))
    if not re.fullmatch(r'\d{1,6}',text):
        text=re.sub(r'\s+','',bot.detail((450,440,520,490))).lstrip('—-_:')
    if not re.fullmatch(r'\d{1,6}', text):
        raise Paused('Количество базовых книг опыта офицера не распознано')
    return int(text)


def use_officer_xp(bot):
    remaining = open_task(bot, 'officer_xp')
    if not remaining:
        return
    if remaining > 3:
        raise Paused('Неожиданный счётчик задания опыта офицера')
    bot.main()
    bot.tap(1135, 1023)
    bot.wait(1)
    bot.observe()
    bot.require('офицеры', 'навыки офицера')
    portrait = None
    # The officer list keeps its previous scroll position between visits.
    for start, end in ((900, 300), (300, 900)):
        for page in range(8):
            bot.require('офицеры', 'навыки офицера')
            portrait = bot.optional_template('officer-paul-current.png', (280, 480, 350, 550),
                                              (50, 200, 400, 965))
            if portrait:
                break
            bot.command('-s', bot.serial, 'shell', 'input', 'swipe', '220', str(start), '220', str(end), '350')
            bot.wait(.7)
            bot.observe()
        if portrait:
            break
    if portrait is None:
        bot.log('Опыт офицера: Аарон Мэтьюз не найден в списке; пропущено')
        bot.tap(120, 45)
        bot.main()
        return
    bot.tap(*portrait)
    bot.template('officer-paul-current.png', (1335, 358, 1518, 388), (1300, 340, 1570, 405))
    bot.tap(1810, 480)
    bot.require('повышение офицера', 'базовый опыт офицера')
    bot.template('officer-xp-items.png', (415, 370, 493, 393), (395, 352, 520, 410))
    for _ in range(remaining):
        before = officer_xp_count(bot)
        if not before:
            bot.log('Опыт офицера: базовые книги закончились')
            break
        bot.template('officer-xp-items.png', (535, 414, 890, 443), (520, 395, 920, 465))
        bot.click('исп.', (1340, 380, 1540, 480))
        bot.wait(1)
        bot.observe()
        bot.require('повышение офицера', 'базовый опыт офицера')
        if officer_xp_count(bot) != before - 1:
            raise Paused('Использование одной базовой книги опыта не подтверждено')
        bot.log(f'Аарон Мэтьюз: использована одна базовая книга 10 000 опыта; осталось {before - 1}')
    bot.tap(1536, 110)
    bot.require('офицеры', 'навыки офицера')
    bot.tap(120, 45)
    bot.main()


def resource_amounts(text):
    """Read three separate ordinary-resource amounts; reject partial OCR."""
    values = re.findall(r'(?<![\w.,])(\d+(?:[.,]\d+)?)\s*([mмkк]?)(?![\w.,])', norm(text))
    if len(values) != 3:
        raise Paused('Три стоимости ресурсов не распознаны однозначно')
    return [round(float(number.replace(',', '.')) *
                  (1000000 if suffix in ('m', 'м') else 1000 if suffix in ('k', 'к') else 1))
            for number, suffix in values]


def building_materials(text):
    values = re.findall(r'(\d+)/(\d+)', re.sub(r'[ \t]+', '', text))
    if len(values) not in (3, 4):
        raise Paused('Количество строительных материалов не распознано')
    return [(int(available), int(cost)) for available, cost in values]


def upgrade_selected_building(bot):
    bot.require('улучшение построек', 'стоимость материалов', 'стоимость ресурсов')
    title = bot.text((1090, 115, 1790, 190))
    header = re.search(r'(ангар\s+[1-5]|командный пункт)\s+ур\.?\s*(\d+).*?[>»›]+\s*(\d+)', title)
    if not header or int(header[3]) != int(header[2]) + 1:
        bot.log('Строительство: название и следующий уровень не прочитаны; отложено')
        bot.back()
        bot.main()
        return False
    materials = building_materials(bot.detail((1100, 652, 1810, 706)))
    if not all(available >= cost > 0 and cost <= 500 for available, cost in materials):
        bot.log(f'Строительство «{header[1]}»: не хватает строительных материалов; отложено')
        bot.back()
        bot.main()
        return False
    costs = resource_amounts(bot.detail((1100, 800, 1840, 865)))
    treasury = resource_amounts(bot.detail((1100, 10, 1635, 75)))
    points = re.search(r'очки строительства\s*:\s*(\d+)\s*/\s*(\d+)', bot.text())
    affordable = (all(available >= cost > 0 and cost <= 500 for available, cost in materials)
                  and all(0 < cost <= 5000000 and stock >= cost for stock, cost in zip(treasury, costs))
                  and (not bot.has('требуемые очки строительства')
                       or (points is not None and int(points[1]) >= int(points[2]))))
    if not affordable:
        bot.log(f'Строительство «{header[1]}»: не хватает материалов/ресурсов/очков или превышен лимит; отложено')
        bot.back()
        bot.main()
        return False
    bot.click('улучшить', (1260, 920, 1700, 1040))
    bot.wait(1.5)
    bot.observe()
    bot.main()
    bot.tap(960, 520)
    actual = bot.detail((600, 480, 1400, 700))
    if not re.search(re.escape(header[1]) + r'\s+ур\.?\s*' + header[3] + r'\b', actual):
        raise Paused('Улучшение постройки не подтверждено новым уровнем')
    bot.log(f'Строительство подтверждено: {header[1]}, уровень {header[2]} → {header[3]}')
    bot.back()
    bot.main()
    return True


def upgrade_building(bot):
    if not open_task(bot, 'building'):
        return
    bot.main()
    bot.tap(*bot.template('daily-hangar-target.png', (846, 727, 901, 780), (700, 650, 1050, 850)))
    if upgrade_selected_building(bot):
        return
    # The daily shortcut points to HQ even when a smaller recommended upgrade is affordable.
    bot.tap(74, 699)
    bot.mission_screen()
    bot.tap(165, 230)
    bot.mission_screen()
    rows = [line for line in bot.lines if bot.in_region(line, (490, 520, 1500, 1000))
            and re.search(r'повысьте уровень ангара\s+[1-5]\s+до\s+\d+', norm(line['text']))]
    if not rows:
        bot.log('Строительство: доступного рекомендованного ангара нет')
        bot.tap(1814, 108)
        bot.main()
        return
    y = min(word['y'] for word in rows[0]['words'])
    bot.click('вперед', (1600, y - 10, 1820, min(y + 120, 1030)))
    bot.wait(1)
    bot.observe()
    bot.main()
    bot.tap(*bot.template('daily-hangar-target.png', (846, 727, 901, 780), (700, 650, 1050, 850)))
    upgrade_selected_building(bot)


def recruit_unit(bot):
    if not open_task(bot, 'recruit'):
        return
    bot.template('daily-recruit-target.png', (1008, 698, 1102, 778), (900, 600, 1220, 900))
    bot.tap(1058, 745)
    bot.require('ящики', 'наземные и воздушные силы')
    # The game remembers the last crate, which may require unavailable gold tickets.
    bot.tap(200,225)
    bot.require('ящики', 'наземные и воздушные силы')
    # One ordinary silver ticket only. A gold purchase has a different currency icon.
    ticket = bot.optional_template('daily-recruit-menu.png', (903, 918, 976, 965), (880, 900, 1000, 980))
    if ticket is None:
        bot.log('Вербовка: обычный билет не подтверждён; покупка пропущена')
        bot.back()
        bot.main()
        return
    bot.tap(932, 890)
    bot.wait(2)
    bot.observe()
    bot.require('ок')
    bot.click('ок', (500, 900, 920, 1060))
    bot.require('ящики')
    bot.back()
    bot.main()
    bot.log('Вербовка выполнена за один обычный билет')


def inventory_cost(text, maximum, require_available=True):
    found = re.search(r'(\d+)/(\d+)$', re.sub(r'\s+', '', text))
    if not found:
        raise Paused('Количество и стоимость предметов не распознаны')
    available, cost = int(found[1]), int(found[2])
    return (available, cost) if 1 <= cost <= maximum and (not require_available or available >= cost) else None


def modify_unit(bot):
    if not open_task(bot, 'modify'):
        return
    bot.main()
    bot.tap(1305, 1023)
    bot.require('наземные войска')
    point = bot.optional_template('daily-unit-list.png', (1635, 481, 1766, 516),
                                   (380, 200, 1880, 1050))
    if point is None:
        bot.log('Модификация: БМ-24 не найден в видимой части списка')
        bot.back()
        bot.main()
        return
    bot.tap(*point)
    bot.template('daily-bm-modify.png', (209, 24, 341, 64), (195, 10, 370, 85))
    bot.click('модифицировать', (25, 350, 325, 445))
    bot.require('разброс огня', 'маневр передачи')
    bot.tap(1213, 467)
    bot.require('реактивная установка', 'катюша')
    bot.template('daily-bm-modify-cost.png', (695, 568, 732, 610), (660, 550, 770, 625))
    values = inventory_cost(bot.text((680, 560, 910, 615)), 200)
    if values is None:
        bot.log('Модификация БМ-24: цена выше 200 деталей или не хватает предметов; пропущено')
    else:
        available, cost = values
        bot.click('модифицировать', (595, 620, 980, 725))
        bot.wait(1)
        bot.observe()
        after = inventory_cost(bot.text((680, 560, 910, 615)), 1000000, require_available=False)
        if after is None or after[0] != available - cost:
            raise Paused('Одна модификация не подтверждена списанием деталей')
        bot.log(f'БМ-24: «Разброс огня» улучшен за {cost} деталей')
    bot.tap(1080, 900)
    bot.back()
    bot.require('наземные войска')
    bot.back()
    bot.main()


def speedup_research(bot):
    if not open_task(bot, 'speedup', navigate=False):
        return
    if not open_task(bot, 'research'):
        return
    # The daily shortcut opens the active research building, then its technology view.
    point = bot.optional_template('daily-research-target.png', (1015, 721, 1077, 781),
                                   (950, 670, 1150, 830))
    if point is None:
        bot.log('Ускорение: нет подтверждённого исследовательского центра; пропущено')
        bot.main()
        return
    bot.tap(*point)
    if not bot.has('ускорение', (770, 960, 935, 1050)):
        bot.log('Ускорение: активного исследования нет')
        bot.back()
        bot.main()
        return
    bot.click('ускорение', (770, 960, 935, 1050))
    bot.require('ускорение', 'исследование завершится')
    bot.template('daily-speedup-menu.png', (252, 497, 324, 522), (220, 480, 345, 540))
    point = bot.template('daily-speedup-menu.png', (1535, 527, 1667, 582), (1500, 500, 1710, 620))
    bot.tap(*point)  # Exactly one one-minute item; never the gold or bulk button.
    bot.require('ускорение', 'исследование завершится')
    bot.tap(1695, 105)
    bot.back()
    bot.main()
    bot.log('Применён один минутный предмет ускорения исследования')


def unit_level(text):
    found = re.search(r'уровень\s+(\d+)\s*/\s*(\d+)', norm(text))
    if not found or not 1 <= int(found[1]) <= int(found[2]) <= 200:
        raise Paused('Уровень юнита не распознан')
    return int(found[1]), int(found[2])


def upgrade_unit(bot):
    if not open_task(bot, 'upgrade'):
        return
    bot.main()
    bot.tap(1305, 1023)
    bot.require('наземные войска')
    point = bot.optional_template('daily-unit-list.png', (835, 600, 1060, 731), (380, 200, 1880, 1050))
    if point is None:
        bot.log('Улучшение: СУ-100М не найден в видимой части списка')
        bot.back()
        bot.main()
        return
    bot.tap(*point)
    bot.require('су-100м', 'уровень')
    before, maximum = unit_level(bot.text())
    cost = re.search(r'/\s*(\d+)\s*$', bot.text((1500, 850, 1800, 910)))
    ordinary_xp = bot.optional_template('daily-unit-detail.png', (1534, 864, 1573, 904),
                                       (1500, 840, 1610, 916))
    if before >= maximum or not ordinary_xp or not cost or not 1 <= int(cost[1]) <= 1000:
        bot.log('Улучшение: нужен переход ранга или больше 1000 опыта; пропущено')
    else:
        bot.click('улучшение', (1400, 910, 1830, 1030))
        bot.wait(1)
        bot.observe()
        after, _ = unit_level(bot.text())
        if after != before + 1:
            raise Paused('Повышение уровня СУ-100М не подтверждено')
        bot.log(f'СУ-100М: уровень {before} → {after}, стоимость {cost[1]} опыта')
    bot.back()
    bot.require('наземные войска')
    bot.back()
    bot.main()


def raven_target_ready(bot):
    return (bot.optional_template('daily-raven-panel.png', (196, 318, 504, 346),
                                  (160, 290, 535, 375)) is not None
            and bot.has('очевидное преимущество', (110, 630, 660, 695)))


def defeat_raven(bot):
    for _ in range(5):
        remaining = open_task(bot, 'raven')
        if not remaining:
            return
        if remaining > 5:
            raise Paused('Неожиданная цель ежедневного боя «Ворона»')
        bot.wait(1.2)  # The task shortcut keeps moving the camera after the map appears.
        bot.observe()
        bot.main()
        bot.tap(960, 520)
        if not raven_target_ready(bot):
            bot.main()
            bot.tap(1300, 600)
            bot.log('Бой «Ворона»: нет подтверждённого полевого подразделения уровня 1 с преимуществом; пропущено')
            return
        bot.tap(*bot.template('daily-raven-panel.png', (836, 700, 898, 755), (780, 650, 960, 810)))
        bot.wait(8)
        bot.observe()
        bot.main()
        after = open_task(bot, 'raven', navigate=False)
        if after is None or after >= remaining:
            bot.log('Бой «Ворона»: прогресс пока не подтверждён; новые атаки отложены до следующего прохода')
            return
        bot.log(f'Бой «Ворона» подтверждён заданием: осталось {remaining} → {after}')
        if not after:
            return
