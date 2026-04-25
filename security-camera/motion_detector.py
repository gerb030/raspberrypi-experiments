#!/usr/bin/env python3
"""Motion-triggered security camera using picamera2 and OpenCV."""

import configparser
import json
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
from libcamera import Transform
from picamera2 import Picamera2

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    stream=sys.stdout,
)
log = logging.getLogger("security-camera")

CONFIG_PATH = Path(__file__).parent / "config.ini"
FAVS_PATH   = Path(__file__).parent / "favourites.json"
MIN_FREE_PCT = 5.0      # fallback — overridden by config at startup
TARGET_FREE_PCT = 15.0  # fallback — overridden by config at startup


def load_config():
    cfg = configparser.ConfigParser()
    cfg.read(CONFIG_PATH)
    return cfg


def free_disk_pct(path: Path) -> float:
    st = os.statvfs(path)
    return st.f_bavail / st.f_blocks * 100


def load_favs() -> set:
    try:
        return set(json.loads(FAVS_PATH.read_text()))
    except Exception:
        return set()


def evict_oldest(image_dir: Path) -> None:
    """Delete the single oldest media file, preferring non-favourites over favourites."""
    all_files = sorted(
        list(image_dir.glob("**/*.jpg")) + list(image_dir.glob("**/*.mp4")),
        key=lambda p: p.stat().st_mtime,
    )
    # Exclude poster JPGs — they are cleaned up alongside their MP4
    files = [f for f in all_files if not (f.suffix == ".jpg" and f.with_suffix(".mp4").exists())]
    if not files:
        return

    favs = load_favs()

    def is_fav(p: Path) -> bool:
        return f"{p.parent.name}/{p.name}" in favs

    # Non-favourites first (oldest → newest), then favourites (oldest → newest)
    non_favs = [f for f in files if not is_fav(f)]
    fav_files = [f for f in files if is_fav(f)]
    ordered = non_favs + fav_files

    oldest = ordered[0]
    oldest.unlink()
    # Remove associated poster frame if this was a movie
    if oldest.suffix == ".mp4":
        poster = oldest.with_suffix(".jpg")
        if poster.exists():
            poster.unlink()
    label = " (favourite)" if is_fav(oldest) else ""
    log.warning("Disk space low — deleted oldest%s file: %s", label, oldest)
    try:
        oldest.parent.rmdir()
    except OSError:
        pass


def enforce_retention(image_dir: Path, retention_days: int) -> None:
    """Delete files that have exceeded the retention period."""
    cutoff = time.time() - retention_days * 86400
    # Delete expired movies and their poster frames together
    for f in sorted(image_dir.glob("**/*.mp4"), key=lambda p: p.stat().st_mtime):
        if f.stat().st_mtime < cutoff:
            f.unlink()
            poster = f.with_suffix(".jpg")
            if poster.exists():
                poster.unlink()
            log.info("Retention expired — deleted: %s", f)
            try:
                f.parent.rmdir()
            except OSError:
                pass
    # Delete expired stills (skip poster JPGs — already handled above)
    for f in sorted(image_dir.glob("**/*.jpg"), key=lambda p: p.stat().st_mtime):
        if not f.exists():
            continue
        if f.stat().st_mtime < cutoff and not f.with_suffix(".mp4").exists():
            f.unlink()
            log.info("Retention expired — deleted: %s", f)
            try:
                f.parent.rmdir()
            except OSError:
                pass


def enforce_disk_space(image_dir: Path) -> None:
    """If free space drops below MIN_FREE_PCT, delete oldest files until TARGET_FREE_PCT is reached."""
    if free_disk_pct(image_dir) >= MIN_FREE_PCT:
        return
    log.warning("Disk space below %.0f%% — freeing space to %.0f%%", MIN_FREE_PCT, TARGET_FREE_PCT)
    while free_disk_pct(image_dir) < TARGET_FREE_PCT:
        before = free_disk_pct(image_dir)
        evict_oldest(image_dir)
        after = free_disk_pct(image_dir)
        if after <= before:
            log.error("Cannot free enough disk space — no more files to delete.")
            break


def save_still(frame_bgr: np.ndarray, image_dir: Path) -> Path:
    now = datetime.now()
    date_dir = image_dir / now.strftime("%Y-%m-%d")
    date_dir.mkdir(parents=True, exist_ok=True)
    filename = date_dir / now.strftime("%H-%M-%S.jpg")
    cv2.imwrite(str(filename), frame_bgr, [cv2.IMWRITE_JPEG_QUALITY, 90])
    return filename


def record_movie(cam: Picamera2, image_dir: Path, duration: float,
                 width: int, height: int, framerate: int,
                 bgr_native: bool = False) -> Path:
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
        writer.write(frame if bgr_native else cv2.cvtColor(frame, cv2.COLOR_RGB2BGR))

    writer.release()

    # Re-encode to H264 MP4 for browser playback
    result = subprocess.run(
        [
            "ffmpeg", "-y", "-i", str(tmp_path),
            "-c:v", "libx264", "-preset", "fast", "-crf", "28",
            "-movflags", "+faststart",
            str(out_path),
        ],
        capture_output=True,
    )
    tmp_path.unlink(missing_ok=True)

    if result.returncode != 0:
        log.error("ffmpeg encoding failed: %s", result.stderr.decode())
        return None

    # Extract a poster frame — accurate seek to middle, fall back to first frame
    poster_path = out_path.with_suffix(".jpg")
    seek = str(duration / 2)
    result_poster = subprocess.run(
        [
            "ffmpeg", "-y", "-i", str(out_path),
            "-ss", seek, "-vframes", "1", "-vf", "scale=800:-2", "-update", "1", "-q:v", "3", str(poster_path),
        ],
        capture_output=True,
    )
    if not poster_path.exists():
        subprocess.run(
            ["ffmpeg", "-y", "-i", str(out_path), "-vframes", "1", "-vf", "scale=800:-2", "-update", "1", "-q:v", "3", str(poster_path)],
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
    sharpness = cfg.getfloat("camera", "sharpness", fallback=1.0)
    noise_reduction = cfg.getint("camera", "noise_reduction", fallback=0)
    exposure_value = cfg.getfloat("camera", "exposure_value", fallback=0.0)
    awb_enable = cfg.getboolean("camera", "awb_enable", fallback=True)
    colour_gain_r = cfg.getfloat("camera", "colour_gain_r", fallback=2.0)
    colour_gain_b = cfg.getfloat("camera", "colour_gain_b", fallback=2.0)
    awb_mode_name = cfg.get("camera", "awb_mode", fallback="Auto").strip()
    rotation = cfg.getint("camera", "rotation", fallback=0)
    threshold = cfg.getint("motion", "sensitivity_threshold")
    min_area = cfg.getint("motion", "min_contour_area")
    cooldown = cfg.getfloat("motion", "cooldown_seconds")
    capture_mode = cfg.get("motion", "capture_mode", fallback="still").strip().lower()
    movie_duration = cfg.getfloat("motion", "movie_duration", fallback=10.0)
    image_dir = Path(cfg.get("storage", "image_dir"))
    image_dir.mkdir(parents=True, exist_ok=True)
    retention_days = cfg.getint("storage", "retention_days", fallback=90)

    global MIN_FREE_PCT, TARGET_FREE_PCT
    MIN_FREE_PCT = cfg.getfloat("storage", "min_free_pct", fallback=5.0)
    TARGET_FREE_PCT = cfg.getfloat("storage", "target_free_pct", fallback=15.0)

    if capture_mode not in ("still", "movie"):
        log.error("Invalid capture_mode '%s', defaulting to 'still'", capture_mode)
        capture_mode = "still"

    log.info("Capture mode: %s", capture_mode)

    awb_modes = {
        "Auto": 0, "Tungsten": 1, "Fluorescent": 2,
        "Indoor": 3, "Daylight": 4, "Cloudy": 5,
    }
    awb_mode = awb_modes.get(awb_mode_name, 0)

    # Detect camera model for logging; picamera2's RGB888 format always delivers
    # BGR byte order on Raspberry Pi (libcamera maps RGB888 → V4L2 RGB24 = B,G,R).
    # No channel conversion is needed before cv2.imwrite or VideoWriter.
    try:
        camera_info = Picamera2.global_camera_info()
        camera_model = camera_info[0]['Model'] if camera_info else 'unknown'
    except Exception:
        camera_model = 'unknown'
    bgr_native = True
    log.info("Camera model: %s", camera_model)

    controls = {
        "FrameRate": framerate,
        "Saturation": saturation,
        "Brightness": brightness,
        "Contrast": contrast,
        "Sharpness": sharpness,
        "NoiseReductionMode": noise_reduction,
        "ExposureValue": exposure_value,
        "AwbEnable": awb_enable,
        "AwbMode": awb_mode,
    }
    if not awb_enable:
        controls["ColourGains"] = (colour_gain_r, colour_gain_b)

    cam = Picamera2()
    config = cam.create_video_configuration(
        main={"size": (width, height), "format": "RGB888"},
        transform=Transform(rotation=rotation),
        controls=controls,
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

    gray_conversion = cv2.COLOR_BGR2GRAY if bgr_native else cv2.COLOR_RGB2GRAY
    fgbg = cv2.createBackgroundSubtractorMOG2(
        history=500, varThreshold=threshold, detectShadows=False
    )

    last_save = 0.0
    log.info("Motion detection active. Watching for movement...")

    while True:
        frame = cam.capture_array()

        gray = cv2.cvtColor(frame, gray_conversion)
        gray = cv2.GaussianBlur(gray, (21, 21), 0)

        mask = fgbg.apply(gray)
        mask = cv2.erode(mask, None, iterations=2)
        mask = cv2.dilate(mask, None, iterations=4)

        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        motion_detected = any(cv2.contourArea(c) >= min_area for c in contours)

        if motion_detected:
            now = time.monotonic()
            if now - last_save >= cooldown:
                enforce_retention(image_dir, retention_days)
                enforce_disk_space(image_dir)
                if capture_mode == "movie":
                    path = record_movie(cam, image_dir, movie_duration, width, height, framerate, bgr_native)
                else:
                    frame_bgr = frame if bgr_native else cv2.cvtColor(frame, cv2.COLOR_RGB2BGR)
                    path = save_still(frame_bgr, image_dir)
                if path:
                    log.info("Motion detected — saved %s", path)
                # Cooldown starts after capture finishes
                last_save = time.monotonic()

        time.sleep(1.0 / framerate)


if __name__ == "__main__":
    run()
