"""Small native Tk controls: no browser, animation loop, or extra UI dependency."""
import tkinter as tk

BG = '#0D131C'
SIDE = '#101923'
CARD = '#16212E'
BORDER = '#2A394B'
TEXT = '#EDF3FA'
MUTED = '#A4B3C5'
ACCENT = '#94E5C0'


def rounded(canvas, width, height, fill, outline='', radius=12):
    r = min(radius, width / 2, height / 2)
    points = [r, 1, width-r, 1, width-1, 1, width-1, r, width-1, height-r,
              width-1, height-1, width-r, height-1, r, height-1, 1, height-1,
              1, height-r, 1, r, 1, 1]
    canvas.create_polygon(points, smooth=True, fill=fill, outline=outline, width=1)


class Panel(tk.Frame):
    def __init__(self, parent, padding=20, fill=CARD, **kwargs):
        # Native opaque panels avoid Tk's repeated repainting of overlapping canvases.
        super().__init__(parent, bg=fill, highlightbackground=BORDER,
                         highlightthickness=1, bd=0, **kwargs)
        self.body = tk.Frame(self, bg=fill)
        self.body.pack(fill='both', expand=True, padx=padding, pady=padding)


class Button(tk.Canvas):
    def __init__(self, parent, text, command, kind='secondary', width=150, height=46):
        super().__init__(parent, width=width, height=height, bg=parent.cget('bg'),
                         bd=0, highlightthickness=0, takefocus=1, cursor='hand2')
        self.label, self.command, self.kind = text, command, kind
        self.hover = self.focused = False
        self.bind('<Configure>', lambda event: self.draw())
        self.bind('<Enter>', lambda event: self.paint(hover=True))
        self.bind('<Leave>', lambda event: self.paint(hover=False))
        self.bind('<FocusIn>', lambda event: self.paint(focused=True))
        self.bind('<FocusOut>', lambda event: self.paint(focused=False))
        self.bind('<Button-1>', self.invoke)
        self.bind('<Return>', self.invoke)
        self.bind('<space>', self.invoke)

    def paint(self, **values):
        for key, value in values.items():
            setattr(self, key, value)
        self.draw()

    def draw(self):
        disabled = str(self.cget('state')) == 'disabled'
        fill, fg = {'primary': (ACCENT, '#10261D'), 'danger': ('#462C38', '#FFD0D8'),
                    'secondary': ('#223144', TEXT), 'nav': (SIDE, MUTED),
                    'selected': ('#1C3934', ACCENT)}[self.kind]
        if disabled:
            fill, fg = '#1B2532', '#7C8BA0'
        elif self.hover and self.kind != 'primary':
            fill = '#304357'
        self.delete('all')
        rounded(self, self.winfo_width(), self.winfo_height(), fill,
                ACCENT if self.focused and not disabled else '', 10)
        self.create_text(self.winfo_width()/2, self.winfo_height()/2, text=self.label,
                         fill=fg, font=('Segoe UI', 10, 'bold' if self.kind == 'primary' else 'normal'))

    def configure(self, cnf=None, **kwargs):
        result = super().configure(cnf, **kwargs)
        if hasattr(self, 'label'):
            if 'state' in kwargs:
                super().configure(takefocus=0 if kwargs['state'] == 'disabled' else 1,
                                  cursor='arrow' if kwargs['state'] == 'disabled' else 'hand2')
            self.draw()
        return result

    config = configure

    def invoke(self, event=None):
        if str(self.cget('state')) != 'disabled':
            self.command()
        return 'break'


def label(parent, text='', size=11, color=TEXT, bold=False, **kwargs):
    return tk.Label(parent, text=text, bg=parent.cget('bg'), fg=color,
                    font=('Segoe UI', size, 'bold' if bold else 'normal'), **kwargs)
