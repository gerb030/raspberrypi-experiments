#!/usr/bin/env python3
"""Flask web server for browsing security camera images."""

import configparser
from pathlib import Path

from flask import Flask, jsonify, render_template, request, send_from_directory

CONFIG_PATH = Path(__file__).parent / "config.ini"
cfg = configparser.ConfigParser()
cfg.read(CONFIG_PATH)

IMAGE_DIR = Path(cfg.get("storage", "image_dir"))
PAGE_SIZE = cfg.getint("web", "latest_count")
HOST = cfg.get("web", "host")
PORT = cfg.getint("web", "port")

app = Flask(__name__, template_folder="templates")


def get_all_images(date_filter: str | None = None) -> list[dict]:
    if not IMAGE_DIR.exists():
        return []
    images = []
    pattern = f"{date_filter}/*.jpg" if date_filter else "**/*.jpg"
    for jpg in IMAGE_DIR.glob(pattern):
        date_str = jpg.parent.name
        time_str = jpg.stem.replace("-", ":")
        images.append({
            "path": f"{date_str}/{jpg.name}",
            "date": date_str,
            "time": time_str,
            "timestamp": jpg.stat().st_mtime,
        })
    images.sort(key=lambda x: x["timestamp"], reverse=True)
    return images


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
    all_images = get_all_images(date_filter)
    page = all_images[offset:offset + limit]
    return jsonify({
        "images": page,
        "total": len(all_images),
        "offset": offset,
        "has_more": offset + limit < len(all_images),
    })


@app.route("/api/dates")
def api_dates():
    return jsonify(get_dates())


@app.route("/images/<path:filename>")
def serve_image(filename: str):
    return send_from_directory(IMAGE_DIR, filename)


if __name__ == "__main__":
    app.run(host=HOST, port=PORT, debug=False)
