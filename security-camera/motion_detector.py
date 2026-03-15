#!/usr/bin/env python3
"""Motion-triggered security camera using picamera2 and OpenCV."""

import configparser
import logging
import os
import signal
import subprocess
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
    """Delete the single oldest media file to reclaim space."""
    files = sorted(
        list(image_dir.glob("**/*.jpg")) + list(image_dir.glob("**/*.mp4")),
        key=lambda p: p.stat().st_mtime,
    )
    if not files:
        return
    oldest = files[0]
    oldest.unlink()
    # Remove associated poster frame if this was a movie
    if oldest.suffix == ".mp4":
        poster = oldest.with_suffix(".jpg")
        if poster.exists():
            poster.unlink()
    log.warning("Disk space low — deleted oldest file: %s", oldest)
    try:
        oldest.parent.rmdir()
    except OSError:
        pass


def enforce_disk_space(image_dir: Path) -> None:
    """Keep deleting oldest files until free space is above MIN_FREE_PCT."""
    while free_disk_pct(image_dir) < MIN_FREE_PCT:
        before = free_disk_pct(image_dir)
        evict_oldest(image_dir)
        after = free_disk_pct(image_dir)
        if after <= before:
            log.error("Cannot free enough disk space — no more files to delete.")
            break


def save_still(frame_rgb: np.ndarray, image_dir: Path) -> Path:
    now = datetime.now()
    date_dir = image_dir / now.strftime("%Y-%m-%d")
    date_dir.mkdir(parents=True, exist_ok=True)
    filename = date_dir / now.strftime("%H-%M-%S.jpg")
    bgr = cv2.cvtColor(frame_rgb, cv2.COLOR_RGB2BGR)
    cv2.imwrite(str(filename), bgr, [cv2.IMWRITE_JPEG_QUALITY, 90])
    return filename


def record_movie(cam: Picamera2, image_dir: Path, duration: float,
                 width: int, height: int, framerate: int) -> Path:
    """Capture frames into a temp AVI then re-encode to H264 MP4."""
    now = datetime.now()
    date_dir = image_dir / now.strftime("%Y-%m-%d")
    date_dir.mkdir(parents=True, exist_ok=True)

    tmp_path = date_dir / (now.strftime("%H-%M-%S") + "_tmp.avi")
    out_path = date_dir / now.strftime("%H-%M-%S.mp4")

    fourcc = cv2.VideoWriter_fourcc(*"MJPG")
    writer = cv2.VideoWriter(str(tmp_path), fourcc, float(framerate), (width, height))

    log.info("Recording movie for %.1fs → %s", duration, out_path)
    end_time = time.monotonic() + duration
    while time.monotonic() < end_time:
        frame = cam.capture_array()
        bgr = cv2.cvtColor(frame, cv2.COLOR_RGB2BGR)
        writer.write(bgr)

    writer.release()

    # Re-encode to H264 MP4 for browser playback
    result = subprocess.run(
        [
            "ffmpeg", "-y", "-i", str(tmp_path),
            "-c:v", "libx264", "-preset", "ultrafast", "-crf", "28",
            str(out_path),
        ],
        capture_output=True,
    )
    tmp_path.unlink(missing_ok=True)

    if result.returncode != 0:
        log.error("ffmpeg encoding failed: %s", result.stderr.decode())
        return None

    # Extract a poster frame from the middle of the clip
    poster_path = out_path.with_suffix(".jpg")
    subprocess.run(
        [
            "ffmpeg", "-y", "-ss", str(duration / 2), "-i", str(out_path),
            "-vframes", "1", "-q:v", "3", str(poster_path),
        ],
        capture_output=True,
    )

    return out_path


def run():
    cfg = load_config()

    width = cfg.getint("camera", "resolution_width")
    height = cfg.getint("camera", "resolution_height")
    framerate = cfg.getint("camera", "framerate")
    saturation = cfg.getfloat("camera", "saturation", fallback=1.0)
    brightness = cfg.getfloat("camera", "brightness", fallback=0.0)
    contrast = cfg.getfloat("camera", "contrast", fallback=1.0)
    awb_mode_name = cfg.get("camera", "awb_mode", fallback="Auto").strip()
    threshold = cfg.getint("motion", "sensitivity_threshold")
    min_area = cfg.getint("motion", "min_contour_area")
    cooldown = cfg.getfloat("motion", "cooldown_seconds")
    capture_mode = cfg.get("motion", "capture_mode", fallback="still").strip().lower()
    movie_duration = cfg.getfloat("motion", "movie_duration", fallback=10.0)
    image_dir = Path(cfg.get("storage", "image_dir"))
    image_dir.mkdir(parents=True, exist_ok=True)

    if capture_mode not in ("still", "movie"):
        log.error("Invalid capture_mode '%s', defaulting to 'still'", capture_mode)
        capture_mode = "still"

    log.info("Capture mode: %s", capture_mode)

    awb_modes = {
        "Auto": 0, "Tungsten": 1, "Fluorescent": 2,
        "Indoor": 3, "Daylight": 4, "Cloudy": 5,
    }
    awb_mode = awb_modes.get(awb_mode_name, 0)

    cam = Picamera2()
    config = cam.create_video_configuration(
        main={"size": (width, height), "format": "RGB888"},
        controls={
            "FrameRate": framerate,
            "Saturation": saturation,
            "Brightness": brightness,
            "Contrast": contrast,
            "AwbMode": awb_mode,
        },
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
                if capture_mode == "movie":
                    path = record_movie(cam, image_dir, movie_duration, width, height, framerate)
                else:
                    path = save_still(frame, image_dir)
                if path:
                    log.info("Motion detected — saved %s", path)
                # Cooldown starts after capture finishes
                last_save = time.monotonic()

        time.sleep(1.0 / framerate)


if __name__ == "__main__":
    run()
