# Yellow Triangle Detector

Скрипт делает скриншоты экрана, ищет жёлтые объекты, отмечает их центры и определяет движение по X: `left`, `right`, `still` или `new object`.

## Установка

```bash
pip install -r requirements.txt
```

## Запуск

Полный экран:

```bash
python detector.py
```

Только область игры:

```bash
python detector.py --region 40 80 830 1270
```

Формат `--region`:

```text
X Y WIDTH HEIGHT
```

## Настройка

Если скрипт видит лишние жёлтые элементы:

```bash
python detector.py --region 40 80 830 1270 --min-area 250
```

Если жёлтый оттенок не попадает в маску:

```bash
python detector.py --h-min 18 --h-max 45 --s-min 100 --v-min 100 --show-mask
```

Окно `Yellow mask` покажет, какие пиксели сейчас считаются жёлтыми.

## Выход

Нажми `Q` в окне детектора.

## Оверлей-бот

`overlay_bot.py` работает поверх игры: рисует найденный розовый шар и жёлтые треугольники, определяет их движение и может кликать, когда прогнозирует пересечение.

По умолчанию приложение ищет окно `PlayDeck`, внутри него находит игровую область по голубым платформам и ставит оверлей прямо поверх поля.

Если `PlayDeck` не найден, приложение также пробует окно `Telegram`. Если окно игры не найдено вообще, полноэкранный оверлей не создаётся: останется только маленькое окно управления со статусом ожидания.

Запуск без автокликов, только наблюдение:

```bash
python overlay_bot.py
```

Запуск с автокликами:

```bash
python overlay_bot.py --auto-click
```

Визуальный оверлей с кругами вокруг объектов теперь выключен по умолчанию, чтобы избежать чёрного экрана на системах, где Tk-прозрачность работает нестабильно. Включить его можно отдельно:

```bash
python overlay_bot.py --auto-click --show-overlay
```

Если окно называется иначе:

```bash
python overlay_bot.py --window-title "Название окна" --auto-click
```

Если автоопределение области ошиблось, можно вручную указать `--region`:

```text
X Y WIDTH HEIGHT
```

Полезные настройки:

```bash
python overlay_bot.py --auto-click --danger-radius 85 --prediction-frames 22
```

`danger-radius` отвечает за допустимую близость треугольника к шару по вертикали. `prediction-frames` отвечает за то, насколько далеко вперёд бот прогнозирует движение.

В окне `Bot control` можно включить/выключить `Auto click`, сделать тестовый клик и закрыть приложение.

Окно `Bot control` ставится сбоку от игрового поля, чтобы не попадать в скриншот анализа и не мешать распознаванию объектов.

## Сборка EXE

```bash
build_exe.bat
```

Готовый файл появится здесь:

```text
dist\FarmBarOverlayBot.exe
```

Иконка приложения лежит здесь:

```text
assets\FarmBarOverlayBot.ico
```

## Latency tuning

Stable EXE before the latency changes:

```text
releases\FarmBarOverlayBot-stable-before-latency.exe
```

Stable goal-lock version:

```text
dist\FarmBarOverlayBot-stable-goal.exe
```

This version keeps the stable timing and blocks auto-clicks that would reverse the ball away from the largest pink goal circle.

Stable goal-lock v1 backup:

```text
releases\FarmBarOverlayBot-stable-goal-v1.exe
```

If the bot reacts too late:

```bash
dist\FarmBarOverlayBot.exe --auto-click --danger-radius 95 --collision-x-radius 85 --prediction-frames 32 --reaction-lead-frames 7
```

If it still reacts too late, use the early preset:

```bash
dist\FarmBarOverlayBot.exe --auto-click --fps 45 --danger-radius 110 --collision-x-radius 120 --prediction-frames 44 --reaction-lead-frames 14 --click-cooldown 0.10
```

If the bot reacts too early:

```bash
dist\FarmBarOverlayBot.exe --auto-click --danger-radius 70 --collision-x-radius 55 --prediction-frames 18 --reaction-lead-frames 2
```

Reaction parameters:

```text
danger-radius        vertical safety radius around the ball
collision-x-radius   horizontal collision radius around the ball
prediction-frames    how far ahead to predict movement
reaction-lead-frames extra frame lead to compensate click/screenshot delay
pair-window-frames   group triangles that arrive within this many frames
group-window-frames  group 2, 3, or more triangles that arrive together
rebound-memory-frames remember the last bounce point to avoid returning to it
triangle-default-speed predicted triangle speed before measured movement exists
forbidden-x-radius  horizontal danger radius for small pink circles
forbidden-y-radius  vertical lookahead for small pink circles
reverse-safety-margin-frames do not click if the reversed path hits a triangle too soon
```

Smart version behavior:

```text
Before clicking, the bot compares the current path with the reversed path.
It clicks only when reversing is safer than continuing.
```

Current early goal-lock backup:

```text
releases\FarmBarOverlayBot-stable-goal-early-v1.exe
```

## Local YOLO mode

Recommended local neural detector: Ultralytics YOLO11n.

It must be trained on your game frames first. Classes:

```text
0 ball
1 goal
2 small
3 triangle
```

Install optional neural dependencies:

```bash
pip install -r requirements-yolo.txt
```

Capture raw frames:

```bash
python capture_training_frames.py --count 300 --interval 0.25
```

Label images in YOLO format and place them here:

```text
datasets/farmbar/images/train
datasets/farmbar/images/val
datasets/farmbar/labels/train
datasets/farmbar/labels/val
```

Train:

```bash
python train_yolo.py
```

Copy the best model:

```text
runs/farmbar/yolo11n/weights/best.pt -> models/farmbar-yolo.pt
```

Run with YOLO:

```bash
python overlay_bot.py --auto-click --detector yolo --yolo-model models/farmbar-yolo.pt
```

If the YOLO model is missing or cannot load, use the CV detector:

```bash
python overlay_bot.py --auto-click --detector cv
```
