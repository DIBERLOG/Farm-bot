"""Local control panel. All Android input runs on one stoppable worker."""
import ctypes
import argparse
import queue
import subprocess
import threading
import time
import tkinter as tk
from tkinter import ttk
import winsound
from pathlib import Path

from plans import PRESETS, RESOURCES, load_plan, save_plan
from production_panel import ProductionPanel
from widgets import BG, SIDE, CARD, BORDER, TEXT, MUTED, ACCENT, Panel, Button, label

ROOT = Path(__file__).resolve().parent


class App:
    def __init__(self, root):
        self.root = root
        root.title('Warpath — помощник')
        icon = ROOT / 'assets' / 'app-icon.ico'
        if icon.exists():
            root.iconbitmap(str(icon))
        root.geometry('1120x820')
        root.minsize(1000, 760)
        root.configure(bg=BG)
        style = ttk.Style(root)
        style.theme_use('clam')
        style.configure('.', font=('Segoe UI', 10), background=CARD, foreground=TEXT)
        style.configure('TCombobox', padding=(10, 10), arrowsize=15, borderwidth=0,
                        fieldbackground='#202E40', background='#202E40', arrowcolor=MUTED,
                        bordercolor=BORDER, lightcolor=BORDER, darkcolor=BORDER)
        style.map('TCombobox', fieldbackground=[('disabled', '#192431'), ('readonly', '#202E40')],
                  foreground=[('disabled', '#7C8BA0'), ('readonly', TEXT)],
                  selectbackground=[('readonly', '#202E40')], selectforeground=[('readonly', TEXT)])
        style.configure('TCheckbutton', background=CARD, foreground=TEXT, padding=(0, 8))
        style.configure('TSpinbox', fieldbackground='#202E40', foreground=TEXT, background='#202E40',
                        arrowcolor=MUTED, bordercolor=BORDER, lightcolor=BORDER, darkcolor=BORDER,
                        insertcolor=TEXT, padding=(8, 8))
        style.map('TSpinbox', fieldbackground=[('disabled', '#192431')],
                  foreground=[('disabled', '#7C8BA0')])
        style.map('TCheckbutton', background=[('active', CARD)], foreground=[('disabled', '#7C8BA0')])
        style.configure('Vertical.TScrollbar', background='#34475E', troughcolor=CARD,
                        arrowcolor=MUTED, borderwidth=0, arrowsize=10)
        root.option_add('*TCombobox*Listbox.background', '#202E40')
        root.option_add('*TCombobox*Listbox.foreground', TEXT)
        root.option_add('*TCombobox*Listbox.selectBackground', '#36574F')
        root.option_add('*TCombobox*Listbox.selectForeground', TEXT)
        root.option_add('*TCombobox*Listbox.font', ('Segoe UI', 10))
        self.events = queue.Queue()
        self.stop = threading.Event()
        self.worker = None
        self.emulator_hidden = False
        self.mode = tk.StringVar(value='Основной цикл: награды, альянс, поставки и сборщики')
        self.resource = tk.StringVar(value='Шахта')
        self.repeat = tk.BooleanVar(value=False)
        self.status = tk.StringVar(value='Остановлен')
        self.preset = tk.StringVar(value='Своя схема')
        self.summary = tk.StringVar()
        self.last_event = tk.StringVar(value='Выбери действие и нажми «Запустить».')
        self.window_hint = tk.StringVar(value='Скрытие окна без остановки игры')
        self.page_title = tk.StringVar()
        self.page_subtitle = tk.StringVar()
        self.plan_controls = []
        self.stat_counts = {}
        self.plan_colorbars = []
        try:
            stored = load_plan(ROOT / 'settings.json')
            warning = None
        except (ValueError, OSError) as error:
            stored = list(next(iter(PRESETS.values())))
            warning = 'Сохранённая схема не прочитана: ' + str(error)
        self.plan = [tk.StringVar(value=value) for value in stored]
        for name, values in PRESETS.items():
            if stored == values:
                self.preset.set(name)
                break
        self.tasks = {
            'Основной цикл: награды, альянс, поставки и сборщики': 'cycle',
            'Автокампания: до 3 боёв (тестовый режим)': 'campaign',
            'Отправить сборщиков по схеме': 'plan',
            'Заполнить производственные очереди по порядку': 'production',
            'Забрать готовые награды радара': 'radar_rewards',
            'Награды миссий и сундуки ежедневной активности': 'mission_rewards',
            'Ежедневные действия и получение наград': 'daily_actions',
            'Миссии офицеров: забрать и отправить': 'officer_missions',
            'Воздушные поставки': 'supplies',
            'Помощь альянсу': 'help_all',
            'Пожертвования в исследования: от 1/20': 'research',
            'Ресурсы: максимальный доступный уровень': 'search_resources',
            'Проверить экран без нажатий': 'inspect',
        }
        self.descriptions = {
            'cycle': 'Радар, ежедневные действия и награды, миссии офицеров, помощь альянсу, пожертвования, поставки, сборщики и производственные очереди.',
            'campaign': 'До трёх боёв с автоатакой. Тестовый режим: при поражении или неизвестном задании бот остановится.',
            'plan': 'Пять назначений из раздела «Сборщики». Занятые и возвращающиеся отряды будут пропущены.',
            'production': 'Последовательности четырёх мастерских из раздела «Производство». Существующие задания сохраняются; новые добавляются только в свободные места.',
            'radar_rewards': 'Получение готовых наград радара. Новые боевые задания не запускаются.',
            'mission_rewards': 'Готовые награды миссий, ежедневных заданий и доступные сундуки активности.',
            'daily_actions': 'Материалы, строительство при достаточных запасах, обычный билет, минутное ускорение, +1 уровень СУ-100М (до 1000 опыта), БМ-24 (до 200 деталей), до 3 базовых книг Аарону Мэтьюзу, обычное и бесплатное быстрое пополнение кампании, бои с «Вороном» уровня 1 и награды.',
            'officer_missions': 'Получить завершённые миссии, затем «Быстрый выбор» и отправка доступных офицеров. Без обновления за золото.',
            'supplies': 'Парашют у твоего командного пункта и получение выпавших ящиков.',
            'help_all': 'Открыть помощь альянсу и помочь всем, если есть запросы.',
            'research': 'От одного доступного пожертвования. Заполненные исследования пропускаются; используются подтверждённые обычные ресурсы.',
            'search_resources': 'Поиск с максимального разрешённого уровня вниз и отправка свободного сборщика.',
            'inspect': 'Получить снимок игры и распознать текст. Нажатий в игре не будет.',
        }
        root.columnconfigure(1, weight=1)
        root.rowconfigure(0, weight=1)
        sidebar = tk.Frame(root, bg=SIDE, width=196)
        sidebar.grid(row=0, column=0, sticky='nsew')
        sidebar.grid_propagate(False)
        brand = tk.Frame(sidebar, bg=SIDE)
        brand.pack(fill='x', padx=22, pady=(28, 32))
        self.brand_icon = tk.PhotoImage(file=str(ROOT / 'assets' / 'app-icon-64.png'))
        tk.Label(brand, image=self.brand_icon, bg=SIDE).pack(anchor='w')
        label(brand, 'WARPATH', size=15, bold=True).pack(anchor='w', pady=(9, 2))
        label(brand, 'Личный помощник', size=9, color=MUTED).pack(anchor='w')
        self.nav_buttons = {}
        self.page_info = {
            'home': ('Центр управления', 'Всё для спокойной работы в фоне'),
            'plans': ('Сборщики', 'Твоя схема добычи для пяти отрядов'),
            'production': ('Производство', 'Твой порядок материалов для четырёх мастерских'),
            'log': ('Журнал событий', 'Реальные действия и сообщения помощника'),
            'guide': ('Как пользоваться', 'Возможности, управление и ограничения'),
        }
        for key, text in [('home', 'Панель управления'), ('plans', 'Сборщики'),
                          ('production', 'Производство'),
                          ('log', 'Журнал событий'), ('guide', 'Как пользоваться')]:
            button = Button(sidebar, text, lambda name=key: self.show_page(name), kind='nav', width=168)
            button.pack(fill='x', padx=14, pady=4)
            self.nav_buttons[key] = button
        foot = tk.Frame(sidebar, bg=SIDE)
        foot.pack(side='bottom', fill='x', padx=22, pady=24)
        tk.Frame(foot, bg=BORDER, height=1).pack(fill='x', pady=(0, 18))
        label(foot, 'ЛОКАЛЬНЫЙ РЕЖИМ', size=8, color=ACCENT, bold=True).pack(anchor='w')
        label(foot, 'LDPlayer · 1920 × 1080', size=9, color=MUTED).pack(anchor='w', pady=(7, 3))
        label(foot, 'Русский язык игры', size=9, color=MUTED).pack(anchor='w')
        label(foot, 'ТЕСТОВАЯ ВЕРСИЯ', size=8, color=MUTED).pack(anchor='w', pady=(22, 0))
        content = tk.Frame(root, bg=BG)
        content.grid(row=0, column=1, sticky='nsew', padx=26)
        header = tk.Frame(content, bg=BG)
        header.pack(fill='x', pady=(26, 22))
        label(header, size=25, bold=True, textvariable=self.page_title).pack(anchor='w')
        label(header, size=10, color=MUTED, textvariable=self.page_subtitle).pack(anchor='w', pady=(5, 0))
        label(content, size=9, color=MUTED, textvariable=self.last_event,
              anchor='w', justify='left', wraplength=800).pack(side='bottom', fill='x', pady=16)
        deck = tk.Frame(content, bg=BG)
        deck.pack(fill='both', expand=True)
        deck.columnconfigure(0, weight=1)
        deck.rowconfigure(0, weight=1)
        self.pages = {}
        for key in self.page_info:
            page = tk.Frame(deck, bg=BG)
            page.grid(row=0, column=0, sticky='nsew')
            self.pages[key] = page
        home = self.pages['home']
        home.columnconfigure(0, weight=1)
        status_card = Panel(home, padding=18)
        status_card.grid(row=0, column=0, sticky='ew')
        status_card.body.columnconfigure(0, weight=1)
        left = tk.Frame(status_card.body, bg=CARD)
        left.grid(row=0, column=0, sticky='w')
        label(left, 'СОСТОЯНИЕ БОТА', size=8, color=MUTED, bold=True).pack(anchor='w')
        self.status_label = label(left, size=15, bold=True, textvariable=self.status,
                                  wraplength=340, justify='left')
        self.status_label.pack(anchor='w', pady=(5, 0))
        self.start_button = Button(status_card.body, 'Запустить', self.start, kind='primary', width=138)
        self.start_button.grid(row=0, column=1, padx=(14, 8))
        self.stop_button = Button(status_card.body, 'Стоп', self.cancel, kind='danger', width=96)
        self.stop_button.grid(row=0, column=2)
        self.stop_button.configure(state='disabled')
        config = Panel(home)
        config.grid(row=1, column=0, sticky='ew', pady=12)
        label(config.body, 'Режим работы', size=13, bold=True).pack(anchor='w')
        label(config.body, 'Действие', size=9, color=MUTED).pack(anchor='w', pady=(14, 6))
        self.task_box = ttk.Combobox(config.body, textvariable=self.mode, values=list(self.tasks), state='readonly')
        self.task_box.pack(fill='x')
        self.task_box.bind('<<ComboboxSelected>>', lambda event: self.update_mode())
        self.resource_frame = tk.Frame(config.body, bg=CARD)
        label(self.resource_frame, 'Ресурс', size=9, color=MUTED).pack(anchor='w', pady=(10, 5))
        self.resource_box = ttk.Combobox(self.resource_frame, textvariable=self.resource,
                                       values=['Ферма', 'Шахта', 'Нефтяная вышка'], state='disabled')
        self.resource_box.pack(fill='x')
        self.mode_description = tk.StringVar()
        label(config.body, size=10, color=MUTED, textvariable=self.mode_description,
              wraplength=760, justify='left', anchor='w').pack(fill='x', pady=(10, 2))
        self.repeat_box = ttk.Checkbutton(config.body, text='Повторять каждые 5 минут', variable=self.repeat)
        self.repeat_box.pack(anchor='w', pady=(4, 0))
        emulator = Panel(home, padding=18)
        emulator.grid(row=2, column=0, sticky='ew')
        emulator.body.columnconfigure(0, weight=1)
        info = tk.Frame(emulator.body, bg=CARD)
        info.grid(row=0, column=0, sticky='w')
        label(info, 'Окно LDPlayer', size=12, bold=True).pack(anchor='w')
        label(info, size=9, color=MUTED, textvariable=self.window_hint).pack(anchor='w', pady=(5, 0))
        Button(emulator.body, 'Скрыть', lambda: self.emulator_window(0), width=100).grid(row=0, column=1, padx=(8, 8))
        Button(emulator.body, 'Показать', lambda: self.emulator_window(9), width=100).grid(row=0, column=2)
        mining = Panel(home, padding=18)
        self.mining_card = mining
        mining.grid(row=3, column=0, sticky='ew', pady=(12, 0))
        mining.body.columnconfigure(0, weight=1)
        label(mining.body, 'План добычи', size=12, bold=True).grid(row=0, column=0, sticky='w')
        Button(mining.body, 'Изменить схему', lambda: self.show_page('plans'), width=148, height=40).grid(row=0, column=1, rowspan=2, padx=(8, 0))
        counts = tk.Frame(mining.body, bg=CARD)
        counts.grid(row=1, column=0, sticky='w', pady=(12, 0))
        for index, (resource, name, color) in enumerate([('Ферма', 'ФЕРМЫ', ACCENT), ('Нефть', 'НЕФТЬ', '#91BCF2'), ('Шахта', 'ШАХТЫ', '#D0BAF6')]):
            cell = tk.Frame(counts, bg=CARD)
            cell.grid(row=0, column=index, padx=(0, 32))
            value = tk.StringVar()
            self.stat_counts[resource] = value
            label(cell, size=20, bold=True, color=color, textvariable=value).pack(side='left')
            label(cell, name, size=8, color=MUTED).pack(side='left', padx=8)
        plans = self.pages['plans']
        preset_card = Panel(plans)
        preset_card.pack(fill='x')
        label(preset_card.body, 'Готовые схемы', size=13, bold=True).pack(anchor='w')
        label(preset_card.body, 'Выбери шаблон или настрой каждый отряд отдельно.', size=10, color=MUTED).pack(anchor='w', pady=(5, 14))
        scheme = ttk.Combobox(preset_card.body, textvariable=self.preset, values=list(PRESETS) + ['Своя схема'], state='readonly')
        scheme.pack(fill='x')
        scheme.bind('<<ComboboxSelected>>', self.apply_preset)
        self.plan_controls.append(scheme)
        grid = tk.Frame(plans, bg=BG)
        grid.pack(fill='x', pady=18)
        for index, variable in enumerate(self.plan):
            grid.columnconfigure(index, weight=1, uniform='collector')
            card = Panel(grid, padding=12)
            card.grid(row=0, column=index, sticky='nsew', padx=(0 if index == 0 else 5, 0 if index == 4 else 5))
            label(card.body, f'{index+1:02}', size=25, color=ACCENT, bold=True).pack(anchor='w')
            label(card.body, f'ОТРЯД №{index+1}', size=8, color=MUTED).pack(anchor='w', pady=(4, 18))
            choice = ttk.Combobox(card.body, textvariable=variable, values=RESOURCES, state='readonly', width=9)
            choice.pack(fill='x')
            choice.bind('<<ComboboxSelected>>', self.customize)
            self.plan_controls.append(choice)
            bar = tk.Frame(card.body, height=3)
            bar.pack(fill='x', pady=(18, 2))
            self.plan_colorbars.append(bar)
        note = Panel(plans)
        note.pack(fill='x')
        label(note.body, size=11, bold=True, textvariable=self.summary).pack(anchor='w')
        label(note.body, 'Занятые отряды заканчивают добычу. Возвращающиеся сначала прибывают на базу.\nФерма — финансирование · Нефть — нефтяная вышка · Шахта — сталь.',
              size=10, color=MUTED, wraplength=760, justify='left').pack(anchor='w', pady=(12, 12))
        label(note.body, 'Изменения сохраняются автоматически.', size=9, color=ACCENT).pack(anchor='w')
        self.production = ProductionPanel(self.pages['production'], ROOT / 'production.json')
        log_card = Panel(self.pages['log'], padding=16)
        log_card.pack(fill='both', expand=True)
        label(log_card.body, 'История текущего сеанса', size=13, bold=True).pack(anchor='w', pady=(0, 16))
        self.log = tk.Text(log_card.body, wrap='word', state='disabled', font=('Consolas', 10),
                           background=CARD, foreground=TEXT, relief='flat', bd=0, padx=4, pady=4,
                           insertbackground=TEXT, selectbackground='#36574F')
        scroll = ttk.Scrollbar(log_card.body, command=self.log.yview)
        scroll.pack(side='right', fill='y')
        self.log.configure(yscrollcommand=scroll.set)
        self.log.pack(fill='both', expand=True)
        guide = Panel(self.pages['guide'])
        guide.pack(fill='both', expand=True)
        for title, text in [
            ('01   Подготовь игру', 'Открой карту или базу в LDPlayer. Русский язык, разрешение Android 1920 × 1080, локальное подключение ADB.'),
            ('02   Настрой и запусти', 'Выбери действие и схему сборщиков. Другими приложениями можно пользоваться: бот не управляет мышью Windows. Ежедневные действия расходуют обычные предметы; лимиты указаны в описании этого режима.'),
            ('03   Управляй окном', '«Скрыть» убирает окно LDPlayer, игра остаётся запущенной. «Показать» возвращает окно. При закрытии помощника скрытое им окно восстанавливается.'),
            ('04   Останови при необходимости', '«Стоп» или Escape отменяет дальнейшие действия. В кампании бот выходит из незавершённого боя. Пазл без настроенного профиля вызывает паузу и сохраняется для настройки.'),
            ('Что ещё в разработке', 'Кампания — тестовый режим для задания об уничтожении наземных сил «Ворона». Ежедневные награды собираются, но выполнение всех видов заданий пока не реализовано.')]:
            label(guide.body, title, size=12, bold=True).pack(anchor='w', pady=(8, 6))
            label(guide.body, text, size=10, color=MUTED, wraplength=740, justify='left').pack(anchor='w', pady=(0, 15))
        self.update_summary()
        self.update_mode()
        self.show_page('home')
        if warning:
            self.append(warning)
        root.protocol('WM_DELETE_WINDOW', self.close)
        root.bind('<Escape>', lambda event: self.cancel())
        root.after(150, self.poll)

    def show_page(self, name):
        for key, page in self.pages.items():
            if key == name:
                page.grid()
            else:
                page.grid_remove()
        self.page_title.set(self.page_info[name][0])
        self.page_subtitle.set(self.page_info[name][1])
        for key, button in self.nav_buttons.items():
            button.kind = 'selected' if key == name else 'nav'
            button.draw()

    def update_mode(self):
        task = self.tasks[self.mode.get()]
        self.mode_description.set(self.descriptions[task])
        if task == 'search_resources':
            self.resource_frame.pack(fill='x', after=self.task_box)
            self.resource_box.configure(state='readonly')
            self.mining_card.grid_remove()
        else:
            self.resource_frame.pack_forget()
            self.resource_box.configure(state='disabled')
            self.mining_card.grid()

    def update_summary(self):
        values = [v.get() for v in self.plan]
        self.summary.set('Схема: ' + ' · '.join(f'{name}: {values.count(name)}' for name in RESOURCES if values.count(name)))
        for name, variable in self.stat_counts.items():
            variable.set(str(values.count(name)))
        colors = {'Ферма': ACCENT, 'Нефть': '#91BCF2', 'Шахта': '#D0BAF6', 'Не отправлять': '#65758B'}
        for bar, value in zip(self.plan_colorbars, values):
            bar.configure(bg=colors[value])

    def save(self):
        try:
            save_plan(ROOT / 'settings.json', [v.get() for v in self.plan])
        except (OSError, ValueError) as error:
            self.status.set('Не удалось сохранить схему')
            self.append(str(error))
            return False
        self.update_summary()
        return True

    def apply_preset(self, event=None):
        if self.preset.get() in PRESETS:
            for variable, value in zip(self.plan, PRESETS[self.preset.get()]):
                variable.set(value)
            self.save()

    def customize(self, event=None):
        self.preset.set('Своя схема')
        self.save()

    def append(self, message):
        entry = time.strftime('%H:%M:%S') + '  ' + message
        self.last_event.set(message.splitlines()[0][:130])
        self.log.configure(state='normal')
        self.log.insert('end', entry + '\n')
        if int(self.log.index('end-1c').split('.')[0]) > 1000:
            self.log.delete('1.0', 'end-1000l')
        self.log.see('end')
        self.log.configure(state='disabled')
        with (ROOT / 'bot.log').open('a', encoding='utf-8') as output:
            output.write(entry + '\n')

    def start(self):
        if self.worker and self.worker.is_alive():
            return
        task, resource, repeat = self.tasks[self.mode.get()], self.resource.get(), self.repeat.get()
        if not self.save():
            return
        if not self.production.save():
            self.show_page('production')
            return
        production = self.production.snapshot()
        self.stop.clear()
        self.status.set('Работает')
        self.status_label.configure(fg=ACCENT)
        self.start_button.configure(state='disabled')
        self.stop_button.configure(state='normal')
        self.task_box.configure(state='disabled')
        self.resource_box.configure(state='disabled')
        self.repeat_box.configure(state='disabled')
        for control in self.plan_controls:
            control.configure(state='disabled')
        self.production.set_running(True)
        self.append('Запуск: ' + self.mode.get())
        self.append('Повтор: каждые 5 минут' if repeat else 'Повтор выключен: один проход')
        self.worker = threading.Thread(target=self.run, args=(task, resource, repeat, [v.get() for v in self.plan], production), daemon=True)
        self.worker.start()

    def run(self, task, resource, repeat, plan, production=None):
        bot = None
        try:
            from bot import Bot
            bot = Bot(log=lambda message: self.events.put(('log', message)), stop=self.stop,
                      allow_captcha=task != 'inspect')
            bot.connect()
            ordered_materials = bool(production and production['enabled'] and any(production['workshops']))
            while True:
                bot.observe()
                if task == 'inspect':
                    self.events.put(('log', 'Снимок получен; игра не изменена.\n' + bot.text()))
                elif task == 'search_resources':
                    bot.search_resources(resource)
                elif task == 'plan':
                    bot.run_plan(plan)
                elif task == 'production':
                    bot.production({**production, 'enabled': True})
                elif task == 'daily_actions':
                    if ordered_materials:
                        bot.production(production)
                        bot.observe()
                    bot.daily_actions(skip_materials=ordered_materials)
                elif task == 'cycle':
                    for action in (bot.help_all, bot.research, bot.supplies, bot.radar_rewards,
                                   lambda: bot.daily_actions(send_officers=True, skip_materials=ordered_materials), lambda: bot.run_plan(plan),
                                   lambda: bot.production(production), bot.personal_research):
                        bot.observe()
                        action()
                else:
                    getattr(bot, task)()
                self.events.put(('log', 'Проход завершён'))
                if not repeat:
                    break
                self.events.put(('log', 'Следующая проверка через 5 минут'))
                bot.wait(300)
            self.events.put(('done', 'Проход завершён'))
        except Exception as error:
            self.events.put(('done', 'Остановлен' if self.stop.is_set() else 'ПАУЗА: ' + str(error)))
        finally:
            if bot is not None:
                bot.close()

    def poll(self):
        try:
            while True:
                kind, message = self.events.get_nowait()
                self.append(message)
                if kind == 'done':
                    self.status.set(message)
                    self.status_label.configure(fg='#FFC1CC' if message.startswith('ПАУЗА') else TEXT)
                    self.start_button.configure(state='normal')
                    self.stop_button.configure(state='disabled')
                    self.task_box.configure(state='readonly')
                    self.resource_box.configure(state='readonly' if self.tasks[self.mode.get()] == 'search_resources' else 'disabled')
                    self.repeat_box.configure(state='normal')
                    for control in self.plan_controls:
                        control.configure(state='readonly')
                    self.production.set_running(False)
                    if message.startswith('ПАУЗА'):
                        self.show_page('log')
                        winsound.MessageBeep(winsound.MB_ICONEXCLAMATION)
        except queue.Empty:
            pass
        self.root.after(150, self.poll)

    def cancel(self):
        if self.worker and self.worker.is_alive():
            self.stop.set()
            self.status.set('Останавливается… выход к карте кампании' if self.tasks[self.mode.get()] == 'campaign'
                            else 'Останавливается… новые нажатия отменены')

    def emulator_window(self, command):
        try:
            output = subprocess.run(['C:/LDPlayer/LDPlayer9/ldconsole.exe', 'list2'],
                                    capture_output=True, timeout=5, creationflags=subprocess.CREATE_NO_WINDOW)
            if output.returncode:
                raise RuntimeError('Не удалось получить список окон LDPlayer')
            row = next((line.split(',') for line in output.stdout.decode(errors='replace').splitlines()
                        if line.startswith('0,')), None)
            if row is None or len(row) < 5 or row[4] != '1':
                raise RuntimeError('LDPlayer не запущен')
            handle = int(row[2])
            user32 = ctypes.WinDLL('user32', use_last_error=True)
            user32.IsWindow.argtypes = [ctypes.c_void_p]
            user32.IsWindowVisible.argtypes = [ctypes.c_void_p]
            user32.ShowWindow.argtypes = [ctypes.c_void_p, ctypes.c_int]
            if not handle or not user32.IsWindow(handle):
                raise RuntimeError('Окно LDPlayer недоступно')
            user32.ShowWindow(handle, command)
            if bool(user32.IsWindowVisible(handle)) != (command != 0):
                raise RuntimeError('Не удалось изменить видимость окна LDPlayer')
            self.emulator_hidden = command == 0
            self.window_hint.set('Окно скрыто · игра работает в фоне' if command == 0 else 'Окно LDPlayer показано')
            self.append({0: 'Окно LDPlayer скрыто; игра продолжает работать',
                         6: 'LDPlayer свёрнут', 9: 'Окно LDPlayer восстановлено'}[command])
        except Exception as error:
            self.append(str(error))

    def close(self):
        self.stop.set()
        if self.worker and self.worker.is_alive():
            self.status.set('Останавливается перед закрытием…')
            self.root.after(150, self.close)
        else:
            if self.emulator_hidden:
                self.emulator_window(9)
            self.root.destroy()


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--auto-farm', action='store_true', help='Запустить основной цикл с повтором каждые 5 минут')
    args = parser.parse_args()
    ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID('Warpath.PersonalHelper')
    panel = App(tk.Tk())
    if args.auto_farm:
        panel.repeat.set(True)
        panel.root.after(500, panel.start)
    panel.root.mainloop()
