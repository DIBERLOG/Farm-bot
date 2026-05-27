@echo off
python -m PyInstaller ^
  --onefile ^
  --windowed ^
  --name FarmBarOverlayBot-yolo ^
  --icon assets\FarmBarOverlayBot.ico ^
  --add-data "models\farmbar-yolo.pt;models" ^
  --collect-all ultralytics ^
  --collect-all torch ^
  --collect-all torchvision ^
  --clean ^
  overlay_bot_yolo.py

if not exist dist\models mkdir dist\models
copy /Y models\farmbar-yolo.pt dist\models\farmbar-yolo.pt
