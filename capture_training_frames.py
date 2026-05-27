import argparse
import time
from pathlib import Path
from types import SimpleNamespace

import cv2

from overlay_bot import capture_frame, make_region


def parse_args():
    parser = argparse.ArgumentParser(description="Capture raw training frames.")
    parser.add_argument("--interval", type=float, default=0.25)
    parser.add_argument("--count", type=int, default=300)
    parser.add_argument("--output", default="datasets/farmbar/raw")
    parser.add_argument("--window-title", default="PlayDeck,Telegram")
    parser.add_argument("--region", nargs=4, type=int)
    return parser.parse_args()


def main():
    args = parse_args()
    output = Path(args.output)
    output.mkdir(parents=True, exist_ok=True)

    bot_args = SimpleNamespace(
        window_title=args.window_title,
        region=args.region,
        no_auto_game_region=False,
    )
    region = make_region(bot_args)
    if region is None:
        raise SystemExit("Game window not found. Open Telegram/PlayDeck first.")

    existing_indexes = []
    for path in output.glob("frame_*.jpg"):
        try:
            existing_indexes.append(int(path.stem.split("_")[-1]))
        except ValueError:
            continue
    start_index = max(existing_indexes, default=-1) + 1

    for index in range(args.count):
        frame = capture_frame(region)
        path = output / f"frame_{start_index + index:05d}.jpg"
        cv2.imwrite(str(path), frame)
        print(path)
        time.sleep(args.interval)


if __name__ == "__main__":
    main()
