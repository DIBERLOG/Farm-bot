@echo off
setlocal

echo [1/4] Capture training frames. Keep Telegram/PlayDeck visible.
python capture_training_frames.py --count 500 --interval 0.10 --window-title PlayDeck,Telegram
if errorlevel 1 exit /b 1

echo [2/4] Build YOLO dataset labels.
python bootstrap_yolo_dataset.py --raw datasets/farmbar/raw --dataset datasets/farmbar
if errorlevel 1 exit /b 1

echo [3/4] Train local YOLO model.
python train_yolo.py
if errorlevel 1 exit /b 1

echo [4/4] Rebuild EXE with the new model.
call build_yolo_exe.bat
if errorlevel 1 exit /b 1

copy /Y dist\FarmBarOverlayBot-yolo.exe dist\FarmBarOverlayBot-yolo-trained.exe
echo Done: dist\FarmBarOverlayBot-yolo-trained.exe
