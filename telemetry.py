"""Persistent, confirmed automation counters. No reconstruction from old logs."""
import json
import re
import threading
import time
from datetime import datetime
from pathlib import Path

PATH = Path(__file__).with_name('statistics.json')
LOCK = threading.RLock()


def safe(bot, function, *args, **kwargs):
    try:
        function(*args, **kwargs)
    except (OSError, ValueError, TypeError) as error:
        bot.log('Статистика не обновлена: ' + type(error).__name__ + '; работа продолжается')


def load():
    if PATH.exists():
        for attempt in range(3):
            try:
                with LOCK:
                    return json.loads(PATH.read_text(encoding='utf-8-sig'))
            except json.JSONDecodeError as error:
                if attempt == 2:
                    raise ValueError(f'Не удалось прочитать {PATH.name}: некорректный JSON. Файл сохранён без изменений') from error
                time.sleep(.05)
    return {'since': datetime.now().isoformat(timespec='seconds'), 'dispatches': {},
            'levels': {}, 'queued': {}, 'produced': {}, 'pending': {},
            'balances': {}, 'inflow': {}, 'gathered': {}, 'active': {}, 'days': {}}


def record(kind, name, count, level=None, workshop=None, collector=None):
    if type(count) is not int or count < 0:
        raise ValueError('Invalid statistics count')
    with LOCK:
        data = load()
        bucket = data[kind]
        bucket[name] = bucket.get(name, 0) + count
        day = data['days'].setdefault(datetime.now().date().isoformat(), {})
        day[kind] = day.get(kind, 0) + count
        if kind == 'dispatches' and level is not None:
            key = str(level)
            data['levels'][key] = data['levels'].get(key, 0) + count
            if collector is not None:
                data.setdefault('active', {})[str(collector)] = {'resource':name, 'amount':0}
        if kind == 'queued' and workshop is not None:
            pending = data['pending'].setdefault(str(workshop), {})
            pending[name] = pending.get(name, 0) + count
        save(data)


def gathering(collector, text):
    if not isinstance(text,str):
        return
    match = re.search(r'(\d[\d ]*)\s*/\s*(\d[\d ]*)', text)
    if not match:
        return
    amount, capacity = (int(value.replace(' ','')) for value in match.groups())
    if not 0 <= amount <= capacity <= 1000000000:
        return
    with LOCK:
        data = load()
        trip = data.get('active', {}).get(str(collector))
        if trip is None or amount <= trip['amount']:
            return
        delta = amount - trip['amount']
        trip['amount'] = amount
        name = trip['resource']
        gathered = data.setdefault('gathered', {})
        gathered[name] = gathered.get(name,0) + delta
        day = data['days'].setdefault(datetime.now().date().isoformat(), {})
        day['gathered'] = day.get('gathered',0) + delta
        save(data)


def save(data):
    temporary = PATH.with_suffix('.tmp')
    temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
    temporary.replace(PATH)


def completed_queue(workshop):
    # Count tracked additions only after the whole workshop queue is claimed.
    with LOCK:
        data = load()
        pending = data['pending'].pop(str(workshop), {})
        if pending:
            for material, count in pending.items():
                data['produced'][material] = data['produced'].get(material, 0) + count
            day = data['days'].setdefault(datetime.now().date().isoformat(), {})
            day['produced'] = day.get('produced', 0) + sum(pending.values())
            save(data)


def parse_balance(text):
    if not isinstance(text, str):
        return None
    match = re.fullmatch(r'\s*(\d+(?:[.,]\d+)?)\s*([mмkк]?)\s*', text.lower().replace(' ', ''))
    if not match:
        return None
    return round(float(match[1].replace(',', '.')) * {'':1, 'k':1000, 'к':1000, 'm':1000000, 'м':1000000}[match[2]])


def snapshot(bot):
    values = {}
    for name, region in [('Финансирование',(1125,24,1212,59)),
                         ('Сталь',(1259,24,1343,59)), ('Топливо',(1394,24,1479,59))]:
        value = parse_balance(bot.text(region))
        if value is None and isinstance(bot.text(region),str):
            value = parse_balance(bot.detail(region))
        if value is not None:
            values[name] = value
    if not values:
        return
    with LOCK:
        data = load()
        for name, value in values.items():
            previous = data['balances'].get(name)
            if previous is not None and value > previous:
                data['inflow'][name] = data['inflow'].get(name, 0) + value - previous
            data['balances'][name] = value
        data['updated'] = datetime.now().isoformat(timespec='seconds')
        save(data)
