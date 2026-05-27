from ultralytics import YOLO
from pathlib import Path
import shutil


def main():
    model = YOLO("yolo11n.pt")
    result = model.train(
        data="yolo_farmbar.yaml",
        epochs=60,
        imgsz=960,
        batch=8,
        device="cpu",
        workers=0,
        project="runs/farmbar",
        name="yolo11n",
    )
    best = Path(result.save_dir) / "weights" / "best.pt"
    output = Path("models/farmbar-yolo.pt")
    output.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(best, output)
    print(f"Saved {output}")


if __name__ == "__main__":
    main()
