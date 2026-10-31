"""Read-only LDPlayer connection and screenshot check. Python standard library only."""
import argparse
from pathlib import Path
import struct
import subprocess
import sys


def connected_devices(output):
    return [parts[0] for line in output.splitlines()
            if len(parts := line.split()) >= 2 and parts[1] == 'device']


def png_size(data):
    if len(data) < 24 or data[:8] != b'\x89PNG\r\n\x1a\n' or data[12:16] != b'IHDR':
        raise ValueError('ADB did not return a PNG screenshot')
    width, height = struct.unpack('>II', data[16:24])
    if not (0 < width <= 16384 and 0 < height <= 16384):
        raise ValueError('Invalid screenshot dimensions')
    return width, height


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--adb', default='C:/LDPlayer/LDPlayer9/adb.exe')
    parser.add_argument('--serial', default='127.0.0.1:5555')
    parser.add_argument('--self-test', action='store_true')
    args = parser.parse_args()
    if args.self_test:
        assert connected_devices('List of devices attached\na\tdevice\nb\toffline\nc\tunauthorized\n') == ['a']
        assert png_size(b'\x89PNG\r\n\x1a\n' + b'\0\0\0\rIHDR' + struct.pack('>II', 1920, 1080)) == (1920, 1080)
        try:
            png_size(b'error: device offline')
        except ValueError:
            pass
        else:
            raise AssertionError('Invalid screenshot accepted')
        print('Self-test passed')
        return
    if not Path(args.adb).is_file():
        raise ValueError('ADB executable missing; use --adb PATH')

    def adb(*command):
        result = subprocess.run([args.adb, *command], capture_output=True, timeout=20,
                                creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        if result.returncode:
            raise ValueError(result.stderr.decode(errors='replace').strip())
        return result.stdout

    adb('connect', args.serial)
    if args.serial not in connected_devices(adb('devices').decode(errors='replace')):
        raise ValueError('LDPlayer unavailable. Enable local ADB in LDPlayer settings, then restart if requested.')
    data = adb('-s', args.serial, 'exec-out', 'screencap', '-p')
    width, height = png_size(data)
    destination = Path(__file__).resolve().parent / 'screen.png'
    destination.write_bytes(data)
    print(f'Connected: {args.serial}; screenshot {width}x{height}: {destination}')


if __name__ == '__main__':
    try:
        main()
    except (ValueError, OSError, subprocess.TimeoutExpired) as error:
        print(f'Connection check failed: {error}', file=sys.stderr)
        sys.exit(1)
