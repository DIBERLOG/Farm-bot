"""JSON-lines bridge for the native UI. EOF cancels automation and releases its lock."""
import ctypes
import json
from pathlib import Path
import subprocess
import sys
import threading
import time

from plans import load_plan, save_plan
from production import load_config, save_config

ROOT = Path(__file__).resolve().parent


class Worker:
    def __init__(self, emit):
        self.emit = emit
        self.stop = threading.Event()
        self.thread = None
        self.hidden = False
        from army import load_groups
        self.join_army_groups = load_groups()

    def log(self, message):
        entry = time.strftime('%H:%M:%S') + '  ' + str(message)
        with (ROOT / 'bot.log').open('a', encoding='utf-8') as output:
            output.write(entry + '\n')
        self.emit({'event': 'log', 'message': entry})

    def animate(self, state):
        self.emit({'event': 'animation', 'state': state})

    def statistics(self, bot=None):
        from telemetry import load, snapshot
        try:
            if bot is not None:
                snapshot(bot)
            self.emit({'event':'statistics', 'data':load()})
        except Exception as error:
            if self.stop.is_set():
                raise
            self.log('Статистика временно недоступна: ' + type(error).__name__)
            self.emit({'event':'statistics_error','message':'Статистика временно недоступна. Проверь statistics.json; автоферма продолжает работу.'})

    def command(self, command):
        kind = command.get('command')
        if kind == 'statistics':
            self.statistics()
            return
        busy = self.thread is not None and self.thread.is_alive()
        if kind == 'army_groups':
            from army import save_groups
            save_groups(command.get('enabled'))
            self.join_army_groups = command['enabled']
            self.emit({'event':'army_groups', 'enabled':self.join_army_groups})
            return
        if kind == 'stop':
            self.stop.set()
            return
        if kind == 'emergency_save':
            if busy:
                raise ValueError('Сначала останови автоферму')
            from emergency import save, settings
            save(command.get('enabled'), command.get('key', ''), command.get('x',0), command.get('y',0), command.get('destination_set',False))
            self.emit({'event': 'emergency', **settings()})
            return
        if kind in ('hide', 'show'):
            self.window(0 if kind == 'hide' else 9)
            return
        if kind == 'save':
            if busy:
                raise ValueError('Сначала останови автоферму, чтобы изменить схемы')
            # Validate both before either file is changed.
            from plans import validate_plan
            from production import validate
            plan = validate_plan(command['plan'])
            production = validate(command['production'])
            save_plan(ROOT / 'settings.json', plan)
            save_config(ROOT / 'production.json', production)
            self.emit({'event': 'saved', 'message': 'Схемы сохранены'})
            return
        if kind != 'start' or command.get('task') not in ('cycle', 'campaign', 'campaign_sea', 'inspect'):
            raise ValueError('Неизвестная команда')
        if busy:
            raise ValueError('Действие уже выполняется')
        plan = load_plan(ROOT / 'settings.json')
        production = load_config(ROOT / 'production.json')
        self.stop.clear()
        self.thread = threading.Thread(target=self.run, args=(command['task'], bool(command.get('repeat')), plan, production))
        self.thread.start()

    def run(self, task, repeat, plan, production):
        persistent = task == 'cycle' and repeat
        while True:
            result = self.run_session(task, repeat, plan, production, persistent)
            if not persistent or self.stop.is_set():
                break
            message = f'Автоферма включена. Повтор через 60 секунд: {result}'
            self.log(message)
            self.animate('recovery')
            self.emit({'event': 'state', 'busy': True, 'message': message})
            # Event.wait makes Stop/closing immediate, including during reconnect delays.
            if self.stop.wait(60):
                break
        if persistent:
            self.animate('stopped')
            self.emit({'event': 'state', 'busy': False, 'message': 'Остановлено пользователем'})

    def run_session(self, task, repeat, plan, production, persistent=False):
        bot = None
        try:
            self.animate('stage')
            self.emit({'event': 'state', 'busy': True, 'message': 'Подключение к игре…'})
            self.log('Загрузка распознавания…')
            from bot import Bot, Paused
            from emergency import settings, recover
            self.log('Подключение к LDPlayer…')
            bot = Bot(log=self.log, stop=self.stop, allow_captcha=task != 'inspect')
            bot.connect()
            bot.watch_attack = settings()['enabled']
            self.log('Подключение готово; проверяю экран')
            while not self.stop.is_set():
                bot.observe()
                if task == 'inspect':
                    self.log('Снимок получен; игра не изменена.\n' + bot.text())
                elif task in ('campaign', 'campaign_sea'):
                    self.animate('sea_campaign' if task == 'campaign_sea' else 'stage')
                    bot.campaign('sea' if task == 'campaign_sea' else 'land')
                    self.animate('stopped' if self.stop.is_set() else 'success')
                else:
                    ordered = production['enabled'] and any(production['workshops'])
                    actions = [
                        ('Помощь альянсу', bot.help_all),
                        ('Воздушные поставки: вызов и сбор', bot.supplies),
                        ('Награды радара', bot.radar_rewards),
                        ('Технологии: всё по порядку', bot.personal_research),
                        ('Пополнение войск', lambda: self.army_actions(bot)),
                        ('Сборщики ресурсов', lambda: bot.run_plan(plan)),
                        ('Производственные очереди', lambda: bot.production(production)),
                        ('Пожертвования от 1/20', bot.research),
                        ('Ежедневные действия, офицеры и пополнение', lambda: (bot.campaign_refill(), bot.daily_actions(send_officers=True, skip_materials=ordered))),
                    ]
                    steps = [{'title': title, 'status':'waiting'} for title, _ in actions]
                    self.statistics(bot)
                    self.emit({'event':'progress', 'steps':steps.copy()})
                    for index, (title, action) in enumerate(actions):
                        if self.stop.is_set():
                            break
                        self.emit({'event': 'state', 'busy': True, 'message': title})
                        self.animate('production' if title == 'Производственные очереди' else 'stage')
                        steps[index] = {'title':title, 'status':'running'}
                        self.emit({'event':'progress', 'steps':steps.copy()})
                        for attempt in range(2):
                            if self.stop.is_set():
                                break
                            try:
                                bot.observe()
                                bot.main()
                                action()
                                if self.stop.is_set():
                                    break
                                # A stage is complete only after its nested windows are closed.
                                bot.observe()
                                try:
                                    bot.main()
                                except Exception as screen_error:
                                    self.animate('recovery')
                                    if not recover(bot, screen_error):
                                        raise
                                steps[index] = {'title':title, 'status':'done'}
                                self.statistics()
                                self.animate('stopped' if self.stop.is_set() else 'success')
                                break
                            except Exception as error:
                                self.log(f'{title}: {error} (попытка {attempt + 1}/2)')
                                steps[index] = {'title':title, 'status':'paused', 'reason':str(error)}
                                self.emit({'event':'progress', 'steps':steps.copy()})
                                if self.stop.is_set() or 'нападении на базу' in str(error):
                                    raise
                                self.animate('recovery')
                                if not recover(bot, error):
                                    raise
                                if attempt == 0:
                                    self.animate('production' if title == 'Производственные очереди' else 'stage')
                                    self.log(f'{title}: повторяю после восстановления карты')
                                    steps[index] = {'title':title, 'status':'running'}
                                    self.emit({'event':'progress', 'steps':steps.copy()})
                                else:
                                    self.log(f'{title}: две попытки не удались; отложено до следующего прохода')
                                    steps[index] = {'title':title, 'status':'deferred', 'reason':str(error)}
                        self.emit({'event':'progress', 'steps':steps.copy()})
                if self.stop.is_set() or not repeat or task != 'cycle':
                    break
                self.animate('idle')
                self.log('Проход завершён; следующая проверка через 5 минут')
                self.emit({'event': 'state', 'busy': True, 'message': 'Ожидание следующего прохода · 5 минут'})
                if bot.watch_attack:
                    for _ in range(20):
                        bot.wait(15)
                        bot.observe()
                else:
                    bot.wait(300)
            result = 'Остановлено' if self.stop.is_set() else 'Проход завершён'
        except Exception as error:
            if bot is not None and not self.stop.is_set() and (task in ('campaign', 'campaign_sea') or 'нападении на базу' in str(error)):
                from emergency import recover
                self.animate('recovery')
                recover(bot, error)
            result = 'Остановлено' if self.stop.is_set() else 'ПАУЗА: ' + str(error)
            if task in ('campaign', 'campaign_sea') and not self.stop.is_set() and any(word in str(error) for word in ('Поражение в кампании', 'Бой не продвигается')):
                level = getattr(bot, 'campaign_level', '') or 'Текущий уровень'
                result = f'{level}: пока непроходим'
                (ROOT / 'campaign-status.txt').write_text(result, encoding='utf-8')
                self.emit({'event':'campaign_status', 'message':result})
            self.log(result)
        finally:
            if bot is not None:
                bot.close()
            if not persistent:
                self.animate('stopped' if self.stop.is_set() else 'idle')
                self.emit({'event': 'state', 'busy': False, 'message': result})
        return result

    def army_actions(self, bot):
        bot.army_refill()
        if self.join_army_groups:
            from army import join_groups
            join_groups(bot)

    def window(self, command):
        output = subprocess.run(['C:/LDPlayer/LDPlayer9/ldconsole.exe', 'list2'], capture_output=True,
                                timeout=5, creationflags=subprocess.CREATE_NO_WINDOW, check=True)
        row = next((line.split(',') for line in output.stdout.decode(errors='replace').splitlines() if line.startswith('0,')), None)
        if row is None or len(row) < 5 or row[4] != '1':
            raise RuntimeError('LDPlayer не запущен')
        handle = int(row[2])
        user32 = ctypes.WinDLL('user32', use_last_error=True)
        for name in ('IsWindow', 'IsWindowVisible'):
            getattr(user32, name).argtypes = [ctypes.c_void_p]
        user32.ShowWindow.argtypes = [ctypes.c_void_p, ctypes.c_int]
        if not handle or not user32.IsWindow(handle):
            raise RuntimeError('Окно LDPlayer недоступно')
        user32.ShowWindow(handle, command)
        if bool(user32.IsWindowVisible(handle)) != (command != 0):
            raise RuntimeError('Не удалось изменить видимость LDPlayer')
        self.hidden = command == 0
        self.emit({'event': 'window', 'hidden': self.hidden, 'message': 'LDPlayer скрыт · игра работает' if self.hidden else 'LDPlayer показан'})

    def close(self):
        self.stop.set()
        if self.thread:
            self.thread.join()
        if self.hidden:
            self.window(9)


def main():
    # NumPy/OpenCV initialize native Windows state; load before the main thread waits on stdin.
    import bot
    sys.stdin.reconfigure(encoding='utf-8')
    sys.stdout.reconfigure(encoding='utf-8', line_buffering=True)
    lock = threading.Lock()
    def emit(event):
        with lock:
            print(json.dumps(event, ensure_ascii=False), flush=True)
    worker = Worker(emit)
    try:
        from emergency import settings
        emit({'event': 'campaign_status', 'message': (ROOT / 'campaign-status.txt').read_text(encoding='utf-8') if (ROOT / 'campaign-status.txt').exists() else ''})
        emit({'event': 'ready', 'plan': load_plan(ROOT / 'settings.json'), 'production': load_config(ROOT / 'production.json'), 'emergency': settings(), 'army_groups':worker.join_army_groups})
        for line in sys.stdin:
            try:
                command = json.loads(line)
                if command.get('command') == 'shutdown':
                    break
                worker.command(command)
            except Exception as error:
                emit({'event': 'error', 'message': str(error)})
    finally:
        worker.close()


if __name__ == '__main__':
    main()
