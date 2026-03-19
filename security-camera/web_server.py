#!/usr/bin/env python3
"""Flask web server for browsing security camera images."""

import configparser
import subprocess
import threading
import time
from pathlib import Path

from flask import Flask, jsonify, redirect, render_template, request, send_from_directory, url_for

CONFIG_PATH = Path(__file__).parent / "config.ini"

def load_cfg():
    cfg = configparser.ConfigParser()
    cfg.read(CONFIG_PATH)
    return cfg

cfg = load_cfg()

IMAGE_DIR = Path(cfg.get("storage", "image_dir"))
PAGE_SIZE = cfg.getint("web", "latest_count")
HOST = cfg.get("web", "host")
PORT = cfg.getint("web", "port")

app = Flask(__name__, template_folder="templates")


def human_size(n: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024:
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} TB"


def get_all_media(date_filter: str | None = None) -> list[dict]:
    if not IMAGE_DIR.exists():
        return []
    media = []
    pattern_base = f"{date_filter}/*" if date_filter else "**/*"
    for ext, media_type in ((".mp4", "movie"), (".jpg", "still")):
        for f in IMAGE_DIR.glob(pattern_base + ext):
            date_str = f.parent.name
            time_str = f.stem.replace("-", ":")
            if ext == ".jpg" and (f.with_suffix(".mp4")).exists():
                continue
            stat = f.stat()
            item = {
                "path": f"{date_str}/{f.name}",
                "date": date_str,
                "time": time_str,
                "type": media_type,
                "timestamp": stat.st_mtime,
                "size": human_size(stat.st_size),
            }
            if media_type == "movie":
                poster = f.with_suffix(".jpg")
                if poster.exists():
                    item["poster"] = f"{date_str}/{poster.name}"
            media.append(item)
    media.sort(key=lambda x: x["timestamp"], reverse=True)
    return media


def get_dates() -> list[str]:
    if not IMAGE_DIR.exists():
        return []
    return sorted(
        {d.name for d in IMAGE_DIR.iterdir() if d.is_dir()},
        reverse=True,
    )


@app.route("/")
def index():
    return render_template("index.html", selected_date=None, title="Latest captures")


@app.route("/date/<date_str>")
def by_date(date_str: str):
    return render_template("index.html", selected_date=date_str, title=f"Captures on {date_str}")


@app.route("/api/images")
def api_images():
    date_filter = request.args.get("date")
    offset = int(request.args.get("offset", 0))
    limit = int(request.args.get("limit", PAGE_SIZE))
    all_media = get_all_media(date_filter)
    page = all_media[offset:offset + limit]
    return jsonify({
        "images": page,
        "total": len(all_media),
        "offset": offset,
        "has_more": offset + limit < len(all_media),
    })


@app.route("/api/dates")
def api_dates():
    return jsonify(get_dates())


@app.route("/images/<path:filename>")
def serve_image(filename: str):
    return send_from_directory(IMAGE_DIR, filename)


@app.route("/api/images/<path:filename>", methods=["DELETE"])
def delete_image(filename: str):
    target = IMAGE_DIR / filename
    if not target.exists():
        return jsonify({"error": "not found"}), 404
    target.unlink()
    # Remove associated poster if this was a movie
    if target.suffix == ".mp4":
        poster = target.with_suffix(".jpg")
        if poster.exists():
            poster.unlink()
    # Remove empty date directory
    try:
        target.parent.rmdir()
    except OSError:
        pass
    return jsonify({"ok": True})


# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------

RESOLUTIONS = [
    (640, 480),
    (1280, 720),
    (1640, 1232),
    (1920, 1080),
    (2592, 1944),
]

AWB_MODES = ["Auto", "Tungsten", "Fluorescent", "Indoor", "Daylight", "Cloudy"]


def read_config() -> dict:
    cfg = load_cfg()
    return {
        "resolution": f"{cfg.getint('camera', 'resolution_width')} x {cfg.getint('camera', 'resolution_height')}",
        "framerate":           cfg.getint("camera",  "framerate"),
        "saturation":          cfg.getfloat("camera", "saturation",  fallback=1.0),
        "brightness":          cfg.getfloat("camera", "brightness",  fallback=0.0),
        "contrast":            cfg.getfloat("camera", "contrast",    fallback=1.0),
        "awb_mode":            cfg.get("camera",  "awb_mode",        fallback="Auto"),
        "sensitivity_threshold": cfg.getint("motion", "sensitivity_threshold"),
        "min_contour_area":    cfg.getint("motion",  "min_contour_area"),
        "cooldown_seconds":    cfg.getfloat("motion", "cooldown_seconds"),
        "capture_mode":        cfg.get("motion",  "capture_mode",    fallback="still"),
        "movie_duration":      cfg.getfloat("motion", "movie_duration", fallback=10.0),
        "image_dir":           cfg.get("storage", "image_dir"),
        "retention_days":      cfg.getint("storage", "retention_days"),
        "min_free_pct":        cfg.getint("storage", "min_free_pct",    fallback=5),
        "target_free_pct":     cfg.getint("storage", "target_free_pct", fallback=15),
        "port":                cfg.getint("web",  "port"),
        "host":                cfg.get("web",  "host"),
        "latest_count":        cfg.getint("web",  "latest_count"),
    }


def write_config(values: dict) -> bool:
    """Persist updated values to config.ini. Returns True if web settings changed."""
    cfg = load_cfg()

    res_w, res_h = (int(x.strip()) for x in values["resolution"].split("x"))
    cfg.set("camera", "resolution_width",  str(res_w))
    cfg.set("camera", "resolution_height", str(res_h))
    cfg.set("camera", "framerate",         str(values["framerate"]))
    cfg.set("camera", "saturation",        str(values["saturation"]))
    cfg.set("camera", "brightness",        str(values["brightness"]))
    cfg.set("camera", "contrast",          str(values["contrast"]))
    cfg.set("camera", "awb_mode",          values["awb_mode"])
    cfg.set("motion", "sensitivity_threshold", str(values["sensitivity_threshold"]))
    cfg.set("motion", "min_contour_area",  str(values["min_contour_area"]))
    cfg.set("motion", "cooldown_seconds",  str(values["cooldown_seconds"]))
    cfg.set("motion", "capture_mode",      values["capture_mode"])
    cfg.set("motion", "movie_duration",    str(values["movie_duration"]))
    cfg.set("storage", "image_dir",        values["image_dir"])
    cfg.set("storage", "retention_days",   str(values["retention_days"]))
    cfg.set("storage", "min_free_pct",     str(values["min_free_pct"]))
    cfg.set("storage", "target_free_pct",  str(values["target_free_pct"]))

    old_port = cfg.getint("web", "port")
    old_host = cfg.get("web", "host")
    cfg.set("web", "port",         str(values["port"]))
    cfg.set("web", "host",         values["host"])
    cfg.set("web", "latest_count", str(values["latest_count"]))

    with open(CONFIG_PATH, "w") as f:
        cfg.write(f)

    web_changed = (values["port"] != old_port or values["host"] != old_host)
    return web_changed


def clamp(val, lo, hi):
    return max(lo, min(hi, val))


def parse_settings_form(form) -> dict:
    res_raw = form.get("resolution", "1280 x 720").replace("×", "x")
    return {
        "resolution":            res_raw,
        "framerate":             clamp(int(form.get("framerate", 10)), 1, 30),
        "saturation":            clamp(round(float(form.get("saturation", 1.0)), 2), 0.0, 2.0),
        "brightness":            clamp(round(float(form.get("brightness", 0.0)), 2), -1.0, 1.0),
        "contrast":              clamp(round(float(form.get("contrast", 1.0)), 2), 0.5, 4.0),
        "awb_mode":              form.get("awb_mode", "Auto") if form.get("awb_mode") in AWB_MODES else "Auto",
        "sensitivity_threshold": clamp(int(form.get("sensitivity_threshold", 25)), 5, 200),
        "min_contour_area":      clamp(int(form.get("min_contour_area", 1500)), 100, 20000),
        "cooldown_seconds":      clamp(int(form.get("cooldown_seconds", 10)), 1, 120),
        "capture_mode":          form.get("capture_mode", "still") if form.get("capture_mode") in ("still", "movie") else "still",
        "movie_duration":        clamp(int(form.get("movie_duration", 10)), 3, 120),
        "image_dir":             form.get("image_dir", "/home/pi/Pictures/motion"),
        "retention_days":        clamp(int(form.get("retention_days", 90)), 7, 365),
        "min_free_pct":          clamp(int(form.get("min_free_pct", 5)), 1, 30),
        "target_free_pct":       clamp(int(form.get("target_free_pct", 15)), 1, 50),
        "port":                  clamp(int(form.get("port", 80)), 1, 65535),
        "host":                  form.get("host", "0.0.0.0"),
        "latest_count":          clamp(int(form.get("latest_count", 8)), 4, 32),
    }


@app.route("/settings", methods=["GET"])
def settings():
    saved = request.args.get("saved")
    web_restarting = request.args.get("web_restarting")
    return render_template(
        "settings.html",
        cfg=read_config(),
        resolutions=[f"{w} x {h}" for w, h in RESOLUTIONS],
        awb_modes=AWB_MODES,
        saved=saved,
        web_restarting=web_restarting,
    )


@app.route("/settings", methods=["POST"])
def settings_save():
    values = parse_settings_form(request.form)
    web_changed = write_config(values)

    # Always restart the motion detector
    subprocess.run(["sudo", "systemctl", "restart", "security-camera"], capture_output=True)

    if web_changed:
        # Restart web server after a short delay so the redirect response is sent first
        def _restart_web():
            time.sleep(2)
            subprocess.run(["sudo", "systemctl", "restart", "security-camera-web"], capture_output=True)
        threading.Thread(target=_restart_web, daemon=True).start()
        return redirect(url_for("settings", saved=1, web_restarting=1))

    return redirect(url_for("settings", saved=1))


if __name__ == "__main__":
    app.run(host=HOST, port=PORT, debug=False)
