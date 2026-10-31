"""Conservative Warpath automation for the observed Russian 1920x1080 UI."""
import argparse
import json
import msvcrt
from pathlib import Path
import re
import subprocess
import threading
import time

import cv2
import numpy as np

from check_connection import connected_devices, png_size

ROOT = Path(__file__).resolve().parent


class Paused(RuntimeError):
    pass


def norm(value):
    return ' '.join(value.lower().replace('ё', 'е').split())


def donation_count(text):
    match = re.search(r'участие\s*:\s*(\d{1,2})\s*[/\[|] ?\s*20\b', norm(text))
    return int(match[1]) if match and 0 <= int(match[1]) <= 20 else None


def donation_next(count, draining):
    return count is not None and 0 < count <= 20 


def search_level(text):
    match = re.fullmatch(r'ур\.?\s*([0-9вбзoо]+)', norm(text))
    if not match:
        return None
    value = int(match[1].translate(str.maketrans('вбзoо', '86300')))
    return value if 1 <= value <= 20 else None


def campaign_progress(text):
    match = re.search(r'(\d+)/(\d+)', re.sub(r'\s+', '', text))
    if match:
        done, total = int(match[1]), int(match[2])
        if 0 <= done <= total <= 100 and total:
            return done, total
    return None


def resource_is_free(panel):
    text = norm(panel)
    return (re.search(r'(шахтер|фермер|нефтяник)\s+нет\b', text) is not None
            or re.fullmatch(r'нет\s+(шахтер|фермер|нефтяник)', text) is not None)


def supply_count(text):
    found = re.search(r'\((\d{1,2})/15\)', re.sub(r'\s+', '', text))
    return int(found[1]) if found and 0 <= int(found[1]) <= 15 else None


def radar_count(text):
    match = re.search(r'сохраненные миссии\s*:\s*(\d+)\s*/\s*(\d+)', norm(text))
    return int(match[1]) if match and 0 <= int(match[1]) <= int(match[2]) else None


def radar_ready_point(frame):
    # Notification dots vary with radar sweep lighting; use their colour and geometry.
    crop = frame[190:880, 170:1780]
    b, g, r = cv2.split(crop)
    mask = ((r > 160) & (g < 115) & (b < 145)).astype('uint8') * 255
    count, _, stats, centres = cv2.connectedComponentsWithStats(mask)
    for index in range(1, count):
        x, y, width, height, area = stats[index]
        if 10 <= width <= 28 and 10 <= height <= 28 and 65 <= area <= 500 and .65 < width/height < 1.5:
            cx, cy = centres[index]
            return round(cx)+170-38, round(cy)+190+40
    return None


class Bot:
    def __init__(self, log=print, stop=None, allow_captcha=True):
        self.log = log
        self.stop = stop or threading.Event()
        self.adb = 'C:/LDPlayer/LDPlayer9/adb.exe'
        self.serial = '127.0.0.1:5555'
        self.lines = []
        self.frame = None
        self.observed = 0
        self.lock = None
        self.allow_captcha = allow_captcha
        self._solving_captcha = False
        self.watch_attack = False

    def command(self, *args):
        if self.stop.is_set():
            raise Paused('Остановлено пользователем')
        p = subprocess.run([self.adb, *args], capture_output=True, timeout=15,
                           creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        if p.returncode:
            raise Paused(p.stderr.decode(errors='replace'))
        return p.stdout

    def connect(self):
        self.lock = (ROOT / '.controller.lock').open('a+b')
        self.lock.seek(0)
        try:
            msvcrt.locking(self.lock.fileno(), msvcrt.LK_NBLCK, 1)
        except OSError:
            self.lock.close()
            self.lock = None
            raise Paused('Уже работает другой экземпляр бота')
        self.command('connect', self.serial)
        if self.serial not in connected_devices(self.command('devices').decode(errors='replace')):
            raise Paused('Нет подключения к LDPlayer')

    def close(self):
        if self.lock:
            self.lock.seek(0)
            msvcrt.locking(self.lock.fileno(), msvcrt.LK_UNLCK, 1)
            self.lock.close()
            self.lock = None

    def wait(self, seconds):
        if self.stop.wait(seconds):
            raise Paused('Остановлено пользователем')

    def observe(self):
        data = self.command('-s', self.serial, 'exec-out', 'screencap', '-p')
        if png_size(data) != (1920, 1080):
            raise Paused('Нужно разрешение Android 1920x1080')
        self.observed = time.monotonic()
        path = ROOT / 'bot-screen.png'
        path.write_bytes(data)
        self.frame = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR)
        self.lines = self.read_ocr(path)
        text = self.text()
        if any(s in text for s in ('captcha', 'капча', 'проверка безопасности', 'подтвердите, что',
                                   'выберите все изображения', 'перетащите ползунок', 'потяните ползунок',
                                   'drag the slider', 'сложите пазл')):
            (ROOT / 'captcha-last.png').write_bytes(data)
            if not self.allow_captcha:
                return self
            if self._solving_captcha:
                raise Paused('Пазл не прошёл проверку после одного перемещения; повторять не буду')
            from puzzle import analyze_frame, load_profile
            try:
                profile = load_profile(ROOT / 'captcha-profile.json')
                if profile.get('enabled') is not True:
                    raise ValueError('Автоматический пазл не включён после калибровки')
                result, movement = analyze_frame(self.frame, profile)
            except ValueError as error:
                raise Paused(f'Проверка человека: {error}. Снимок сохранён в captcha-last.png') from error
            self.log(f'Пазл: совпадение {result.score:.2f}, отрыв {result.margin:.2f}; одна попытка')
            self._solving_captcha = True
            try:
                self.command('-s', self.serial, 'shell', 'input', 'swipe',
                             *(str(n) for n in movement), '700')
                self.wait(1.5)
                self.observe()
                self.log('Окно пазла больше не распознаётся; проверяю дальнейшее состояние игры')
            finally:
                self._solving_captcha = False
        if self.watch_attack:
            from emergency import attack_warning
            if attack_warning(self):
                raise Paused('Обнаружено предупреждение о нападении на базу')
        if not getattr(self, '_closing_offer', False):
            self.dismiss_offer()
        return self

    def dismiss_offer(self):
        """Close recognized shop promotions before a caller acts on the screen."""
        def visible():
            # Exclude the chat/footer; offer titles can also appear near the bottom.
            body = self.text((160, 30, 1900, 1005))
            if all(label in body for label in (
                    'мгновенно получите предметы', 'золота', 'лимит:', 'осталось:')):
                return True
            promotion = any(label in body for label in (
                'предложение', 'набор со скидкой', 'скидка', 'скидки',
                'супернабор', 'супер набор', 'только сегодня', 'успейте купить'))
            purchase = any(label in body for label in (
                'купить', 'приобрести', 'покупка', '₽', 'руб.', 'usd', '$', 'rub'))
            timed_bundle = ('лимит:' in body and 'осталось:' in body
                            and ('%' in body or purchase))
            return (promotion and purchase) or timed_bundle
        if not visible():
            return False
        self._closing_offer = True
        try:
            for _ in range(3):
                try:
                    close = self.point('закрыть', (160, 30, 1900, 1005))
                except Paused:
                    close = None
                if isinstance(close, tuple):
                    self.tap(*close)
                else:
                    self.back()
                if not visible():
                    self.log('Всплывающее предложение закрыто; продолжаю текущий этап')
                    return True
            raise Paused('Предложение не закрылось после трёх попыток')
        finally:
            self._closing_offer = False

    def read_ocr(self, path):
        result = subprocess.run(['powershell', '-NoProfile', '-File', str(ROOT / 'ocr.ps1'),
                                 '-ImagePath', str(path)], capture_output=True, timeout=20,
                                creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        if result.returncode:
            raise Paused('Ошибка Windows OCR: ' + result.stderr.decode(errors='replace'))
        lines = json.loads(result.stdout.decode('utf-8-sig'))
        return lines if isinstance(lines, list) else [lines] if lines else []

    def detail(self, region):
        x, y, right, bottom = region
        path = ROOT / 'detail.png'
        crop = cv2.resize(self.frame[y:bottom, x:right], None, fx=2, fy=2)
        crop = cv2.copyMakeBorder(crop, 100, 100, 30, 30, cv2.BORDER_REPLICATE)
        cv2.imencode('.png', crop)[1].tofile(path)
        return '\n'.join(norm(line['text']) for line in self.read_ocr(path))

    def text(self, region=None):
        return '\n'.join(norm(line['text']) for line in self.lines if self.in_region(line, region))

    @staticmethod
    def in_region(line, region):
        if not line['words']:
            return False
        if region is None:
            return True
        x, y, right, bottom = region
        return all(x <= w['x'] and y <= w['y'] and w['x'] + w['width'] <= right
                   and w['y'] + w['height'] <= bottom for w in line['words'])

    def has(self, text, region=None):
        return norm(text) in norm(self.text(region))

    def point(self, phrase, region=None):
        matches = [line for line in self.lines if norm(line['text']) == norm(phrase)
                   and self.in_region(line, region)]
        if len(matches) != 1:
            raise Paused(f'Кнопка «{phrase}» не определена однозначно')
        words = matches[0]['words']
        return (round((min(w['x'] for w in words) + max(w['x'] + w['width'] for w in words)) / 2),
                round((min(w['y'] for w in words) + max(w['y'] + w['height'] for w in words)) / 2))

    def require(self, *phrases):
        if not all(self.has(p) for p in phrases):
            self.wait(.5)
            self.observe()
            if not all(self.has(p) for p in phrases):
                raise Paused('Неожиданный экран; ожидалось: ' + ', '.join(phrases))

    def tap(self, x, y):
        if time.monotonic() - self.observed > 10:
            raise Paused('Снимок устарел; действие отменено')
        if not (0 <= x < 1920 and 0 <= y < 1080):
            raise Paused('Кнопка за границей экрана')
        self.command('-s', self.serial, 'shell', 'input', 'tap', str(x), str(y))
        self.observed = 0
        self.wait(.65)
        self.observe()

    def click(self, phrase, region=None):
        self.tap(*self.point(phrase, region))

    def back(self):
        self.command('-s', self.serial, 'shell', 'input', 'keyevent', '4')
        self.wait(.6)
        self.observe()

    def main(self):
        footer = self.detail((1055, 982, 1915, 1070))
        if not all(s in footer for s in ('офицеры', 'юниты', 'инвентарь', 'армия')):
            raise Paused('Не распознано главное меню игры')
        # A modal can leave footer text visible behind it: check actual footer brightness too.
        sample = self.frame[1036:1052, 1240:1260].mean()
        if sample < 100:
            raise Paused('Главное меню перекрыто окном')

    def production(self, config):
        from production import fill_queues, UncertainAddition
        try:
            fill_queues(self, config)
        except UncertainAddition as error:
            self.log('Производство приостановлено до освобождения очереди: ' + str(error))
            self.require('агрегатный завод', 'производство')
            self.back()
            self.main()

    def personal_research(self):
        from research_center import run
        run(self)

    def help_all(self):
        if not self.help_open():
            self.main()
            point = self.optional_template('help-shortcut.png', (214, 880, 260, 923),
                                           (150, 750, 390, 965))
            if point:
                self.tap(*point)
            if not self.help_open():
                # A request can disappear while the map shortcut is being pressed.
                # Only retry navigation after positively confirming the map again.
                self.main()
                self.tap(1646, 1023)
                self.require('инфо', 'участники', 'помощь')
                self.tap(1608, 955)
        self.require_help()
        point = self.help_all_point()
        if point:
            for _ in range(3):
                self.tap(*point)
                self.wait(1.2)
                self.observe()
                self.require_help()
                point = self.help_all_point()
                if not point:
                    break
            else:
                raise Paused('Помощь не подтверждена после трёх проверок; возможно, приходят новые запросы')
            self.log('Помощь всем оказана; активная кнопка исчезла или отключилась')
        else:
            self.log('Помощь: активной кнопки «Помощь всем» нет')
        self.require_help()
        self.tap(1536, 110)
        if all(self.has(p) for p in ('инфо', 'участники', 'помощь')):
            self.back()
        self.main()

    def help_open(self):
        # The long counter line is intermittently missed by OCR, especially at 100/100.
        return (self.has('монет вклада в альянс сегодня')
                or (self.optional_template('help-ready.png', (357, 94, 544, 143),
                                            (340, 80, 560, 155)) is not None
                    and self.optional_template('help-ready.png', (365, 193, 433, 260),
                                               (345, 175, 450, 275)) is not None))

    def require_help(self):
        if not self.help_open():
            self.wait(.8)
            self.observe()
            if not self.help_open():
                raise Paused('Не подтверждено окно помощи альянсу')

    def help_all_point(self):
        region = (700, 860, 1210, 1015)
        point = None
        for text in ('помощь всем', 'помочь всем', 'помогать всем'):
            if self.has(text, region):
                point = self.point(text, region)
                break
        if point is None:
            point = self.optional_template('help-ready.png', (813, 927, 1108, 969), region)
        if point is not None:
            x, y = point
            blue, green, red = self.frame[y+25:y+40, x-10:x+10].mean(axis=(0, 1))
            if blue > red + 20 and blue > green + 5:
                return point
        return None

    def research(self):
        from alliance_research import donate_all
        if self.has('исследования альянса') and self.has('награды за вклад'):
            self.tap(1536, 110)
        if not self.has('исследования альянса'):
            self.main()
            self.tap(1646, 1023)
            self.require('инфо', 'участники', 'помощь')
            self.tap(1131, 591)
        self.require('исследования альянса')
        donated = donate_all(self)
        self.tap(120, 45)
        self.require('инфо', 'участники', 'помощь')
        self.tap(120, 45)
        self.main()
        self.log(f'Пожертвования: выполнено {donated}; рекомендованные технологии проверяются первыми')

    def research_funded(self):
        return (self.has('уже на макс. уровне', (700, 930, 1230, 1010))
                or self.optional_template('research_full.png', (812, 921, 1105, 963),
                                          (770, 885, 1150, 995)) is not None)

    def donate_current_research(self, name, budget=20):
        count = donation_count(self.text((1000, 820, 1440, 883)))
        if count is None:
            count = donation_count(self.detail((1000, 820, 1440, 883)))
        if count is None:
            raise Paused('Не удалось прочитать число пожертвований')
        self.log(f'Пожертвования «{name}»: доступно {count}/20; начинаю от 1')
        sent = 0
        for _ in range(min(budget, 20)):
            if not donation_next(count, False):
                break
            self.require('награды за вклад', name)
            self.require_resource_button()
            previous = count
            self.tap(1205, 920)
            if self.research_funded() or self.research_in_progress():
                sent += 1
                self.log(f'«{name}»: финансирование завершено; проверяю другие карточки')
                break
            self.require('награды за вклад', name)
            count = donation_count(self.text((1000, 820, 1440, 883)))
            for _ in range(3):
                if count is not None and count < previous:
                    break
                self.wait(.8)
                self.observe()
                self.require('награды за вклад', name)
                count = donation_count(self.text((1000, 820, 1440, 883)))
                if count is None:
                    count = donation_count(self.detail((1000, 820, 1440, 883)))
            if count is None or count >= previous:
                raise Paused('Пожертвование не подтверждено уменьшением счётчика')
            sent += 1
            self.log(f'Пожертвование выполнено, осталось {count}/20')
        return sent

    def research_in_progress(self):
        return (self.optional_template('research-progress.png', (866, 776, 909, 813),
                                       (840, 750, 935, 840)) is not None
                and not self.has('сделайте вклад'))

    def require_resource_button(self):
        self.require('сделайте вклад')
        # Only the observed right-hand blue ordinary-resource button is allowed.
        b, g, r = self.frame[895:940, 1018:1040].mean(axis=(0, 1))
        if not (b > r + 15 and b > g):
            raise Paused('Кнопка пожертвования за ресурсы не активна')
        price = re.sub(r'\s+', '', self.text((1000, 945, 1420, 1000)))
        if not price:
            price = re.sub(r'\s+', '', self.detail((1185, 945, 1325, 995)))
        if not price:
            crop = cv2.cvtColor(self.frame[950:990,1200:1295],cv2.COLOR_BGR2GRAY)
            mask = cv2.threshold(crop,105,255,cv2.THRESH_BINARY)[1]
            path = ROOT / 'donation-price-ocr.png'
            cv2.imencode('.png',cv2.copyMakeBorder(cv2.resize(mask,None,fx=3,fy=3),
                80,80,80,80,cv2.BORDER_CONSTANT,value=255))[1].tofile(path)
            price = re.sub(r'\s+','',''.join(line['text'] for line in self.read_ocr(path)))
        # Keep the observed 3000-resource button, and recognise oil for other prices.
        oil = self.optional_template('research-local-current.png', (1143, 944, 1186, 992),
                                     (1125, 930, 1205, 1005))
        conqueror_oil = self.optional_template('research-conqueror.png', (1143, 944, 1186, 992),
                                               (1125, 930, 1205, 1005))
        oil_price = (price.isdigit() and 0 < int(price) <= 1000000
                     and (oil is not None or conqueror_oil is not None))
        if price != '3000' and not oil_price:
            raise Paused('Стоимость пожертвования изменилась; нужна проверка')

    def army_refill(self):
        from army import refill
        refill(self)

    def open_supply_menu(self):
        self.main()
        # Center the user's base using the already observed bottom-left locator.
        self.tap(95, 985)
        self.wait(.8)
        self.observe()
        self.main()
        if self.optional_template('base.png', (62, 949, 122, 1020), (40, 935, 140, 1040)):
            # Base interior: toggle once back to world map.
            self.tap(95, 985)
            self.wait(.8)
            self.observe()
            self.main()
        self.tap(960, 510)
        self.require('командный пункт')
        self.template('supply_ready.png', (495, 350, 635, 377))
        count = supply_count(self.text())
        if count is None:
            count = supply_count(self.detail((1080, 620, 1330, 750)))
        if count is None:
            # White outlined digits are lost by Windows OCR on the coloured map.
            crop = cv2.cvtColor(self.frame[640:730, 1120:1280], cv2.COLOR_BGR2GRAY)
            mask = cv2.threshold(crop, 200, 255, cv2.THRESH_BINARY_INV)[1]
            mask = cv2.copyMakeBorder(cv2.resize(mask, None, fx=3, fy=3),
                                      100, 100, 100, 100, cv2.BORDER_CONSTANT, value=255)
            path = ROOT / 'supply-counter-ocr.png'
            cv2.imencode('.png', mask)[1].tofile(path)
            caption = ' '.join(line['text'] for line in self.read_ocr(path))
            count = supply_count(caption)
            if count is None:
                crop = cv2.cvtColor(self.frame[695:728, 1152:1233], cv2.COLOR_BGR2GRAY)
                digits = cv2.threshold(crop, 220, 255, cv2.THRESH_BINARY_INV)[1]
                digits = cv2.copyMakeBorder(cv2.resize(digits, None, fx=2, fy=2),
                                            100, 100, 100, 100, cv2.BORDER_CONSTANT, value=255)
                cv2.imencode('.png', digits)[1].tofile(path)
                count = supply_count(' '.join(line['text'] for line in self.read_ocr(path)))
        if count is None:
            # Outlined digits vary with the map lighting; do not give up after one scale.
            crop = cv2.cvtColor(self.frame[695:728,1150:1238],cv2.COLOR_BGR2GRAY)
            for scale, threshold in ((4,200),(2,200),(2,180),(3,220),(3,180),(4,220)):
                mask = cv2.threshold(crop,threshold,255,cv2.THRESH_BINARY_INV)[1]
                path = ROOT / 'supply-counter-ocr.png'
                cv2.imencode('.png',cv2.copyMakeBorder(cv2.resize(mask,None,fx=scale,fy=scale),
                    100,100,100,100,cv2.BORDER_CONSTANT,value=255))[1].tofile(path)
                count = supply_count(' '.join(line['text'] for line in self.read_ocr(path)))
                if count is not None:
                    break
        if count is None:
            for filename, value in (('supply-counter-13-day.png',13),('supply-counter-13.png',13),('supply-counter-10.png',10)):
                source = cv2.imdecode(np.fromfile(ROOT/filename,np.uint8),1)
                score = cv2.matchTemplate(self.frame[692:733,1148:1240],source[697:727,1154:1233],cv2.TM_CCOEFF_NORMED)
                if cv2.minMaxLoc(score)[1] >= .97:
                    count = value
                    break
        if count is None:
            timer = caption
            timer_pattern = r'\d[\d\sзбoо.,•ь:\-]{0,8}(?:мин|сек)'
            if not re.search(timer_pattern, norm(timer)):
                timer = self.detail((1110, 640, 1290, 695))
            if re.search(timer_pattern, norm(timer)):
                self.log(f'Воздушные поставки: подтверждён таймер «{timer.strip()}»')
                return None
            raise Paused('Не удалось прочитать остаток воздушных поставок; таймер не подтверждён')
        return count

    def supplies(self):
        previous = None
        total = 0
        for _ in range(16):
            try:
                count = self.open_supply_menu()
            except Paused:
                # Existing crates must still be collected if the call counter is unreadable.
                if self.has('командный пункт'):
                    self.back()
                    total += self.collect_supplies()
                raise
            if count is None or count == 0:
                self.back()
                total += self.collect_supplies()
                self.log('Воздушные поставки: остаток 0/15, все доступные ящики проверены'
                         if count == 0 else 'Воздушные поставки: вызов временно недоступен; сбор проверен, продолжу после таймера в следующем проходе')
                return total
            if previous is not None and count >= previous:
                self.back()
                raise Paused(f'Воздушные поставки: остаток не уменьшился ({count}/15); повтор вызова отменён')
            self.log(f'Воздушные поставки: доступно {count}/15; вызываю следующую')
            self.tap(*self.template('supply_ready.png', (1167, 565, 1213, 626)))
            if self.has('командный пункт'):
                self.back()
            total += self.collect_supplies(wait_for_drop=True)
            previous = count
        raise Paused('Воздушные поставки: остаток не достиг нуля после 15 вызовов')

    def supply_label_point(self, region=(180, 220, 1780, 950)):
        labels = [line for line in self.lines
                  if norm(line['text']).strip(' .:—') == 'воздушные поставки'
                  and self.in_region(line, region)]
        if not labels:
            # OCR can split the same crate label into two vertically adjacent lines.
            first = [line for line in self.lines if norm(line['text']) == 'воздушные'
                     and self.in_region(line, region)]
            second = [line for line in self.lines if norm(line['text']) == 'поставки'
                      and self.in_region(line, region)]
            for upper in first:
                a = upper['words']
                ax = sum(w['x'] + w['width']/2 for w in a)/len(a)
                ay = max(w['y'] + w['height'] for w in a)
                for lower in second:
                    b = lower['words']
                    bx = sum(w['x'] + w['width']/2 for w in b)/len(b)
                    by = min(w['y'] for w in b)
                    if abs(ax-bx) < 70 and 0 <= by-ay <= 35:
                        labels.append({'words': a+b})
                        break
                if labels:
                    break
        if labels:
            words = labels[0]['words']
            return (round((min(w['x'] for w in words) + max(w['x'] + w['width'] for w in words))/2),
                    round((min(w['y'] for w in words) + max(w['y'] + w['height'] for w in words))/2))
        for filename, rectangle in (('supply_loot.png', (1113, 455, 1340, 479)),
                                     ('supply-label-tap.png', (951, 479, 1180, 503)),
                                     ('supply-lower-before.png', (825, 865, 1045, 900))):
            point = self.optional_template(filename, rectangle, region)
            if point is not None:
                return point
        return None

    def dismiss_new_unit(self):
        text = self.text()
        if 'новинка' not in text:
            return False
        for _ in range(2):
            self.back()
            if 'новинка' not in self.text():
                self.log('Представление нового юнита закрыто; продолжаю сбор наград')
                return True
        (ROOT/'new-unit-unclosed.png').write_bytes((ROOT/'bot-screen.png').read_bytes())
        raise Paused('Представление нового юнита не закрылось; снимок new-unit-unclosed.png сохранён')

    def collect_supplies(self, wait_for_drop=False):
        if wait_for_drop:
            self.log('Поставка вызвана; жду приземления ящиков')
            self.wait(2.5)
            self.observe()
        collected = quiet = 0
        while collected < 18:
            self.main()
            point = self.supply_label_point()
            if point is None:
                quiet += 1
                quiet_limit = 12 if wait_for_drop and collected == 0 else 3
                if quiet < quiet_limit:
                    self.wait(1)
                    self.observe()
                    continue
                if wait_for_drop and collected == 0:
                    self.log('Поставка вызвана, но приземлившиеся ящики пока не обнаружены; проверю в следующем проходе')
                else:
                    self.log(f'Воздушные поставки: собрано ящиков {collected}; оставшихся меток рядом с базой нет')
                return collected
            quiet = 0
            # Labels select the crate even when its model is hidden behind HQ.
            # A tap above the label can select the HQ tower instead.
            self.tap(*point)
            loot = self.optional_template('supply_loot.png', (1202, 578, 1248, 627))
            if loot is None:
                self.wait(.8)
                self.observe()
                loot = self.template('supply_loot.png', (1202, 578, 1248, 627))
            self.tap(*loot)
            self.wait(.8)
            self.observe()
            if self.rewards_open():
                self.confirm_rewards()
            self.dismiss_new_unit()
            self.main()
            x, y = point
            around = (max(180, x - 150), max(220, y - 40), min(1780, x + 150), min(950, y + 40))
            if self.supply_label_point(around) is not None:
                self.wait(.8)
                self.observe()
                self.main()
                if self.supply_label_point(around) is not None:
                    raise Paused('Получение поставки не подтверждено исчезновением выбранного ящика')
            collected += 1
            self.log(f'Воздушный ящик №{collected}: военные трофеи получены, метка ящика исчезла')
        raise Paused('Лимит поставок за один проход; проверь экран')

    def optional_template(self, filename, rectangle, region=None):
        try:
            return self.template(filename, rectangle, region)
        except Paused:
            return None

    def rewards_open(self):
        return (self.optional_template('radar_rewards.png', (815, 167, 1106, 219),
                                       (700, 130, 1220, 250)) is not None
                or (self.has('награды', (700, 130, 1220, 250))
                    and self.has('подтвердить', (780, 900, 1140, 1015))))

    def confirm_rewards(self):
        if not self.rewards_open():
            raise Paused('Не подтверждено окно получения наград')
        point = self.optional_template('radar_rewards.png', (853, 942, 1069, 978), (780, 900, 1140, 1015))
        if point is None:
            point = self.point('подтвердить', (780, 900, 1140, 1015))
        self.tap(*point)
        if self.rewards_open():
            raise Paused('Окно наград не закрылось')
        self.log('Награды подтверждены')

    def officer_report_open(self):
        return self.optional_template('officer_report.png', (241, 117, 532, 149),
                                      (210, 98, 560, 165)) is not None

    def confirm_officer_report(self):
        if not self.officer_report_open():
            raise Paused('Не подтвержден отчёт о миссиях офицеров')
        point = self.template('officer_report.png', (834, 960, 1092, 1001),
                              (760, 915, 1165, 1035))
        self.tap(*point)
        self.wait(.8)
        self.observe()
        if self.officer_report_open():
            raise Paused('Отчёт о миссиях не закрылся')
        self.log('Награды завершённых миссий офицеров подтверждены')

    def radar_screen(self):
        self.template('radar_missions.png', (211, 27, 344, 66), (195, 15, 365, 82))

    def radar_rewards(self):
        self.main()
        self.tap(74, 577)
        self.wait(1.5)  # Mission markers and the bulk button arrive after the radar animation.
        self.observe()
        self.radar_screen()
        claimed = False
        bulk_attempted = 0
        for _ in range(80):
            if self.rewards_open():
                self.confirm_rewards()
                claimed = True
                self.wait(.8)
                self.observe()
                self.radar_screen()
                continue
            self.radar_screen()
            if not bulk_attempted:
                point = self.optional_template('radar_missions.png', (1472,851,1742,899),
                                               (1440,825,1775,935))
                bulk_attempted += 1
                if point:
                    self.tap(*point)
                    self.wait(1.5)
                    self.observe()
                    continue
            marker = radar_ready_point(self.frame)
            if not marker:
                count = radar_count(self.text((170, 130, 720, 215)))
                if count is None:
                    count = radar_count(self.detail((170, 130, 720, 215)))
                point = self.optional_template('radar_missions.png', (1472, 851, 1742, 899),
                                               (1440, 825, 1775, 935))
                if point and bulk_attempted < 2:
                    bulk_attempted += 1
                    self.tap(*point)
                    self.wait(1.5)
                    self.observe()
                    continue
                if count == 0:
                    # Zero counts stored missions, not remaining rewards. Give animations
                    # time to reveal their final markers after the bulk collection too.
                    self.wait(1.2)
                    self.observe()
                    self.radar_screen()
                    if self.rewards_open() or radar_ready_point(self.frame):
                        continue
                    self.log('Радар: сохранённые миссии 0; оставшиеся награды дополнительно проверены')
                    break
                self.log(f'Радар: сохранено миссий {count}; доступных для сбора наград не обнаружено')
                break
            self.tap(*marker)
            self.wait(.8)
            self.observe()
            if not self.rewards_open():
                self.radar_screen()
                self.log('Радар: выбранная метка не открыла награду; сбор не подтверждён, продолжаю другие этапы')
                break
        else:
            raise Paused('Достигнут лимит наград радара за проход')
        self.log('Радар: получение завершено' if claimed else 'Радар: готовых наград нет')
        self.radar_screen()
        self.back()
        self.main()

    def mission_screen(self):
        self.template('missions_claim.png', (315, 95, 485, 132), (295, 78, 505, 145))

    def daily_screen(self):
        self.mission_screen()
        self.template('daily.png', (333, 207, 469, 230), (320, 190, 485, 240))

    def daily_top(self):
        self.daily_screen()
        self.command('-s', self.serial, 'shell', 'input', 'swipe', '1450', '430', '1450', '1020', '200')
        self.wait(.7)
        self.observe()
        self.daily_screen()

    def daily_chest_claimed(self, index):
        center = 698 + index * 221
        return self.optional_template('daily.png', (689, 287, 708, 306),
                                      (center - 24, 273, center + 24, 321)) is not None

    def daily_activity(self):
        mask = cv2.inRange(self.frame[248:299, 350:460], (205, 205, 205), (255, 255, 255))
        glyphs = [c for c in cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)[0]
                  if cv2.contourArea(c) > 20]
        # Windows OCR often omits isolated digits; only 0 and 5 are possible below ten.
        if len(glyphs) == 1:
            for value, filename, box in ((0, 'daily-current.png', (393, 253, 415, 295)),
                                         (5, 'daily-claim.png', (407, 253, 430, 295))):
                if self.optional_template(filename, box, (350, 248, 460, 300)):
                    return value
        image = cv2.resize(255 - mask, None, fx=4, fy=4)
        image = cv2.copyMakeBorder(image, 100, 100, 100, 100, cv2.BORDER_CONSTANT, value=255)
        path = ROOT / 'activity-ocr.png'
        cv2.imencode('.png', image)[1].tofile(path)
        value = ''.join(line['text'] for line in self.read_ocr(path))
        value = re.sub(r'\s+', '', value)
        if not re.fullmatch(r'\d{1,3}', value) or int(value) > 500:
            if self.optional_template('daily-activity-30.png', (374, 253, 434, 296), (350, 248, 460, 300)):
                return 30
            # Windows OCR also omits this exact two-digit glyph pair entirely.
            if self.optional_template('daily-90.png', (374, 253, 434, 296), (350, 248, 460, 300)):
                return 90
            raise Paused('Не удалось прочитать ежедневную активность')
        return int(value)

    def daily_ready_card(self):
        for row in range(2):
            for column in range(5):
                left, top = 330 + column * 303, 389 + row * 370
                if self.optional_template('daily-current.png', (329, 390, 341, 420),
                                          (left-4, top-4, left+22, top+42)):
                    return left + 140, top + 185
        return None

    def daily_task_rewards(self):
        self.daily_screen()
        for _ in range(20):
            point = self.daily_ready_card()
            if point is None:
                self.log('Готовые награды ежедневных заданий проверены')
                return
            previous = self.daily_activity()
            self.tap(*point)
            self.wait(.8)
            self.observe()
            if self.rewards_open():
                self.confirm_rewards()
            self.daily_screen()
            current = self.daily_activity()
            if current <= previous:
                raise Paused('Получение наград заданий не подтверждено ростом активности')
            self.log(f'Награды ежедневных заданий получены; активность {previous} → {current}')
        raise Paused('Достигнут лимит наград ежедневных заданий за проход')

    def daily_chests(self):
        self.daily_screen()
        activity = self.daily_activity()
        for index, threshold in enumerate((20, 40, 60, 80, 100, 120)):
            if self.daily_chest_claimed(index):
                continue
            if activity < threshold:
                self.log(f'Сундук за {threshold}: нужно ещё {threshold - activity} активности')
                continue
            # These six fixed slots only expose activity rewards or their locked tooltip.
            self.tap(660 + 221 * index, 275)
            if self.rewards_open():
                self.confirm_rewards()
                self.daily_screen()
                if not self.daily_chest_claimed(index):
                    raise Paused(f'Не подтверждено получение сундука за {threshold}')
                self.log(f'Получен сундук активности за {threshold}')
            else:
                self.daily_screen()
                self.log(f'Сундук за {threshold}: получение пока недоступно')
                self.tap(165, 350)
                self.daily_screen()

    def mission_rewards(self, send_officers=False):
        self.main()
        self.tap(74, 699)
        self.mission_screen()
        self.tap(165, 230)
        self.mission_screen()
        point = self.optional_template('missions_claim.png', (944, 924, 1200, 965),
                                       (850, 894, 1285, 995))
        if point:
            self.tap(*point)
            self.wait(1)
            self.observe()
            if self.rewards_open():
                self.confirm_rewards()
            else:
                raise Paused('Получение наград миссий не подтверждено')
        self.mission_screen()
        self.tap(165, 350)
        self.daily_top()
        self.daily_task_rewards()
        self.daily_chests()
        self.log('Сундуки ежедневной активности проверены')
        self.tap(165, 475)
        self.mission_screen()
        self.claim_officer_rewards()
        if send_officers:
            self.dispatch_officer_missions()
        self.mission_screen()
        self.tap(1814, 108)
        self.main()

    def daily_actions(self, send_officers=False, skip_materials=False):
        from daily_tasks import run_daily
        run_daily(self, send_officers=send_officers, skip_materials=skip_materials)

    def claim_officer_rewards(self):
        self.mission_screen()
        point = self.optional_template('officer_missions.png', (1484, 922, 1757, 971),
                                       (1405, 880, 1830, 1000))
        if point:
            self.tap(*point)
            self.wait(1.2)
            self.observe()
            if self.officer_report_open():
                self.confirm_officer_report()
            elif self.rewards_open():
                self.confirm_rewards()
            else:
                self.mission_screen()
                self.log('Миссии офицеров: окно наград не появилось')
        self.mission_screen()

    def officer_missions(self):
        self.main()
        self.tap(74, 699)
        self.mission_screen()
        self.tap(165, 475)
        self.claim_officer_rewards()
        self.dispatch_officer_missions()
        self.tap(1814, 108)
        self.main()

    def officer_candidates(self):
        source = cv2.imdecode(np.fromfile(ROOT / 'officer_missions.png', np.uint8), 1)
        marker = source[555:592, 996:1021]
        result = cv2.matchTemplate(self.frame[270:805, 315:1830], marker, cv2.TM_CCOEFF_NORMED)
        points = []
        for _ in range(12):
            _, score, _, position = cv2.minMaxLoc(result)
            if score < .92:
                break
            x, y = position
            points.append((x + 327, y + 288))
            result[max(0, y-25):y+40, max(0, x-25):x+40] = 0
        return sorted(points, key=lambda point: (point[1], point[0]))

    def officer_card_key(self, point):
        x, y = point
        return norm(self.detail((x-520, y-110, x+20, y-40)))

    def officer_selection(self):
        self.template('officer-select.png', (215, 77, 623, 115), (185, 55, 700, 135))

    def officer_send_enabled(self):
        self.officer_selection()
        if not self.has('отправить', (1000, 850, 1425, 985)):
            return False
        blue, green, red = self.frame[875:895, 1030:1050].mean(axis=(0, 1))
        return red > blue + 35 and green > blue + 20

    def dispatch_officer_missions(self):
        self.mission_screen()
        attempted = set()
        launched = 0
        previous_page = None
        # Up to four pages; unavailable officers are retried on the next scheduled pass.
        for _page in range(4):
            for _mission in range(20):
                self.mission_screen()
                candidates = self.officer_candidates()
                choice = None
                visible_keys = []
                for point in candidates:
                    key = self.officer_card_key(point)
                    if not key or 'в процессе' in key or 'отчет' in key:
                        continue
                    visible_keys.append(key)
                    if key not in attempted and choice is None:
                        choice = point, key
                if choice is None:
                    break
                point, key = choice
                attempted.add(key)
                # The padlock belongs to pinning a mission. Open the card, not the lock.
                self.observe()
                self.mission_screen()
                self.tap(point[0] - 300, point[1] - 50)
                self.officer_selection()
                name = self.detail((290, 160, 870, 220))
                self.tap(*self.template('officer-select.png', (550, 900, 876, 944),
                                       (500, 850, 930, 990)))
                self.wait(.6)
                self.observe()
                if not self.officer_send_enabled():
                    self.log(f'Миссия «{name}»: быстрый выбор не дал доступной отправки; пропускаю')
                    self.tap(1712, 90)
                    self.mission_screen()
                    continue
                self.tap(1215, 915)
                self.wait(1.2)
                self.observe()
                self.mission_screen()
                remaining = [self.officer_card_key(p) for p in self.officer_candidates()]
                if key in remaining:
                    raise Paused('Отправка миссии офицеров не подтверждена изменением списка')
                launched += 1
                self.log(f'Миссия «{name}»: офицеры отправлены через быстрый выбор')
            else:
                raise Paused('Достигнут лимит отправок офицеров за проход')
            signature = tuple(visible_keys)
            if signature == previous_page:
                break
            previous_page = signature
            self.mission_screen()
            self.command('-s', self.serial, 'shell', 'input', 'swipe', '1450', '740', '1450', '360', '450')
            self.wait(.7)
            self.observe()
        self.log(f'Миссии офицеров: новых отправок {launched}; платное обновление не используется')

    def template(self, filename, rectangle, region=None):
        source = cv2.imdecode(np.fromfile(ROOT / filename, np.uint8), cv2.IMREAD_COLOR)
        x, y, right, bottom = rectangle
        template = source[y:bottom, x:right]
        rx, ry, rr, rb = region or (0, 0, 1920, 1080)
        score = cv2.matchTemplate(self.frame[ry:rb, rx:rr], template, cv2.TM_CCOEFF_NORMED)
        _, best, _, position = cv2.minMaxLoc(score)
        if best < .92:
            raise Paused('Не распознана кнопка: ' + filename)
        return rx + position[0] + (right-x)//2, ry + position[1] + (bottom-y)//2

    def campaign_result(self):
        if self.optional_template('campaign-sea-victory.png', (742, 204, 1168, 298), (710, 180, 1200, 325)):
            return 'victory'
        if self.optional_template('battle_victory.png', (742, 204, 1168, 298),
                                  (710, 180, 1200, 325)):
            return 'victory'
        if self.optional_template('campaign_defeat.png', (643, 119, 1216, 234),
                                  (610, 90, 1250, 265)):
            return 'defeat'
        return None

    def battle_open(self):
        return self.optional_template('battle.png', (32, 164, 176, 196),
                                      (15, 135, 200, 210)) is not None

    def return_campaign_victory(self):
        for _ in range(4):
            self.wait(.8)
            self.observe()
            if self.campaign_result() != 'victory':
                raise Paused('Экран победы изменился до получения наград')
            point = self.optional_template('battle_victory.png', (873, 900, 1044, 939),
                                            (785, 860, 1140, 975))
            if point is None:
                point = self.optional_template('campaign-sea-victory.png', (873, 900, 1044, 939), (785, 860, 1140, 975))
            if point:
                self.tap(*point)
                self.wait(4)
                self.observe()
                return
        raise Paused('Не появилась кнопка возврата после победы')

    def campaign_target(self):
        # Match the distinctive Raven symbol and its brown/red background together.
        # The game can position these badges inside the viewport as well as at its edges.
        try:
            x, y = self.template('battle.png', (855, 1028, 875, 1048))
        except Paused:
            x, y = self.template('campaign-sea-battle.png', (1093, 23, 1127, 61), (460, 0, 1910, 750))
        b, g, r = self.frame[y-10:y+10, x-10:x+10].mean(axis=(0, 1))
        if not (r > b + 15 and r > g + 8) or (x >= 1055 and 835 <= y <= 970):
            raise Paused('Не подтверждён значок противника «Ворона»')
        return min(max(x, 480), 1750), min(max(y, 350), 740 if x > 1050 else 790)

    def pause_campaign(self):
        # The game's menu does not freeze combat. Stop exits the unfinished battle.
        # A separate flag permits only this verified cleanup after the user presses Stop.
        guard = Bot(log=self.log, allow_captcha=False)
        try:
            guard.observe()
            if guard.campaign_result():
                return
            if guard.battle_open():
                if not guard.optional_template('battle_paused.png', (648, 275, 767, 399),
                                               (610, 250, 800, 430)):
                    guard.tap(100, 50)
                guard.template('battle_paused.png', (648, 275, 767, 399),
                               (610, 250, 800, 430))
                guard.tap(1210, 350)
                guard.wait(1)
                guard.observe()
                if not guard.has('скорость пополнения'):
                    guard.require('наземная', 'кампания')
                self.log('Незавершённый бой остановлен; выполнен выход к карте кампании')
        except Exception as error:
            self.log('Не удалось подтвердить выход из боя: ' + str(error))

    def campaign_mode(self):
        if self.optional_template('campaign-sea-map.png', (1698, 828, 1782, 904), (1680, 810, 1800, 925)):
            return 'sea'
        if self.has('морская', (1650, 900, 1910, 1030)) and self.has('кампания', (1650, 900, 1910, 1030)):
            return 'land'
        return None

    def enter_campaign(self, mode="land"):
        if mode not in ('land', 'sea'):
            raise ValueError('Неизвестный вид кампании')
        current = self.campaign_mode()
        if current is None:
            self.main()
            self.tap(74, 699)
            self.mission_screen()
            self.tap(165, 230)
            self.mission_screen()
            if not self.has('кампании', (490, 260, 1500, 325)):
                raise Paused('Не найдена миссия перехода в кампанию')
            self.click('вперед', (1600, 270, 1820, 400))
            self.require('наземная', 'кампания')
            self.tap(*self.template('campaign-entry-label.png', (902, 805, 1019, 855), (700, 650, 1100, 900)))
            self.wait(1)
            self.observe()
            current = self.campaign_mode()
        if current is None:
            raise Paused('Не определён текущий вид кампании')
        if current != mode:
            self.tap(1740, 875)
            self.wait(1)
            self.observe()
        if self.campaign_mode() != mode:
            raise Paused('Переключение вида кампании не подтверждено')

    def campaign_refill(self):
        from campaign_supply import collect
        collect(self)

    def sea_autoattack(self):
        target_x, target_y = self.template('campaign-sea-battle.png', (1093, 23, 1127, 61), (460, 0, 1910, 750))
        self.tap(min(max(target_x, 480), 1650), min(max(target_y, 350), 740))
        if not self.has('автоатака'):
            raise Paused('Бой не продвигается: автоатака к оставшимся целям недоступна')
        self.click('автоатака')

    def campaign(self, mode="land"):
        """Bounded native attack-move strategy; unsupported objectives pause."""
        try:
            self.enter_campaign(mode)
            for stage in range(3):
                if mode == 'sea':
                    self.require('наземная', 'кампания')
                else:
                    self.require('скорость пополнения')
                self.template('campaign-sea-map.png' if mode == 'sea' else 'campaign.png', (835, 944, 1080, 979), (800, 920, 1110, 1005))
                self.tap(960, 866)
                self.require('задание', 'награды')
                if mode == 'sea':
                    self.require('уничтожьте все войска флота')
                else:
                    self.template('campaign_start.png', (632, 364, 1288, 399), (600, 340, 1320, 425))
                level_text = self.text((330, 70, 1400, 160)).strip()
                level_number = re.search(r'\b\d+-\d+\b', level_text)
                self.campaign_level = level_number[0] if level_number else level_text
                self.log(f'Кампания: бой {stage + 1}/3; {self.campaign_level}')
                self.tap(960, 933)
                if self.has('ваш враг слишком силен'):
                    self.tap(1209, 780)
                self.wait(2)
                self.observe()
                if not self.battle_open():
                    raise Paused('Не подтверждён экран тактического боя')
                cv2.imencode('.png', self.frame)[1].tofile(ROOT / 'campaign-last-battle.png')
                b, g, r = self.frame[780:810, 1430:1450].mean(axis=(0, 1))
                if not (r > b + 50 and g > b + 40):
                    self.tap(1468, 794)
                if mode == 'sea':
                    self.sea_autoattack()
                else:
                    target = self.campaign_target()
                    self.tap(*target)
                    if self.has('нельзя переместить в указанное место'):
                        raise Paused('Бой не продвигается: выбранная точка атаки недоступна')
                    self.tap(*self.template('battle_attack_menu.png', (945, 939, 986, 983)))
                self.log('Отрядам дана команда «Автоатака»')
                started = changed = time.monotonic()
                previous = None
                retargeted = time.monotonic()
                while True:
                    self.wait(4)
                    self.observe()
                    result = self.campaign_result()
                    if result == 'defeat':
                        raise Paused('Поражение в кампании; повторный бой не запускается')
                    if result == 'victory':
                        self.log('Кампания: победа')
                        self.return_campaign_victory()
                        break
                    if not self.battle_open():
                        self.wait(1.5)
                        self.observe()
                        if self.campaign_result() == 'victory':
                            self.return_campaign_victory()
                            break
                        if not self.battle_open():
                            raise Paused('Неизвестный экран во время боя')
                    progress = campaign_progress(self.detail((20, 215, 460, 320)))
                    if progress is not None and progress != previous:
                        previous = progress
                        changed = time.monotonic()
                        self.log(f'Кампания: уничтожено {progress[0]}/{progress[1]}')
                    if mode == 'sea' and time.monotonic() - changed > 20 and time.monotonic() - retargeted > 20:
                        self.sea_autoattack()
                        retargeted = time.monotonic()
                        self.log('Морская кампания: повторное наведение на оставшиеся цели')
                    if time.monotonic() - started > 240 or time.monotonic() - changed > 90:
                        raise Paused('Бой не продвигается; нужна ручная команда отрядам')
            self.log('Кампания: завершены три боя')
            if mode == 'sea':
                self.require('наземная', 'кампания')
            else:
                self.require('скорость пополнения')
            self.tap(100, 50)
            self.main()
        finally:
            self.pause_campaign()

    def slider_level(self, maximum):
        source = cv2.imdecode(np.fromfile(ROOT / 'search_mine.png', np.uint8), cv2.IMREAD_COLOR)
        handle = source[690:735, 544:566]
        result = cv2.matchTemplate(self.frame[685:741, 540:1010], handle, cv2.TM_CCOEFF_NORMED)
        _, score, _, point = cv2.minMaxLoc(result)
        if score < .95:
            raise Paused('Ползунок уровня поиска не распознан')
        position = point[0] + 540 + 11
        value = 1 + (position - 555) / (993 - 555) * (maximum - 1)
        if abs(value - round(value)) > .2 or not 1 <= round(value) <= maximum:
            raise Paused('Положение ползунка неоднозначно')
        return round(value)

    def dispatch_free_collector(self, number=None):
        self.require('отряд сбора')
        if number is not None and number not in range(1, 6):
            raise Paused('Разрешены только обычные отряды №1–5')
        if number is not None:
            self.command('-s', self.serial, 'shell', 'input', 'swipe', '560', '440', '1350', '440', '450')
            self.wait(.6)
            self.observe()
            if number >= 4:
                self.command('-s', self.serial, 'shell', 'input', 'swipe', '1350', '440', '560', '440', '450')
                self.wait(.6)
                self.observe()
            center = (620 + (number - 1) * 280) if number <= 3 else (745 + (number - 4) * 280)
            self.require('отряд сбора')
            caption = self.detail((center - 135, 526, center + 135, 573))
            if not re.search(r'сбора\s*(?:№|n[qоo°]?)?\s*' + str(number) + r'\b', caption):
                raise Paused(f'Не удалось подтвердить номер отряда {number}')
            try:
                x, y = self.template('collector_free.png', (787, 475, 814, 501),
                                     (center - 160, 465, center - 60, 515))
            except Paused:
                self.log(f'Отряд №{number} занят или возвращается; пропускаю')
                self.tap(1410, 205)
                return False
            self.tap(center, 430)
        else:
            return self.dispatch_any_free()
        return self.send_selected_collector(number)

    def dispatch_any_free(self):
        try:
            x, y = self.template('collector_free.png', (787, 475, 814, 501))
        except Paused:
            # Show the leftmost ordinary collectors; the sixth paid slot is excluded.
            self.command('-s', self.serial, 'shell', 'input', 'swipe', '560', '440', '1350', '440', '450')
            self.wait(.6)
            self.observe()
            self.require('отряд сбора')
            try:
                x, y = self.template('collector_free.png', (787, 475, 814, 501))
            except Paused:
                self.log('Свободного сборщика в видимой группе нет')
                self.tap(1410, 205)
                return False
        if not (490 <= x <= 1415 and 470 <= y <= 505):
            raise Paused('Маркер свободного сборщика вне списка')
        self.tap(min(x + 90, 1400), 430)
        return self.send_selected_collector()

    def send_selected_collector(self, number=None):
        self.require('отряд сбора')
        self.template('collector_free.png', (787, 475, 814, 501))
        lower = self.detail((755, 654, 1165, 810))
        if 'отправить' not in lower or 'км' not in lower:
            raise Paused('Отправка свободного сборщика не распознана')
        # A free collector has one central gold button, no current resource panel.
        b, g, r = self.frame[707:725, 775:805].mean(axis=(0, 1))
        if not (r > b + 35 and g > b + 20):
            raise Paused('Не подтверждена кнопка отправки свободного сборщика')
        self.tap(960, 748)
        self.main()
        if self.has('отряд сбора', (460, 160, 1465, 600)):
            raise Paused('Окно отправки осталось открытым')
        if number is not None:
            self.tap(75, 337)
            self.tap(155, 250)
            self.require('сбор ресурсов')
            top = 286 + (number - 1) * 135
            caption = self.detail((730, top + 8, 903, top + 78))
            state = self.detail((330, top + 8, 715, top + 78))
            self.tap(75, 337)
            self.main()
            if 'отозвать' not in caption or 'до базы' in state:
                self.log(f'Отряд №{number}: отправка не подтверждена; проверю в следующем проходе')
                return False
            self.log(f'Отряд №{number}: команда принята, подтверждён выход или добыча')
        else:
            self.log('Команда отправки передана; окно выбора закрыто')
        return True

    def open_resource_search(self, resource, target=None):
        self.main()
        self.tap(75, 218)
        self.require('поиск', 'ферма', 'шахта')
        self.tap({'Ферма': 960, 'Шахта': 1160, 'Нефтяная вышка': 1360}[resource], 363)
        self.require('шахта', 'ферма', 'поиск')
        match = re.search(r'до ур\.?\s*(\d+)', self.detail((470, 740, 1075, 785)))
        if not match or not 1 <= int(match[1]) <= 20:
            raise Paused('Максимальный уровень ресурса не прочитан')
        maximum = int(match[1])
        target = maximum if target is None else target
        if not 1 <= target <= maximum:
            raise Paused('Запрошен недопустимый уровень поиска')
        for _ in range(maximum + 1):
            self.require('шахта', 'ферма', 'поиск')
            current = self.slider_level(maximum)
            if not current:
                raise Paused('Текущий уровень поиска не прочитан')
            if current == target:
                return maximum
            self.tap(1047 if current < target else 504, 713)
        raise Paused('Не удалось установить уровень поиска')

    def first_free_collector(self):
        self.main()
        self.tap(75, 337)
        self.tap(155, 250)
        self.require('сбор ресурсов')
        available = None
        for number in range(1, 6):
            top = 286 + (number - 1) * 135
            caption = self.detail((730, top + 8, 903, top + 78))
            state = self.detail((330, top + 8, 715, top + 78))
            if 'отправить' not in caption and 'отозвать' not in caption:
                raise Paused(f'Статус отряда №{number} не распознан')
            if 'отправить' in caption and 'до базы' not in state:
                available = number
                break
        self.observe()
        self.require('сбор ресурсов')
        self.tap(75, 337)
        self.main()
        return available

    def search_resources(self, resource='Шахта', collector=None):
        if collector is None:
            collector = self.first_free_collector()
            if collector is None:
                self.log('Свободных обычных сборщиков нет; поиск отложен')
                return
        maximum = self.open_resource_search(resource)
        for level in range(maximum, 0, -1):
            if self.slider_level(maximum) != level:
                raise Paused('Уровень поиска изменился неожиданно')
            self.log(f'Поиск: {resource}, уровень {level}')
            self.require('шахта', 'ферма', 'поиск')
            self.tap(1315, 711)
            self.wait(1.5)
            self.observe()
            if self.has('шахта производит') or self.has('можете собирать ресурсы'):
                if not self.has('не найдено') and 'не найдено' not in norm(self.detail((775, 0, 1160, 165))):
                    raise Paused('Результат поиска не определён; повторный поиск отменён')
                if level > 1:
                    self.tap(504, 713)
                continue
            # The camera continues moving after the search panel disappears.
            self.main()
            panel = self.detail((210, 330, 663, 575))
            if 'резервы' not in panel:
                self.tap(960, 520)
                panel = self.detail((210, 330, 663, 575))
            found = re.search(r'ур\.?\s*([0-9вбзoо]+)\b', panel)
            if not found or search_level('ур. ' + found[1]) != level:
                raise Paused('Уровень найденного месторождения не подтверждён')
            # OCR reads columns out of order; isolate the actual occupant row by its label.
            labels = [word for line in self.lines for word in line['words']
                      if norm(word['text']) in ('шахтер', 'фермер', 'нефтяник')
                      and 210 <= word['x'] <= 400 and 330 <= word['y'] <= 640]
            if len(labels) != 1:
                raise Paused('Не найдена строка занятости месторождения')
            label = labels[0]
            occupant = self.detail((225, int(label['y']) - 7, 655,
                                    int(label['y'] + label['height']) + 7))
            if not resource_is_free(occupant):
                self.log(f'Месторождение уровня {level}: занято или статус не прочитан; пропускаю')
                self.tap(1300, 600)
                self.main()
                if level == 1:
                    self.log('Свободных подтверждённых месторождений не найдено')
                    return
                if self.open_resource_search(resource, target=level - 1) != maximum:
                    raise Paused('Максимальный уровень поиска изменился во время прохода')
                continue
            self.tap(*self.template('mine.png', (937, 699, 983, 748)))
            self.require('отряд сбора')
            self.log(f'Найдено месторождение уровня {level}')
            if self.dispatch_free_collector(collector):
                from telemetry import record, safe
                safe(self, record, 'dispatches', resource, 1, level=level, collector=collector)
            return
        self.log('Подходящих ресурсов поблизости не найдено')
        self.tap(1410, 205)

    def run_plan(self, plan):
        from plans import validate_plan
        from emergency import local_recover
        failures=[]
        for number, resource in enumerate(validate_plan(plan), 1):
            for attempt in range(2):
                try:
                    self.run_collector(number,resource)
                    break
                except Paused as error:
                    if self.stop.is_set() or 'нападении на базу' in str(error):
                        raise
                    self.log(f'Отряд №{number}: {error}; восстановление, попытка {attempt+1}/2')
                    self.observe()
                    if self.has('сбор ресурсов'):
                        self.tap(75,337)
                    if self.has('поиск') and self.has('шахта') and self.has('ферма'):
                        self.tap(1410,205)
                    if not local_recover(self):
                        raise
                    if attempt == 1:
                        failures.append(number)
                        self.log(f'Отряд №{number}: отправка отложена; проверяю остальных')
        if failures:
            self.log(f'Сборщики: не удалось отправить отряды {failures}; повторю в следующем проходе')

    def run_collector(self, number, resource):
        if resource == 'Не отправлять':
            self.log(f'Отряд №{number}: пропущен по схеме')
            return
        self.log(f'Отряд №{number}: {resource}')
        self.observe()
        self.main()
        self.tap(75, 337)
        self.tap(155, 250)
        self.require('сбор ресурсов')
        top = 286 + (number - 1) * 135
        caption = self.detail((730, top + 8, 903, top + 78))
        state = self.detail((330, top + 8, 715, top + 78))
        busy = 'отозвать' in caption
        returning = 'до базы' in state
        if busy:
            from telemetry import gathering, safe
            safe(self, gathering, number,state)
        if not busy and 'отправить' not in caption:
            raise Paused(f'Статус отряда №{number} не распознан')
        self.tap(75, 337)
        self.main()
        if returning:
            self.log(f'Отряд №{number} возвращается на базу; дождусь прибытия')
            return
        if busy:
            self.log(f'Отряд №{number} уже занят; дождусь освобождения')
            return
        self.search_resources('Нефтяная вышка' if resource == 'Нефть' else resource, number)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--task', choices=['help', 'research', 'supplies', 'search', 'radar', 'missions', 'inspect'], default='inspect')
    parser.add_argument('--resource', choices=['Ферма', 'Шахта', 'Нефтяная вышка'], default='Шахта')
    args = parser.parse_args()
    bot = Bot(allow_captcha=args.task != 'inspect')
    try:
        bot.connect()
        bot.observe()
        if args.task == 'inspect':
            print(bot.text())
        elif args.task == 'search':
            bot.search_resources(args.resource)
        else:
            getattr(bot, {'help': 'help_all', 'research': 'research', 'supplies': 'supplies',
                          'radar': 'radar_rewards', 'missions': 'mission_rewards'}[args.task])()
    except (Paused, subprocess.TimeoutExpired, OSError, ValueError) as error:
        print('ПАУЗА:', error)
        return 1
    finally:
        bot.close()
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
