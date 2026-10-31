@echo off
cd /d "%~dp0"
cargo build --release --manifest-path native-ui/Cargo.toml
if errorlevel 1 exit /b 1
copy /Y "native-ui\target\release\warpath-helper.exe" "warpath-helper.exe"
