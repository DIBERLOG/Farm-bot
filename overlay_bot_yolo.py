import sys

from overlay_bot import main


if "--detector" not in sys.argv:
    sys.argv.extend(["--detector", "yolo"])


if __name__ == "__main__":
    main()
