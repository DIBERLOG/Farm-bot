import argparse
import time
from dataclasses import dataclass

import cv2
import numpy as np
import pyautogui


@dataclass(frozen=True)
class Detection:
    x: int
    y: int
    area: float
    direction: str = "new"


def parse_args():
    parser = argparse.ArgumentParser(
        description="Find yellow game objects on the screen and estimate horizontal movement."
    )
    parser.add_argument(
        "--region",
        nargs=4,
        type=int,
        metavar=("X", "Y", "WIDTH", "HEIGHT"),
        help="Screen region to capture. Example: --region 40 80 830 1270",
    )
    parser.add_argument("--min-area", type=int, default=150)
    parser.add_argument("--h-min", type=int, default=20)
    parser.add_argument("--h-max", type=int, default=40)
    parser.add_argument("--s-min", type=int, default=120)
    parser.add_argument("--v-min", type=int, default=120)
    parser.add_argument("--move-threshold", type=int, default=4)
    parser.add_argument("--delay", type=float, default=0.03)
    parser.add_argument("--show-mask", action="store_true")
    return parser.parse_args()


def capture_frame(region):
    screenshot = pyautogui.screenshot(region=region)
    frame = np.array(screenshot)
    return cv2.cvtColor(frame, cv2.COLOR_RGB2BGR)


def find_yellow_objects(frame, args):
    hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
    lower_yellow = np.array([args.h_min, args.s_min, args.v_min])
    upper_yellow = np.array([args.h_max, 255, 255])
    mask = cv2.inRange(hsv, lower_yellow, upper_yellow)

    kernel = np.ones((5, 5), np.uint8)
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel)
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel)

    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    detections = []

    for contour in contours:
        area = cv2.contourArea(contour)
        if area < args.min_area:
            continue

        x, y, w, h = cv2.boundingRect(contour)
        detections.append(Detection(x=x + w // 2, y=y + h // 2, area=area))

    detections.sort(key=lambda item: (item.y, item.x))
    return detections, mask


def add_directions(current, previous, threshold):
    results = []

    for detection in current:
        nearest = None
        min_distance = float("inf")

        for old in previous:
            distance = abs(detection.x - old.x) + abs(detection.y - old.y)
            if distance < min_distance:
                min_distance = distance
                nearest = old

        if nearest is None:
            results.append(
                Detection(detection.x, detection.y, detection.area, "new object")
            )
            continue

        dx = detection.x - nearest.x
        if dx > threshold:
            direction = "right"
        elif dx < -threshold:
            direction = "left"
        else:
            direction = "still"

        results.append(Detection(detection.x, detection.y, detection.area, direction))

    return results


def draw_detections(frame, detections, offset):
    offset_x, offset_y = offset

    for detection in detections:
        cv2.circle(frame, (detection.x, detection.y), 12, (0, 255, 255), 2)
        cv2.putText(
            frame,
            detection.direction,
            (detection.x - 45, detection.y - 18),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.65,
            (0, 255, 255),
            2,
        )

        screen_x = detection.x + offset_x
        screen_y = detection.y + offset_y
        print(
            f"Triangle: x={screen_x}, y={screen_y}, area={detection.area:.0f}, "
            f"movement={detection.direction}"
        )


def main():
    args = parse_args()
    region = tuple(args.region) if args.region else None
    offset = (args.region[0], args.region[1]) if args.region else (0, 0)
    previous = []

    print("Press Q in the detector window to exit.")

    while True:
        frame = capture_frame(region)
        current, mask = find_yellow_objects(frame, args)
        detections = add_directions(current, previous, args.move_threshold)

        draw_detections(frame, detections, offset)
        previous = current

        cv2.imshow("Yellow triangles detector", frame)
        if args.show_mask:
            cv2.imshow("Yellow mask", mask)

        if cv2.waitKey(1) & 0xFF == ord("q"):
            break

        time.sleep(args.delay)

    cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
