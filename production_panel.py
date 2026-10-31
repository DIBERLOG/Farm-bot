"""Small native editor for the four ordered manufacturing recipes."""
import tkinter as tk
from tkinter import ttk

from production import MATERIALS, DEFAULT, load_config, save_config, validate
from widgets import CARD, TEXT, MUTED, ACCENT, Panel, Button, label


class ProductionPanel:
    def __init__(self, parent, path):
        self.path = path
        self.controls = []
        try:
            self.config = load_config(path)
            warning = 'Схемы сохраняются отдельно от назначений сборщиков.'
        except (OSError, ValueError) as error:
            import copy
            self.config = copy.deepcopy(DEFAULT)
            self.config['enabled'] = False
            warning = 'Настройки не прочитаны; производство выключено: ' + str(error)
        self.current = 0
        self.enabled = tk.BooleanVar(value=self.config['enabled'])
        self.repeat = tk.BooleanVar(value=self.config['repeat'])
        self.limit = tk.StringVar(value=str(self.config['limit']))
        self.workshop = tk.StringVar(value='Мастерская 1')
        self.material = tk.StringVar(value=MATERIALS[2])
        self.count = tk.StringVar(value='1')
        self.message = tk.StringVar(value=warning)
        card = Panel(parent, padding=18)
        card.pack(fill='both', expand=True)
        body = card.body
        label(body, 'Очереди агрегатного завода', size=14, bold=True).pack(anchor='w')
        label(body, 'Шаги выполняются сверху вниз. Четыре мастерские производят параллельно.\nУже поставленные в игре задания сохраняются впереди новых.',
              size=10, color=MUTED, justify='left', wraplength=750).pack(anchor='w', pady=(8, 12))
        bar = tk.Frame(body, bg=CARD)
        bar.pack(fill='x')
        enabled = ttk.Checkbutton(bar, text='Включить в автоферму', variable=self.enabled)
        enabled.pack(side='left')
        repeat = ttk.Checkbutton(bar, text='Повторять последовательность', variable=self.repeat)
        repeat.pack(side='left', padx=20)
        self.controls += [(enabled, 'normal'), (repeat, 'normal')]
        options = tk.Frame(body, bg=CARD)
        options.pack(fill='x', pady=(8, 12))
        selector = ttk.Combobox(options, textvariable=self.workshop,
                               values=[f'Мастерская {n}' for n in range(1, 5)], state='readonly', width=18)
        selector.pack(side='left')
        selector.bind('<<ComboboxSelected>>', self.switch_workshop)
        label(options, 'Заполнять до', size=10).pack(side='left', padx=(22, 8))
        limit = ttk.Spinbox(options, textvariable=self.limit, from_=1, to=33, width=4)
        limit.pack(side='left')
        label(options, 'мест (максимум 33)', size=10, color=MUTED).pack(side='left', padx=8)
        self.controls += [(selector, 'readonly'), (limit, 'normal')]
        style = ttk.Style(body)
        style.configure('Production.Treeview', background='#202E40', fieldbackground='#202E40',
                        foreground=TEXT, rowheight=32, borderwidth=0)
        style.configure('Production.Treeview.Heading', background=CARD, foreground=MUTED, font=('Segoe UI', 10))
        style.map('Production.Treeview', background=[('selected', '#36574F')], foreground=[('selected', TEXT)])
        self.tree = ttk.Treeview(body, columns=('number', 'material', 'count'), show='headings',
                                 selectmode='browse', height=7, style='Production.Treeview')
        for key, title, width in [('number', 'Порядок', 80), ('material', 'Материал', 350), ('count', 'Количество', 110)]:
            self.tree.heading(key, text=title)
            self.tree.column(key, width=width, anchor='w' if key == 'material' else 'center', stretch=key == 'material')
        self.tree.pack(fill='both', expand=True)
        self.tree.bind('<<TreeviewSelect>>', self.select_row)
        editor = tk.Frame(body, bg=CARD)
        editor.pack(fill='x', pady=(14, 8))
        material = ttk.Combobox(editor, textvariable=self.material, values=MATERIALS, state='readonly', width=20)
        material.pack(side='left')
        count = ttk.Spinbox(editor, textvariable=self.count, from_=1, to=999, width=5)
        count.pack(side='left', padx=8)
        self.controls += [(material, 'readonly'), (count, 'normal')]
        for text, command in [('Добавить', self.add), ('Изменить', self.edit)]:
            button = Button(editor, text, command, width=108, height=40)
            button.pack(side='left', padx=4)
            self.controls.append((button, 'normal'))
        moves = tk.Frame(body, bg=CARD)
        moves.pack(fill='x')
        for text, command, width in [('↑ Выше', lambda: self.move(-1), 104),
                                     ('↓ Ниже', lambda: self.move(1), 104), ('Удалить шаг', self.remove, 140),
                                     ('Сохранить', self.save, 138)]:
            button = Button(moves, text, command, width=width, height=40,
                            kind='primary' if text == 'Сохранить' else 'secondary')
            button.pack(side='left', padx=(0, 8))
            self.controls.append((button, 'normal'))
        label(body, size=9, color=ACCENT, textvariable=self.message,
              wraplength=750, justify='left').pack(anchor='w', pady=(12, 0))
        self.render()

    def render(self, selected=None):
        self.tree.delete(*self.tree.get_children())
        for index, row in enumerate(self.config['workshops'][self.current]):
            self.tree.insert('', 'end', iid=str(index), values=(index + 1, row['material'], row['count']))
        if selected is not None:
            self.tree.selection_set(str(selected))
            self.tree.see(str(selected))

    def switch_workshop(self, event=None):
        self.current = int(self.workshop.get().split()[-1]) - 1
        self.render()

    def select_row(self, event=None):
        if selected := self.tree.selection():
            row = self.config['workshops'][self.current][int(selected[0])]
            self.material.set(row['material'])
            self.count.set(str(row['count']))

    def changed(self):
        self.message.set('Есть несохранённые изменения. Нажми «Сохранить» или «Запустить».')

    def row_value(self):
        row = {'material': self.material.get(), 'count': int(self.count.get())}
        candidate = {**self.config, 'workshops': [[row], [], [], []]}
        validate(candidate)
        return row

    def add(self):
        try:
            recipe = self.config['workshops'][self.current]
            if len(recipe) >= 20:
                raise ValueError('В одной мастерской допускается до 20 шагов')
            recipe.append(self.row_value())
            self.render(len(recipe) - 1)
            self.changed()
        except ValueError as error:
            self.message.set(str(error))

    def edit(self):
        if selected := self.tree.selection():
            try:
                index = int(selected[0])
                self.config['workshops'][self.current][index] = self.row_value()
                self.render(index)
                self.changed()
            except ValueError as error:
                self.message.set(str(error))

    def move(self, direction):
        if selected := self.tree.selection():
            index = int(selected[0])
            recipe = self.config['workshops'][self.current]
            target = index + direction
            if 0 <= target < len(recipe):
                recipe[index], recipe[target] = recipe[target], recipe[index]
                self.render(target)
                self.changed()

    def remove(self):
        if selected := self.tree.selection():
            self.config['workshops'][self.current].pop(int(selected[0]))
            self.render()
            self.changed()

    def snapshot(self):
        return validate({**self.config, 'enabled': self.enabled.get(), 'repeat': self.repeat.get(),
                         'limit': int(self.limit.get())})

    def save(self):
        try:
            candidate = self.snapshot()
            save_config(self.path, candidate)
            self.config = candidate
            self.message.set('Сохранено. Порядок применяется к новым заданиям; существующая очередь сохраняется.')
            return True
        except (ValueError, OSError) as error:
            self.message.set('Не сохранено: ' + str(error))
            return False

    def set_running(self, running):
        for control, state in self.controls:
            control.configure(state='disabled' if running else state)
