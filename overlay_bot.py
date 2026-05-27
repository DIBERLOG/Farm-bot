import argparse
import ctypes
import sys
import threading
import time
import tkinter as tk
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import cv2
import numpy as np
import pyautogui
import pygetwindow as gw


WS_EX_LAYERED = 0x00080000
WS_EX_TRANSPARENT = 0x00000020
GWL_EXSTYLE = -20
TRANSPARENT_COLOR = "#010203"
PANEL_WIDTH = 560
PANEL_HEIGHT = 146
PANEL_MARGIN = 16


@dataclass
class TrackedObject:
    x: int
    y: int
    area: float
    vx: float = 0.0
    vy: float = 0.0


@dataclass
class BotState:
    ball: TrackedObject | None
    goal: TrackedObject | None
    rebound: TrackedObject | None
    forbidden: list[TrackedObject]
    triangles: list[TrackedObject]
    danger: TrackedObject | None
    action: str
    auto_click: bool
    running: bool
    region: tuple[int, int, int, int] | None


@dataclass
class Threat:
    triangle: TrackedObject
    frames: float
    y_distance: float
    vertical_relation: float


class YoloDetector:
    def __init__(self, model_path: str, conf: float, imgsz: int):
        self.requested_model_path = Path(model_path)
        self.model_path = resolve_resource_path(model_path)
        self.conf = conf
        self.imgsz = imgsz
        self.model = None
        self.error = None

    def load(self):
        if self.model is not None or self.error is not None:
            return self.model is not None

        if not self.model_path.exists():
            self.error = (
                f"YOLO model not found: {self.requested_model_path} "
                f"(resolved: {self.model_path})"
            )
            write_log(self.error)
            return False

        try:
            from ultralytics import YOLO

            self.model = YOLO(str(self.model_path))
            write_log(f"YOLO loaded: {self.model_path}")
            return True
        except Exception as exc:
            self.error = f"YOLO load failed: {exc}"
            write_log(self.error)
            return False

    def detect(self, frame):
        if not self.load():
            return None

        try:
            result = self.model.predict(
                frame,
                imgsz=self.imgsz,
                conf=self.conf,
                verbose=False,
            )[0]
        except Exception as exc:
            self.error = f"YOLO predict failed: {exc}"
            write_log(self.error)
            return None
        names = result.names
        objects = {
            "ball": [],
            "goal": [],
            "small": [],
            "triangle": [],
        }

        if result.boxes is None:
            return objects

        for box in result.boxes:
            class_id = int(box.cls[0])
            label = normalize_yolo_label(str(names.get(class_id, class_id)))
            if label is None:
                continue

            x1, y1, x2, y2 = [float(value) for value in box.xyxy[0]]
            width = max(1.0, x2 - x1)
            height = max(1.0, y2 - y1)
            objects[label].append(
                TrackedObject(
                    x=int((x1 + x2) / 2),
                    y=int((y1 + y2) / 2),
                    area=width * height,
                )
            )

        return objects


def app_base_dir():
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


def resolve_resource_path(path: str):
    raw = Path(path)
    if raw.is_absolute() and raw.exists():
        return raw

    candidates = [
        Path.cwd() / raw,
        app_base_dir() / raw,
    ]
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        candidates.append(Path(meipass) / raw)

    for candidate in candidates:
        if candidate.exists():
            return candidate

    return candidates[1]


def write_log(message: str):
    try:
        log_path = app_base_dir() / "farmbar_bot.log"
        timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
        with log_path.open("a", encoding="utf-8") as log_file:
            log_file.write(f"[{timestamp}] {message}\n")
    except Exception:
        pass


def normalize_yolo_label(label: str):
    normalized = label.lower().strip().replace("-", "_").replace(" ", "_")
    aliases = {
        "ball": "ball",
        "pink_ball": "ball",
        "player": "ball",
        "goal": "goal",
        "big": "goal",
        "big_pink": "goal",
        "goal_pink": "goal",
        "target": "goal",
        "small": "small",
        "small_pink": "small",
        "rebound": "small",
        "triangle": "triangle",
        "yellow_triangle": "triangle",
        "obstacle": "triangle",
    }
    return aliases.get(normalized)


def parse_args():
    parser = argparse.ArgumentParser(
        description="Transparent overlay bot for detecting the pink ball and yellow triangles."
    )
    parser.add_argument(
        "--region",
        nargs=4,
        type=int,
        metavar=("X", "Y", "WIDTH", "HEIGHT"),
        help="Game screen region. Example: --region 80 36 788 1380",
    )
    parser.add_argument(
        "--window-title",
        default="PlayDeck,Telegram",
        help="Comma-separated window titles to follow when --region is not set.",
    )
    parser.add_argument(
        "--show-overlay",
        action="store_true",
        help="Draw the transparent visual overlay. Disabled by default to avoid black-screen issues.",
    )
    parser.add_argument(
        "--no-auto-game-region",
        action="store_true",
        help="Use the whole matched window instead of auto-detecting the game field.",
    )
    parser.add_argument("--fps", type=int, default=30)
    parser.add_argument("--auto-click", action="store_true")
    parser.add_argument("--click-x", type=int, help="Click X. Defaults to region center.")
    parser.add_argument("--click-y", type=int, help="Click Y. Defaults to region center.")
    parser.add_argument("--yellow-min-area", type=int, default=120)
    parser.add_argument("--pink-min-area", type=int, default=40)
    parser.add_argument("--danger-radius", type=int, default=90)
    parser.add_argument("--collision-x-radius", type=int, default=62)
    parser.add_argument("--prediction-frames", type=int, default=28)
    parser.add_argument("--reaction-lead-frames", type=int, default=3)
    parser.add_argument("--click-cooldown", type=float, default=0.20)
    parser.add_argument("--pair-window-frames", type=int, default=5)
    parser.add_argument("--group-window-frames", type=int, default=6)
    parser.add_argument("--rebound-memory-frames", type=int, default=45)
    parser.add_argument("--triangle-default-speed", type=float, default=0.0)
    parser.add_argument("--forbidden-x-radius", type=int, default=80)
    parser.add_argument("--forbidden-y-radius", type=int, default=180)
    parser.add_argument("--reverse-safety-margin-frames", type=int, default=4)
    parser.add_argument(
        "--goal-area-ratio",
        type=float,
        default=0.80,
        help="Largest pink static circle must be this much bigger than other targets to be treated as the main goal.",
    )
    parser.add_argument("--debug", action="store_true")
    parser.add_argument(
        "--detector",
        choices=("cv", "yolo"),
        default="cv",
        help="Object detector backend. YOLO requires a trained local model.",
    )
    parser.add_argument("--yolo-model", default="models/farmbar-yolo.pt")
    parser.add_argument("--yolo-conf", type=float, default=0.20)
    parser.add_argument("--yolo-imgsz", type=int, default=960)
    return parser.parse_args()


def screen_size():
    width, height = pyautogui.size()
    return int(width), int(height)


def locate_window(titles):
    if not titles:
        return None

    title_parts = [item.strip() for item in titles.split(",") if item.strip()]
    candidates = []
    for title in title_parts:
        for window in gw.getWindowsWithTitle(title):
            if window.isMinimized or window.width <= 100 or window.height <= 100:
                continue
            candidates.append(window)

    if not candidates:
        return None

    window = max(candidates, key=lambda item: item.width * item.height)
    return int(window.left), int(window.top), int(window.width), int(window.height)


def detect_game_region(window_region):
    frame = capture_frame(window_region)
    hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
    cyan_mask = cv2.inRange(hsv, np.array([80, 80, 120]), np.array([100, 255, 255]))

    kernel = np.ones((5, 5), np.uint8)
    cyan_mask = cv2.morphologyEx(cyan_mask, cv2.MORPH_CLOSE, kernel)
    contours, _ = cv2.findContours(cyan_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

    bars = []
    frame_h, frame_w = frame.shape[:2]
    for contour in contours:
        area = cv2.contourArea(contour)
        x, y, w, h = cv2.boundingRect(contour)
        if area < 600 or w < frame_w * 0.25 or h > 80:
            continue
        bars.append((x, y, w, h))

    if len(bars) < 2:
        return window_region

    bars.sort(key=lambda item: item[1])
    top_bar = bars[0]
    bottom_bar = bars[-1]

    left = max(0, min(top_bar[0], bottom_bar[0]) - 55)
    right = min(frame_w, max(top_bar[0] + top_bar[2], bottom_bar[0] + bottom_bar[2]) + 55)
    top = max(0, top_bar[1] - 45)
    bottom = min(frame_h, bottom_bar[1] + bottom_bar[3] + 45)

    if right - left < 250 or bottom - top < 400:
        return window_region

    win_x, win_y, _, _ = window_region
    return win_x + left, win_y + top, right - left, bottom - top


def make_region(args):
    if args.region:
        return tuple(args.region)

    window_region = locate_window(args.window_title)
    if window_region:
        if args.no_auto_game_region:
            return window_region
        return detect_game_region(window_region)

    return None


def capture_frame(region):
    if region is None:
        return None

    screenshot = pyautogui.screenshot(region=region)
    frame = np.array(screenshot)
    return cv2.cvtColor(frame, cv2.COLOR_RGB2BGR)


def find_colored_objects(
    frame,
    lower: np.ndarray,
    upper: np.ndarray,
    min_area: int,
    circularity_min: float | None = None,
):
    hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
    mask = cv2.inRange(hsv, lower, upper)

    kernel = np.ones((5, 5), np.uint8)
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel)
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel)

    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    objects = []

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
        objects.append(TrackedObject(x + w // 2, y + h // 2, area))

    return objects, mask


def track_objects(
    current: Iterable[TrackedObject],
    previous: Iterable[TrackedObject],
    max_distance: int,
):
    previous_list = list(previous)
    tracked = []

    for obj in current:
        nearest = None
        nearest_distance = float("inf")

        for old in previous_list:
            distance = abs(obj.x - old.x) + abs(obj.y - old.y)
            if distance < nearest_distance:
                nearest_distance = distance
                nearest = old

        if nearest is not None and nearest_distance <= max_distance:
            obj.vx = obj.x - nearest.x
            obj.vy = obj.y - nearest.y

        tracked.append(obj)

    return tracked


def choose_ball(pink_objects: list[TrackedObject], previous_ball: TrackedObject | None):
    if not pink_objects:
        return None

    moving_objects = [
        obj for obj in pink_objects if abs(obj.vx) > 0.5 or abs(obj.vy) > 0.5
    ]
    if moving_objects:
        if previous_ball is not None:
            predicted_x = previous_ball.x + previous_ball.vx
            predicted_y = previous_ball.y + previous_ball.vy
            return min(
                moving_objects,
                key=lambda obj: abs(obj.x - predicted_x) + abs(obj.y - predicted_y),
            )
        return min(moving_objects, key=lambda obj: obj.area)

    if previous_ball is not None:
        return min(
            pink_objects,
            key=lambda obj: abs(obj.x - previous_ball.x) + abs(obj.y - previous_ball.y),
        )

    # Static pink rings are usually larger. The playable ball is usually compact
    # and sits below the top UI target ring.
    return min(pink_objects, key=lambda obj: (obj.area, obj.y))


def distance(a: TrackedObject, b: TrackedObject):
    return abs(a.x - b.x) + abs(a.y - b.y)


def choose_goal(pink_objects: list[TrackedObject], ball: TrackedObject | None, area_ratio: float):
    if ball is None:
        return None

    static_targets = [
        obj
        for obj in pink_objects
        if distance(obj, ball) > 32
        and obj.area > ball.area * area_ratio
        and abs(obj.vx) < 1.0
        and abs(obj.vy) < 1.0
    ]
    if not static_targets:
        fallback_targets = [obj for obj in pink_objects if distance(obj, ball) > 45]
        if not fallback_targets:
            return None
        return max(fallback_targets, key=lambda obj: obj.area)

    return max(static_targets, key=lambda obj: obj.area)


def choose_forbidden_pinks(
    pink_objects: list[TrackedObject],
    ball: TrackedObject | None,
    goal: TrackedObject | None,
):
    if ball is None:
        return []

    forbidden = []
    for obj in pink_objects:
        if distance(obj, ball) <= 32:
            continue
        if goal is not None and distance(obj, goal) <= 32:
            continue
        if abs(obj.vx) > 1.0 or abs(obj.vy) > 1.0:
            continue
        if goal is not None and obj.area >= goal.area * 0.9:
            continue
        forbidden.append(obj)

    return forbidden


def click_moves_toward_goal(ball: TrackedObject | None, goal: TrackedObject | None):
    if ball is None or goal is None or abs(ball.vy) < 0.2:
        return True

    direction_after_click = -1 if ball.vy > 0 else 1
    goal_direction = 1 if goal.y > ball.y else -1
    return direction_after_click == goal_direction


def click_returns_to_rebound(ball: TrackedObject | None, rebound: TrackedObject | None):
    if ball is None or rebound is None or abs(ball.vy) < 0.2:
        return False

    direction_after_click = -1 if ball.vy > 0 else 1
    rebound_direction = 1 if rebound.y > ball.y else -1
    return direction_after_click == rebound_direction


def direction_after_click(ball: TrackedObject):
    return -1 if ball.vy > 0 else 1


def click_moves_toward_forbidden(
    ball: TrackedObject | None,
    forbidden: list[TrackedObject],
    x_radius: int,
):
    if ball is None or abs(ball.vy) < 0.2:
        return False

    after_click = direction_after_click(ball)
    for obj in forbidden:
        if abs(obj.x - ball.x) > x_radius:
            continue
        obj_direction = 1 if obj.y > ball.y else -1
        if after_click == obj_direction:
            return True

    return False


def should_escape_forbidden(
    ball: TrackedObject | None,
    forbidden: list[TrackedObject],
    x_radius: int,
    y_radius: int,
):
    if ball is None or abs(ball.vy) < 0.2:
        return False

    current_direction = 1 if ball.vy > 0 else -1
    for obj in forbidden:
        if abs(obj.x - ball.x) > x_radius:
            continue
        obj_direction = 1 if obj.y > ball.y else -1
        if current_direction == obj_direction and abs(obj.y - ball.y) <= y_radius:
            return True

    return False


def collect_triangle_threats(
    ball: TrackedObject,
    triangles: list[TrackedObject],
    ball_vy: float,
    danger_radius: int,
    collision_x_radius: int,
    prediction_frames: int,
    reaction_lead_frames: int,
    triangle_default_speed: float,
):
    threats = []

    if abs(ball_vy) < 0.2:
        return threats

    ball_direction = 1 if ball_vy > 0 else -1

    for triangle in triangles:
        vx = triangle.vx
        if abs(vx) < 0.2 and triangle_default_speed > 0:
            vx = triangle_default_speed if triangle.x < ball.x else -triangle_default_speed
        if abs(vx) < 0.2:
            continue

        dx = triangle.x - ball.x
        if dx * vx >= 0 and abs(dx) > collision_x_radius:
            continue

        frames_to_danger = max(
            0.0,
            (abs(dx) - collision_x_radius) / max(abs(vx), 0.1),
        )
        frames_to_danger -= reaction_lead_frames
        frames_to_danger = max(0.0, frames_to_danger)

        if frames_to_danger > prediction_frames:
            continue

        predicted_ball_y = ball.y + ball_vy * frames_to_danger
        predicted_triangle_y = triangle.y + triangle.vy * frames_to_danger
        y_distance = abs(predicted_ball_y - predicted_triangle_y)
        if y_distance > danger_radius:
            continue

        vertical_relation = triangle.y - ball.y
        if ball_direction > 0 and vertical_relation < -danger_radius:
            continue
        if ball_direction < 0 and vertical_relation > danger_radius:
            continue

        threats.append(
            Threat(
                triangle=triangle,
                frames=frames_to_danger,
                y_distance=y_distance,
                vertical_relation=vertical_relation,
            )
        )

    threats.sort(key=lambda item: (item.frames, item.y_distance))
    return threats


def predict_danger(
    ball: TrackedObject | None,
    triangles: list[TrackedObject],
    danger_radius: int,
    collision_x_radius: int,
    prediction_frames: int,
    reaction_lead_frames: int,
    pair_window_frames: int,
    group_window_frames: int,
    triangle_default_speed: float,
    reverse_safety_margin_frames: int,
):
    if ball is None:
        return None, "ball not found"

    if abs(ball.vy) < 0.2:
        ball_direction = 0
    elif ball.vy > 0:
        ball_direction = 1
    else:
        ball_direction = -1

    threats = collect_triangle_threats(
        ball,
        triangles,
        ball.vy,
        danger_radius,
        collision_x_radius,
        prediction_frames,
        reaction_lead_frames,
        triangle_default_speed,
    )
    if not threats:
        return None, "forward" if ball_direction >= 0 else "back"

    reverse_threats = collect_triangle_threats(
        ball,
        triangles,
        -ball.vy,
        danger_radius,
        collision_x_radius,
        prediction_frames,
        0,
        triangle_default_speed,
    )
    if reverse_threats and reverse_threats[0].frames <= threats[0].frames + reverse_safety_margin_frames:
        return None, "hold: reverse unsafe"

    earliest = threats[0].frames
    cluster = [
        threat
        for threat in threats
        if threat.frames <= earliest + max(pair_window_frames, group_window_frames)
    ]

    if len(cluster) >= 2:
        above = any(threat.triangle.y < ball.y for threat in cluster)
        below = any(threat.triangle.y > ball.y for threat in cluster)
        label = "group" if len(cluster) >= 3 else "paired"
        if above and below:
            return cluster[0].triangle, f"click: {label} gap ({len(cluster)})"
        return cluster[0].triangle, f"click: {label} line ({len(cluster)})"

    return threats[0].triangle, "click: reverse"


class OverlayApp:
    def __init__(self, args):
        self.args = args
        self.region = make_region(args)
        self.offset_x, self.offset_y, self.region_w, self.region_h = self.safe_region_parts()
        self.click_point = self.make_click_point()
        self.state = BotState(None, None, None, [], [], None, "starting", args.auto_click, True, self.region)
        self.lock = threading.Lock()
        self.last_click_time = 0.0
        self.last_region_check = 0.0
        self.panel_was_placed = False
        self.previous_triangles = []
        self.previous_pinks = []
        self.previous_ball = None
        self.previous_yolo_ball = []
        self.previous_yolo_forbidden = []
        self.rebound_point = None
        self.rebound_seen_frame = 0
        self.frame_index = 0
        self.yolo_detector = (
            YoloDetector(args.yolo_model, args.yolo_conf, args.yolo_imgsz)
            if args.detector == "yolo"
            else None
        )

        self.root = tk.Tk()
        self.root.title("Farm-bar overlay")
        self.root.overrideredirect(True)
        self.root.attributes("-topmost", True)
        self.root.configure(bg=TRANSPARENT_COLOR)
        if args.show_overlay and self.region is not None:
            self.root.geometry(
                f"{self.region_w}x{self.region_h}+{self.offset_x}+{self.offset_y}"
            )
            self.root.attributes("-transparentcolor", TRANSPARENT_COLOR)
        else:
            self.root.withdraw()

        self.canvas = None
        if args.show_overlay:
            self.canvas = tk.Canvas(
                self.root,
                width=self.region_w,
                height=self.region_h,
                bg=TRANSPARENT_COLOR,
                highlightthickness=0,
            )
            self.canvas.pack(fill="both", expand=True)

        self.panel = tk.Toplevel(self.root)
        self.panel.title("Bot control")
        self.panel.geometry(self.panel_geometry())
        self.panel.attributes("-topmost", True)
        self.panel.protocol("WM_DELETE_WINDOW", self.stop)

        self.status_var = tk.StringVar(value="starting")
        self.auto_var = tk.BooleanVar(value=args.auto_click)
        tk.Label(self.panel, textvariable=self.status_var, anchor="w").pack(
            fill="x", padx=10, pady=(8, 2)
        )
        tk.Checkbutton(
            self.panel,
            text="Auto click",
            variable=self.auto_var,
            command=self.set_auto_click,
        ).pack(anchor="w", padx=10)
        tk.Button(self.panel, text="Test click", command=self.click).pack(
            fill="x", padx=10, pady=4
        )
        tk.Button(self.panel, text="Quit", command=self.stop).pack(
            fill="x", padx=10, pady=(0, 8)
        )

        self.root.after(100, self.make_click_through)
        self.root.after(25, self.render)

    def safe_region_parts(self):
        if self.region is not None:
            return self.region

        width, height = screen_size()
        return 40, 40, min(420, width - 80), min(240, height - 80)

    def panel_geometry(self):
        screen_w, screen_h = screen_size()
        x = self.offset_x - PANEL_WIDTH - PANEL_MARGIN
        if x < PANEL_MARGIN:
            x = self.offset_x + self.region_w + PANEL_MARGIN
        if x + PANEL_WIDTH > screen_w - PANEL_MARGIN:
            x = PANEL_MARGIN

        y = max(PANEL_MARGIN, min(self.offset_y + PANEL_MARGIN, screen_h - PANEL_HEIGHT - PANEL_MARGIN))
        return f"{PANEL_WIDTH}x{PANEL_HEIGHT}+{x}+{y}"

    def place_panel(self, force=False):
        if self.panel_was_placed and not force:
            return

        self.panel.geometry(self.panel_geometry())
        self.panel_was_placed = True

    def make_click_point(self):
        x = self.args.click_x
        y = self.args.click_y
        if x is None:
            x = self.offset_x + max(self.region_w // 2, 1)
        if y is None:
            y = self.offset_y + max(self.region_h // 2, 1)
        return x, y

    def update_region(self):
        if self.args.region:
            return

        now = time.time()
        if now - self.last_region_check < 0.6:
            return

        self.last_region_check = now
        new_region = make_region(self.args)
        if new_region == self.region:
            return

        if self.region is not None and new_region is not None:
            old_x, old_y, old_w, old_h = self.region
            new_x, new_y, new_w, new_h = new_region
            delta = max(
                abs(old_x - new_x),
                abs(old_y - new_y),
                abs(old_w - new_w),
                abs(old_h - new_h),
            )
            if delta < 28:
                return

        self.region = new_region
        self.offset_x, self.offset_y, self.region_w, self.region_h = self.safe_region_parts()
        self.click_point = self.make_click_point()
        self.place_panel(force=not self.panel_was_placed)
        self.previous_triangles = []
        self.previous_pinks = []
        self.previous_ball = None
        self.previous_yolo_ball = []
        self.previous_yolo_forbidden = []

    def make_click_through(self):
        if not self.args.show_overlay:
            return

        hwnd = self.root.winfo_id()
        style = ctypes.windll.user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
        ctypes.windll.user32.SetWindowLongW(
            hwnd, GWL_EXSTYLE, style | WS_EX_LAYERED | WS_EX_TRANSPARENT
        )

    def set_auto_click(self):
        with self.lock:
            self.state.auto_click = self.auto_var.get()

    def stop(self):
        with self.lock:
            self.state.running = False
        self.root.destroy()

    def click(self):
        pyautogui.click(*self.click_point)
        self.last_click_time = time.time()

    def maybe_click(self, danger, ball, goal, forbidden):
        if not self.state.auto_click or danger is None:
            return

        if click_moves_toward_forbidden(ball, forbidden, self.args.forbidden_x_radius):
            self.state.action = "blocked: click toward small pink"
            return

        if click_returns_to_rebound(ball, self.rebound_point):
            self.state.action = "blocked: would return to rebound"
            return

        if not click_moves_toward_goal(ball, goal):
            self.state.action = "blocked: click would leave big goal"
            return

        now = time.time()
        if now - self.last_click_time < self.args.click_cooldown:
            return

        self.click()

    def process_loop(self):
        delay = 1 / max(self.args.fps, 1)

        while True:
            with self.lock:
                if not self.state.running:
                    break

            self.update_region()
            self.frame_index += 1
            if self.region is None:
                with self.lock:
                    self.state.ball = None
                    self.state.goal = None
                    self.state.rebound = None
                    self.state.forbidden = []
                    self.state.triangles = []
                    self.state.danger = None
                    self.state.action = "waiting for PlayDeck/Telegram window"
                    self.state.region = None
                time.sleep(0.5)
                continue

            frame = capture_frame(self.region)
            if frame is None:
                time.sleep(0.5)
                continue
            yellow_mask = None
            pink_mask = None
            detector_note = ""

            yolo_objects = (
                self.yolo_detector.detect(frame) if self.yolo_detector is not None else None
            )
            if yolo_objects is not None:
                triangles = track_objects(
                    yolo_objects["triangle"], self.previous_triangles, 120
                )
                ball_candidates = track_objects(
                    yolo_objects["ball"], self.previous_yolo_ball, 120
                )
                goal_candidates = yolo_objects["goal"]
                forbidden = track_objects(
                    yolo_objects["small"], self.previous_yolo_forbidden, 80
                )

                ball = choose_ball(ball_candidates, self.previous_ball)
                goal = max(goal_candidates, key=lambda obj: obj.area) if goal_candidates else None
                detector_note = "yolo"
            else:
                fallback_reason = ""
                if self.yolo_detector is not None and self.yolo_detector.error:
                    fallback_reason = f" after {self.yolo_detector.error}"
                yellow, yellow_mask = find_colored_objects(
                    frame,
                    np.array([20, 110, 110]),
                    np.array([42, 255, 255]),
                    self.args.yellow_min_area,
                )
                pink, pink_mask = find_colored_objects(
                    frame,
                    np.array([145, 70, 120]),
                    np.array([179, 255, 255]),
                    self.args.pink_min_area,
                    circularity_min=0.35,
                )

                triangles = track_objects(yellow, self.previous_triangles, 90)
                pink = track_objects(pink, self.previous_pinks, 90)
                ball = choose_ball(pink, self.previous_ball)
                goal = choose_goal(pink, ball, self.args.goal_area_ratio)
                forbidden = choose_forbidden_pinks(pink, ball, goal)
                detector_note = f"cv fallback{fallback_reason}" if fallback_reason else "cv"
            if (
                ball is not None
                and self.previous_ball is not None
                and abs(self.previous_ball.vy) > 0.5
                and abs(ball.vy) > 0.5
                and self.previous_ball.vy * ball.vy < 0
            ):
                self.rebound_point = TrackedObject(
                    self.previous_ball.x,
                    self.previous_ball.y,
                    self.previous_ball.area,
                    self.previous_ball.vx,
                    self.previous_ball.vy,
                )
                self.rebound_seen_frame = self.frame_index

            if (
                self.rebound_point is not None
                and self.frame_index - self.rebound_seen_frame > self.args.rebound_memory_frames
            ):
                self.rebound_point = None

            danger, action = predict_danger(
                ball,
                triangles,
                self.args.danger_radius,
                self.args.collision_x_radius,
                self.args.prediction_frames,
                self.args.reaction_lead_frames,
                self.args.pair_window_frames,
                self.args.group_window_frames,
                self.args.triangle_default_speed,
                self.args.reverse_safety_margin_frames,
            )

            self.previous_triangles = triangles
            if yolo_objects is not None:
                self.previous_yolo_ball = ball_candidates
                self.previous_yolo_forbidden = forbidden
            else:
                self.previous_pinks = pink
            self.previous_ball = ball

            with self.lock:
                self.state.ball = ball
                self.state.goal = goal
                self.state.rebound = self.rebound_point
                self.state.forbidden = forbidden
                self.state.triangles = triangles
                self.state.danger = danger
                self.state.action = f"{detector_note}: {action}"
                self.state.region = self.region
                self.maybe_click(danger, ball, goal, forbidden)

            if self.args.debug:
                if yellow_mask is not None:
                    cv2.imshow("yellow mask", yellow_mask)
                if pink_mask is not None:
                    cv2.imshow("pink mask", pink_mask)
                cv2.waitKey(1)

            time.sleep(delay)

    def render(self):
        with self.lock:
            state = BotState(
                self.state.ball,
                self.state.goal,
                self.state.rebound,
                list(self.state.forbidden),
                list(self.state.triangles),
                self.state.danger,
                self.state.action,
                self.state.auto_click,
                self.state.running,
                self.state.region,
            )

        if state.region is not None:
            region_x, region_y, region_w, region_h = state.region
            geometry = f"{region_w}x{region_h}+{region_x}+{region_y}"
            if self.args.show_overlay:
                if self.root.state() == "withdrawn":
                    self.root.deiconify()
                    self.root.attributes("-transparentcolor", TRANSPARENT_COLOR)
                    self.make_click_through()
                if self.root.geometry() != geometry:
                    self.root.geometry(geometry)
                    if self.canvas is not None:
                        self.canvas.config(width=region_w, height=region_h)
            self.place_panel()
        elif self.args.show_overlay and self.root.state() != "withdrawn":
            self.root.withdraw()

        if self.canvas is not None:
            self.canvas.delete("all")

        for triangle in state.triangles:
            color = "#ff4040" if triangle is state.danger else "#fff05a"
            if self.canvas is not None:
                self.canvas.create_oval(
                    triangle.x - 16,
                    triangle.y - 16,
                    triangle.x + 16,
                    triangle.y + 16,
                    outline=color,
                    width=3,
                )
            direction = ">" if triangle.vx > 0.5 else "<" if triangle.vx < -0.5 else "."
            if self.canvas is not None:
                self.canvas.create_text(
                    triangle.x,
                    triangle.y - 28,
                    text=direction,
                    fill=color,
                    font=("Segoe UI", 13, "bold"),
                )

        if state.ball is not None:
            if self.canvas is not None:
                self.canvas.create_oval(
                    state.ball.x - 18,
                    state.ball.y - 18,
                    state.ball.x + 18,
                    state.ball.y + 18,
                    outline="#ff2f8a",
                    width=4,
                )
                ball_direction = "down" if state.ball.vy > 0.5 else "up" if state.ball.vy < -0.5 else "wait"
                self.canvas.create_text(
                    state.ball.x,
                    state.ball.y - 32,
                    text=ball_direction,
                    fill="#ff2f8a",
                    font=("Segoe UI", 13, "bold"),
                )

        if state.goal is not None and self.canvas is not None:
            self.canvas.create_oval(
                state.goal.x - 24,
                state.goal.y - 24,
                state.goal.x + 24,
                state.goal.y + 24,
                outline="#ff9ccc",
                width=3,
            )

        if state.rebound is not None and self.canvas is not None:
            self.canvas.create_oval(
                state.rebound.x - 14,
                state.rebound.y - 14,
                state.rebound.x + 14,
                state.rebound.y + 14,
                outline="#ff5555",
                width=2,
            )

        if self.canvas is not None:
            for obj in state.forbidden:
                self.canvas.create_oval(
                    obj.x - 12,
                    obj.y - 12,
                    obj.x + 12,
                    obj.y + 12,
                    outline="#ff2222",
                    width=2,
                )

        status = (
            f"{'AUTO' if state.auto_click else 'MANUAL'} | "
            f"ball: {'yes' if state.ball else 'no'} | "
            f"goal: {'yes' if state.goal else 'no'} | "
            f"rebound: {'yes' if state.rebound else 'no'} | "
            f"small: {len(state.forbidden)} | "
            f"triangles: {len(state.triangles)} | {state.action}"
        )
        self.status_var.set(status)

        if state.running:
            self.root.after(25, self.render)

    def run(self):
        worker = threading.Thread(target=self.process_loop, daemon=True)
        worker.start()
        self.root.mainloop()
        cv2.destroyAllWindows()


def main():
    pyautogui.FAILSAFE = True
    args = parse_args()
    app = OverlayApp(args)
    app.run()


if __name__ == "__main__":
    main()
