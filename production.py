"""Ordered, resumable manufacturing; UI configuration uses only the standard library."""
import copy
import json
from pathlib import Path

MATERIALS = ('Доска', 'Кирпич', 'Цемент', 'Железная балка', 'Асфальт', 'Бетон')
DEFAULT = {'version': 1, 'enabled': True, 'repeat': True, 'limit': 33,
           'workshops': [[{'material': material, 'count': 1}]
                         for material in ('Цемент', 'Железная балка', 'Асфальт', 'Бетон')]}


class UncertainAddition(RuntimeError):
    """The pending journal must block a retry, while other farming tasks may continue."""


def validate(config):
    if not isinstance(config, dict) or config.get('version') != 1:
        raise ValueError('Неизвестный формат производственной схемы')
    if type(config.get('enabled')) is not bool or type(config.get('repeat')) is not bool:
        raise ValueError('Не указаны переключатели производства')
    if type(config.get('limit')) is not int or not 1 <= config['limit'] <= 33:
        raise ValueError('Заполнение очереди должно быть от 1 до 33')
    recipes = config.get('workshops')
    if not isinstance(recipes, list) or len(recipes) != 4:
        raise ValueError('Нужны схемы четырёх мастерских')
    for recipe in recipes:
        if not isinstance(recipe, list) or len(recipe) > 20:
            raise ValueError('В мастерской допускается до 20 шагов; пустая схема отключает её')
        for row in recipe:
            if (not isinstance(row, dict) or row.get('material') not in MATERIALS
                    or type(row.get('count')) is not int or not 1 <= row['count'] <= 999):
                raise ValueError('Для каждого шага выбери материал и количество от 1 до 999')
    return copy.deepcopy(config)


def write_json(path, data):
    path = Path(path)
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
    temporary.replace(path)


def load_config(path):
    path = Path(path)
    return validate(json.loads(path.read_text(encoding='utf-8'))) if path.exists() else copy.deepcopy(DEFAULT)


def save_config(path, config):
    write_json(path, validate(config))


def next_batch(recipe, position, repeat, room):
    """Return one same-material batch and its next cursor; never cross a recipe boundary."""
    index, used = position
    if index == len(recipe):
        if not repeat:
            return None
        index, used = 0, 0
    if not recipe or room <= 0:
        return None
    if not 0 <= index < len(recipe) or not 0 <= used < recipe[index]['count']:
        raise ValueError('Повреждена позиция производственной схемы')
    row = recipe[index]
    if repeat and len(recipe) == 1:
        count = min(room, 5)
        return row['material'], count, [0, (used + count) % row['count']]
    count = min(room, row['count'] - used, 5)
    following = [index + 1, 0] if used + count == row['count'] else [index, used + count]
    return row['material'], count, following


def select_material(bot, material):
    from bot import Paused, norm
    for _ in range(7):
        bot.require('агрегатный завод', 'производство')
        title = norm(bot.detail((1250, 500, 1750, 575)))
        names = [norm(value) for value in MATERIALS]
        if title not in names:
            raise Paused('Не прочитан выбранный строительный материал: ' + title)
        if title == norm(material):
            return
        delta = names.index(norm(material)) - names.index(title)
        # Touching the selected center card can enqueue even at the start of a drag.
        # Only touch an unselected adjacent card; it centers itself without adding a job.
        bot.template('factory-current.png', (1434, 440, 1484, 460), (1400, 430, 1510, 480))
        bot.tap(1690 if delta > 0 else 1220, 320)
    raise Paused('Не удалось выбрать материал: ' + material)


def enter_factory(bot):
    # Overview buttons also say «Производство»; only workshop tabs identify the editor.
    if bot.has('агрегатный завод') and bot.has('мастерская'):
        return
    bot.main()
    if not bot.has('агрегатный завод'):
        if not bot.has('сбор ресурсов'):
            bot.tap(75, 337)
            bot.tap(155, 250)
        bot.require('сбор ресурсов')
        bot.tap(153, 385)
    bot.require('агрегатный завод')
    for number in range(4):
        region = (725, 280 + number * 140, 910, 380 + number * 140)
        if bot.has('получить', region):
            bot.click('получить', region)
            bot.wait(.8)
            bot.observe()
            bot.require('агрегатный завод')
            bot.log(f'Мастерская №{number + 1}: готовые материалы получены')
            from telemetry import completed_queue, safe
            if not bot.has('получить', region):
                safe(bot, completed_queue, number+1)
            if bot.has('мастерская'):
                bot.back()
                bot.main()
                bot.tap(75, 337)
                bot.tap(155, 250)
                bot.require('сбор ресурсов')
                bot.tap(153, 385)
                bot.require('агрегатный завод')
    first_queue = (725, 280, 910, 380)
    button = 'производство' if bot.has('производство', first_queue) else 'показать'
    bot.click(button, first_queue)
    bot.wait(.8)
    bot.observe()
    bot.require('агрегатный завод', 'мастерская')


def fill_queues(bot, config, state_path=None):
    from bot import Paused, ROOT
    from daily_tasks import factory_queue
    config = validate(config)
    if not config['enabled'] or not any(config['workshops']):
        bot.log('Производственные очереди выключены или схемы пусты')
        return
    path = Path(state_path) if state_path is not None else ROOT / 'production-state.json'
    state = json.loads(path.read_text(encoding='utf-8')) if path.exists() else {'version': 1, 'workshops': {}}
    if not isinstance(state, dict) or state.get('version') != 1 or not isinstance(state.get('workshops'), dict):
        raise Paused('Не прочитан сохранённый прогресс производства')
    enter_factory(bot)
    for number, recipe in enumerate(config['workshops'], 1):
        if not recipe:
            continue
        bot.tap(180 + (number - 1) * 233, 175)
        bot.require('агрегатный завод', 'производство')
        # All four labels are visible: distinguish the active dark tab from inactive light tabs.
        if bot.frame[148:163, 80 + (number - 1)*233:100 + (number - 1)*233].mean() > 110:
            raise Paused(f'Не подтверждена выбранная мастерская №{number}')
        queued, capacity = factory_queue(bot)
        signature = json.dumps([recipe, config['repeat']], ensure_ascii=False, sort_keys=True)
        progress = state['workshops'].get(str(number))
        if progress is None or progress.get('signature') != signature:
            progress = {'signature': signature, 'position': [0, 0], 'pending': False}
            state['workshops'][str(number)] = progress
        if progress.get('pending'):
            if queued and not (config['repeat'] and len(recipe)==1):
                bot.log(f'Мастерская №{number}: результат прерванного добавления неизвестен; дождусь пустой очереди')
                continue
            progress.update(position=[0, 0], pending=False)
            write_json(path, state)
            bot.log(f'Мастерская №{number}: неопределённое добавление снято; очередь перечитана, схема восстановлена')
        added = 0
        for _ in range(33):
            queued, capacity = factory_queue(bot)
            batch = next_batch(recipe, progress['position'], config['repeat'], min(capacity, config['limit']) - queued)
            if batch is None:
                break
            material, count, following = batch
            select_material(bot, material)
            before, capacity = factory_queue(bot)
            if before > queued:
                progress['pending'] = True
                write_json(path,state)
                raise UncertainAddition(f'Мастерская №{number}: смена материала неожиданно изменила очередь; повтор заблокирован')
            count = min(count, min(capacity, config['limit']) - before)
            if count <= 0:
                progress['pending'] = False
                write_json(path, state)
                break
            # Recompute if the observed capacity changed while selecting a material.
            material, count, following = next_batch(recipe, progress['position'], config['repeat'], count)
            bot.template('daily-material-menu.png', (1320, 889, 1610, 938), (1250, 850, 1700, 980))
            progress['pending'] = True
            write_json(path, state)
            for _ in range(count):
                bot.command('-s', bot.serial, 'shell', 'input', 'tap', '1460', '910')
                bot.wait(.1)
            bot.wait(.7)
            bot.observe()
            bot.require('агрегатный завод', 'производство')
            after, _ = factory_queue(bot)
            if after != before + count:
                raise UncertainAddition(f'Мастерская №{number}: добавление не подтверждено счётчиком; автоматический повтор заблокирован')
            progress.update(position=following, pending=False)
            write_json(path, state)
            added += count
            from telemetry import record, safe
            safe(bot, record, 'queued', material, count, workshop=number)
            bot.log(f'Мастерская №{number}: {material} × {count}; очередь {after}/{capacity}')
        bot.log(f'Мастерская №{number}: добавлено {added}, следующая позиция схемы сохранена')
    bot.back()
    bot.main()
