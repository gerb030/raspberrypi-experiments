#!/usr/bin/env python3
"""Motion-triggered security camera using picamera2 and OpenCV."""

import configparser
import logging
import os
import signal
import sys
import time
from datetime import datetime
from pathlib import Path

import cv2
import numpy as np
from picamera2 import Picamera2

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    stream=sys.stdout,
)
log = logging.getLogger("security-camera")

CONFIG_PATH = Path(__file__).parent / "config.ini"
MIN_FREE_PCT = 5.0  # enforce at least this % free disk space


def load_config():
    cfg = configparser.ConfigParser()
    cfg.read(CONFIG_PATH)
    return cfg


def free_disk_pct(path: Path) -> float:
    st = os.statvfs(path)
    return st.f_bavail / st.f_blocks * 100


def evict_oldest(image_dir: Path) -> None:
    """Delete the single oldest image file to reclaim space."""
    jpgs = sorted(image_dir.glob("**/*.jpg"), key=lambda p: p.stat().st_mtime)
    if not jpgs:
        return
    oldest = jpgs[0]
    oldest.unlink()
    log.warning("Disk space low — deleted oldest image: %s", oldest)
    # Remove empty date directory if nothing left in it
    try:
        oldest.parent.rmdir()
    except OSError:
        pass


def enforce_disk_space(image_dir: Path) -> None:
    """Keep deleting oldest images until free space is above MIN_FREE_PCT."""
    while free_disk_pct(image_dir) < MIN_FREE_PCT:
        before = free_disk_pct(image_dir)
        evict_oldest(image_dir)
        after = free_disk_pct(image_dir)
        if after <= before:
            # No files left to delete, stop to avoid infinite loop
            log.error("Cannot free enough disk space — no more images to delete.")
            break


def save_image(frame_rgb: np.ndarray, image_dir: Path) -> Path:
    now = datetime.now()
    date_dir = image_dir / now.strftime("%Y-%m-%d")
    date_dir.mkdir(parents=True, exist_ok=True)
    filename = date_dir / now.strftime("%H-%M-%S.jpg")
    bgr = cv2.cvtColor(frame_rgb, cv2.COLOR_RGB2BGR)
    cv2.imwrite(str(filename), bgr, [cv2.IMWRITE_JPEG_QUALITY, 90])
    return filename


def run():
    cfg = load_config()

    width = cfg.getint("camera", "resolution_width")
    height = cfg.getint("camera", "resolution_height")
    framerate = cfg.getint("camera", "framerate")
    threshold = cfg.getint("motion", "sensitivity_threshold")
    min_area = cfg.getint("motion", "min_contour_area")
    cooldown = cfg.getfloat("motion", "cooldown_seconds")
    image_dir = Path(cfg.get("storage", "image_dir"))
    image_dir.mkdir(parents=True, exist_ok=True)

    cam = Picamera2()
    config = cam.create_video_configuration(
        main={"size": (width, height), "format": "RGB888"},
        controls={"FrameRate": framerate},
    )
    cam.configure(config)

    def shutdown(sig, frame):
        log.info("Shutting down...")
        cam.stop()
        cam.close()
        sys.exit(0)

    signal.signal(signal.SIGTERM, shutdown)
    signal.signal(signal.SIGINT, shutdown)

    cam.start()
    log.info("Camera started at %dx%d @ %d fps", width, height, framerate)

    # Warm up
    time.sleep(2)

    fgbg = cv2.createBackgroundSubtractorMOG2(
        history=500, varThreshold=threshold, detectShadows=False
    )

    last_save = 0.0
    log.info("Motion detection active. Watching for movement...")

    while True:
        frame = cam.capture_array()

        gray = cv2.cvtColor(frame, cv2.COLOR_RGB2GRAY)
        gray = cv2.GaussianBlur(gray, (21, 21), 0)

        mask = fgbg.apply(gray)
        mask = cv2.erode(mask, None, iterations=2)
        mask = cv2.dilate(mask, None, iterations=4)

        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        motion_detected = any(cv2.contourArea(c) >= min_area for c in contours)

        if motion_detected:
            now = time.monotonic()
            if now - last_save >= cooldown:
                enforce_disk_space(image_dir)
                path = save_image(frame, image_dir)
                log.info("Motion detected — saved %s", path)
                last_save = now

        time.sleep(1.0 / framerate)


if __name__ == "__main__":
    run()
