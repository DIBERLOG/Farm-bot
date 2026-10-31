"""Five ordinary collectors; paid sixth collector is never included."""
import json
from pathlib import Path

RESOURCES = ('Ферма', 'Нефть', 'Шахта', 'Не отправлять')
PRESETS = {
    '2 фермы · 2 нефти · 1 шахта': ['Ферма', 'Ферма', 'Нефть', 'Нефть', 'Шахта'],
    '2 фермы · 1 нефть · 2 шахты': ['Ферма', 'Ферма', 'Нефть', 'Шахта', 'Шахта'],
    '1 ферма · 2 нефти · 2 шахты': ['Ферма', 'Нефть', 'Нефть', 'Шахта', 'Шахта'],
    'Все на фермы': ['Ферма'] * 5,
    'Все на нефть': ['Нефть'] * 5,
    'Все на шахты': ['Шахта'] * 5,
}


def validate_plan(plan):
    if not isinstance(plan, list) or len(plan) != 5 or any(value not in RESOURCES for value in plan):
        raise ValueError('Схема должна содержать назначения для пяти отрядов')
    return list(plan)


def save_plan(path, plan):
    data = {'version': 1, 'plan': validate_plan(plan)}
    destination = Path(path)
    temporary = destination.with_suffix('.tmp')
    temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
    temporary.replace(destination)


def load_plan(path):
    destination = Path(path)
    if not destination.exists():
        return list(next(iter(PRESETS.values())))
    data = json.loads(destination.read_text(encoding='utf-8'))
    if data.get('version') != 1:
        raise ValueError('Неизвестная версия сохранённой схемы')
    return validate_plan(data.get('plan'))
