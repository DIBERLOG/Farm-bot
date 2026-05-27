import argparse
import shutil
from pathlib import Path

import cv2
import numpy as np


CLASS_IDS = {
    "ball": 0,
    "goal": 1,
    "small": 2,
    "triangle": 3,
}


def parse_args():
    parser = argparse.ArgumentParser(description="Bootstrap YOLO labels from color masks.")
    parser.add_argument("--raw", default="datasets/farmbar/raw")
    parser.add_argument("--dataset", default="datasets/farmbar")
    parser.add_argument("--val-ratio", type=float, default=0.2)
    parser.add_argument("--yellow-min-area", type=int, default=120)
    parser.add_argument("--pink-min-area", type=int, default=40)
    return parser.parse_args()


def find_boxes(frame, lower, upper, min_area, circularity_min=None):
    hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
    mask = cv2.inRange(hsv, lower, upper)
    kernel = np.ones((5, 5), np.uint8)
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel)
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel)
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

    boxes = []
    for contour in contours:
        area = cv2.contourArea(contour)
        if area < min_area:
            continue

        if circularity_min is not None:
            perimeter = cv2.arcLength(contour, True)
            if perimeter == 0:
                continue
            circularity = 4 * np.pi * area / (perimeter * perimeter)
            if circularity < circularity_min:
                continue

        x, y, w, h = cv2.boundingRect(contour)
        boxes.append({"box": (x, y, w, h), "area": area, "cx": x + w / 2, "cy": y + h / 2})

    return boxes


def nearest_motion(current, previous):
    for obj in current:
        nearest = None
        nearest_distance = float("inf")
        for old in previous:
            distance = abs(obj["cx"] - old["cx"]) + abs(obj["cy"] - old["cy"])
            if distance < nearest_distance:
                nearest_distance = distance
                nearest = old
        obj["motion"] = nearest_distance if nearest is not None and nearest_distance < 120 else 0
    return current


def yolo_line(class_name, box, frame_w, frame_h, pad=5):
    x, y, w, h = box
    x = max(0, x - pad)
    y = max(0, y - pad)
    w = min(frame_w - x, w + pad * 2)
    h = min(frame_h - y, h + pad * 2)
    cx = (x + w / 2) / frame_w
    cy = (y + h / 2) / frame_h
    nw = w / frame_w
    nh = h / frame_h
    return f"{CLASS_IDS[class_name]} {cx:.6f} {cy:.6f} {nw:.6f} {nh:.6f}"


def clean_dataset_dirs(dataset):
    for split in ("train", "val"):
        for kind in ("images", "labels"):
            path = dataset / kind / split
            path.mkdir(parents=True, exist_ok=True)
            for file in path.glob("*"):
                file.unlink()


def main():
    args = parse_args()
    raw_dir = Path(args.raw)
    dataset = Path(args.dataset)
    frames = sorted(
        [
            path
            for path in raw_dir.glob("*")
            if path.suffix.lower() in {".jpg", ".jpeg", ".png"}
        ]
    )
    if not frames:
        raise SystemExit(f"No frames found in {raw_dir}")

    clean_dataset_dirs(dataset)
    previous_pink = []
    labeled_count = 0

    for index, frame_path in enumerate(frames):
        frame = cv2.imread(str(frame_path))
        if frame is None:
            continue

        frame_h, frame_w = frame.shape[:2]
        yellow = find_boxes(
            frame,
            np.array([20, 110, 110]),
            np.array([42, 255, 255]),
            args.yellow_min_area,
        )
        pink = find_boxes(
            frame,
            np.array([145, 70, 120]),
            np.array([179, 255, 255]),
            args.pink_min_area,
            circularity_min=0.35,
        )
        pink = nearest_motion(pink, previous_pink)
        previous_pink = pink

        labels = []
        for obj in yellow:
            labels.append(yolo_line("triangle", obj["box"], frame_w, frame_h))

        ball = None
        if pink:
            moving = [obj for obj in pink if obj.get("motion", 0) > 2]
            if moving:
                ball = max(moving, key=lambda obj: obj["motion"])
            else:
                ball = min(pink, key=lambda obj: obj["area"])

        static_pink = [obj for obj in pink if obj is not ball]
        goal = max(static_pink, key=lambda obj: obj["area"]) if static_pink else None

        if ball is not None:
            labels.append(yolo_line("ball", ball["box"], frame_w, frame_h))
        if goal is not None:
            labels.append(yolo_line("goal", goal["box"], frame_w, frame_h))

        min_small_area = 120
        if ball is not None:
            min_small_area = max(min_small_area, ball["area"] * 0.25)
        max_small_area = goal["area"] * 0.85 if goal is not None else float("inf")

        for obj in static_pink:
            if obj is goal:
                continue
            if obj["area"] < min_small_area or obj["area"] > max_small_area:
                continue
            labels.append(yolo_line("small", obj["box"], frame_w, frame_h))

        split = "val" if index % max(2, int(1 / args.val_ratio)) == 0 else "train"
        out_image = dataset / "images" / split / frame_path.name
        out_label = dataset / "labels" / split / f"{frame_path.stem}.txt"
        shutil.copy2(frame_path, out_image)
        out_label.write_text("\n".join(labels), encoding="utf-8")
        labeled_count += 1

    print(f"Bootstrapped {labeled_count} frames into {dataset}")


if __name__ == "__main__":
    main()
