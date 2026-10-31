"""Check the five land barracks; only use explicit replenishment controls."""
import re
import json


def load_groups():
    from bot import ROOT
    path = ROOT / 'army-options.json'
    if not path.exists():
        return False
    value = json.loads(path.read_text(encoding='utf-8'))['join_groups']
    if not isinstance(value, bool):
        raise ValueError('Автовступление: ожидается переключатель включено/выключено')
    return value


def save_groups(enabled):
    from bot import ROOT
    if not isinstance(enabled, bool):
        raise ValueError('Автовступление: ожидается переключатель включено/выключено')
    path = ROOT / 'army-options.json'
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps({'join_groups': enabled}), encoding='utf-8')
    temporary.replace(path)


def join_groups(bot):
    from bot import Paused
    bot.main()
    bot.tap(1646, 1023)
    bot.require('инфо', 'участники')
    bot.tap(1040, 780)
    bot.require('группы армий', 'флот альянса')
    try:
        for top in (290, 660):
            caption = bot.text((920, top, 1340, top+135))
            match = re.search(r'сформирована\s*:\s*(\d+)\s*/\s*(\d+)', caption)
            if not match:
                caption = bot.detail((920, top, 1340, top+135))
                match = re.search(r'сформирована\s*:\s*(\d+)\s*/\s*(\d+)', caption)
            if not match:
                continue
            current, capacity = map(int, match.groups())
            if not 0 <= current < capacity:
                continue
            x, y = 1505, top+88
            blue, green, red = bot.frame[y-25:y-15, x-30:x+30].mean(axis=(0, 1))
            if blue <= red+15 or blue <= green:
                continue
            bot.tap(x, y)
            if bot.has('покинуть') or bot.has('выйти из группы'):
                bot.log('Группа армий: вступление подтверждено')
                return
            raise Paused('Группа армий: нажато «Вступить», результат требует проверки; повторно не нажимаю')
        bot.log('Группы армий: свободных мест с доступной кнопкой вступления нет')
    finally:
        if bot.has('группы армий') and bot.has('флот альянса'):
            bot.tap(120, 45)
            bot.require('инфо', 'участники')
            bot.tap(120, 45)
            bot.main()


def refill(bot):
    from bot import Paused, ROOT
    if not (bot.has('наземные войска') and bot.has('казарма')):
        bot.main()
        bot.click('армия', (1700, 980, 1920, 1080))
    bot.require('наземные войска', 'казарма')
    bot.click('наземные войска', (870, 10, 1180, 100))
    bot.require('наземные войска', 'казарма')
    for number in range(5):
        top = 100 + number * 170
        region = (1500, top + 40, 1880, top + 165)
        title = bot.text((1550, top, 1880, top + 55))
        count = re.search(r'казарма\s*:\s*(\d+)\s*/\s*(\d+)', title)
        if not count:
            title = bot.detail((1500, top, 1900, top + 55))
            count = re.search(r'казарма\s*:\s*(\d+)\s*/\s*(\d+)', title)
        if not count:
            raise Paused(f'Армия: не прочитана численность казармы №{number + 1}')
        current, capacity = map(int, count.groups())
        if not 0 <= current <= capacity:
            raise Paused('Армия: некорректная численность')
        # Free personnel slots alone do not imply losses: a vehicle uses several slots.
        button = next((name for name in ('пополнить', 'восполнить', 'подготовить')
                       if bot.has(name, region)), None)
        prepare = None
        if current < capacity and button is None:
            prepare = bot.optional_template('army-prepare-available.png', (1680, 178, 1845, 234), region)
        if current == capacity or (button is None and prepare is None):
            bot.log(f'Казарма №{number + 1}: {current}/{capacity}; кнопки пополнения нет' if button is None
                    else f'Казарма №{number + 1}: заполнена')
            continue
        if prepare is not None:
            bot.tap(*prepare)
        else:
            bot.click(button, region)
        bot.wait(.8)
        bot.observe()
        if not (bot.has('наземные войска') and bot.has('казарма')):
            (ROOT / 'army-refill-confirmation.png').write_bytes((ROOT / 'bot-screen.png').read_bytes())
            raise Paused('Пополнение войск: открылось подтверждение; снимок сохранён для настройки следующего шага')
        after = bot.text((1550, top, 1880, top + 55))
        result = re.search(r'казарма\s*:\s*(\d+)\s*/\s*(\d+)', after)
        if result and int(result[1]) > current:
            bot.log(f'Казарма №{number + 1}: пополнение подтверждено {current} → {result[1]}')
        else:
            bot.log(f'Казарма №{number + 1}: команда нажата; увеличение численности пока не подтверждено')
    bot.tap(1855, 50)
    bot.main()
