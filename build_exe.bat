@echo off
python -m PyInstaller ^
  --onefile ^
  --windowed ^
  --name FarmBarOverlayBot ^
  --icon assets\FarmBarOverlayBot.ico ^
  --clean ^
  overlay_bot.py
