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


def get_all_media(date_filter: str | None = None) -> list[dict]:
    if not IMAGE_DIR.exists():
        return []
    media = []
    pattern_base = f"{date_filter}/*" if date_filter else "**/*"
    for ext, media_type in ((".mp4", "movie"), (".jpg", "still")):
        for f in IMAGE_DIR.glob(pattern_base + ext):
            date_str = f.parent.name
            time_str = f.stem.replace("-", ":")
            # .jpg files that share a name with an .mp4 are poster frames, not stills
            if ext == ".jpg" and (f.with_suffix(".mp4")).exists():
                continue
            item = {
                "path": f"{date_str}/{f.name}",
                "date": date_str,
                "time": time_str,
                "type": media_type,
                "timestamp": f.stat().st_mtime,
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


if __name__ == "__main__":
    app.run(host=HOST, port=PORT, debug=False)
