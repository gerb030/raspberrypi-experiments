# Security Camera — Installation Guide

Motion-triggered security camera for Raspberry Pi with a Noir camera. Saves timestamped photos locally, auto-deletes after 90 days, and serves a web UI for browsing captures.

## Requirements

- Raspberry Pi (tested on Pi 4 Model B)
- Raspberry Pi camera module (tested with IMX219 / Noir camera)
- Raspberry Pi OS / Debian Trixie or later
- Camera enabled in `/boot/firmware/config.txt` (`camera_auto_detect=1`)

## 1. Install dependencies

```bash
sudo apt update
sudo apt install -y python3-opencv python3-picamera2 python3-flask
```

## 2. Copy application files

```bash
sudo mkdir -p /home/pi/security-camera/templates
sudo cp motion_detector.py web_server.py config.ini /home/pi/security-camera/
sudo cp templates/index.html /home/pi/security-camera/templates/
sudo chown -R pi:pi /home/pi/security-camera
```

## 3. Create the image storage directory

```bash
mkdir -p /home/pi/Pictures/motion
```

## 4. Install systemd services

```bash
sudo cp systemd/security-camera.service /etc/systemd/system/
sudo cp systemd/security-camera-web.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable security-camera.service security-camera-web.service
sudo systemctl start security-camera.service security-camera-web.service
```

## 5. Set up automatic cleanup (cron)

Add a daily job to delete images older than 90 days:

```bash
(crontab -l 2>/dev/null; echo "0 2 * * * find /home/pi/Pictures/motion -name '*.jpg' -mtime +90 -delete && find /home/pi/Pictures/motion -mindepth 1 -type d -empty -delete") | crontab -
```

## 6. Verify

```bash
systemctl status security-camera
systemctl status security-camera-web
journalctl -u security-camera -f
```

Open `http://<pi-ip-address>` in a browser to view the web UI.

---

## Configuration

Edit `/home/pi/security-camera/config.ini`, then restart the relevant service:

```bash
sudo systemctl restart security-camera        # after changing motion/camera settings
sudo systemctl restart security-camera-web    # after changing web settings
```

### Camera

| Key | Default | Description |
|---|---|---|
| `resolution_width` | `1280` | Capture width in pixels |
| `resolution_height` | `720` | Capture height in pixels |
| `framerate` | `10` | Frames per second |
| `saturation` | `0.0` | Colour saturation. `0.0` = greyscale, `1.0` = normal colour. Greyscale is recommended for NoIR cameras to avoid the purple/blue IR cast. |
| `brightness` | `0.0` | Brightness adjustment from `-1.0` (black) to `1.0` (white). `0.0` is unchanged. |
| `contrast` | `1.0` | Contrast multiplier. `1.0` is unchanged, higher values increase tonal range. |
| `awb_mode` | `Auto` | Auto white balance preset. Options: `Auto`, `Tungsten`, `Fluorescent`, `Indoor`, `Daylight`, `Cloudy`. `Tungsten` or `Indoor` can reduce blue cast under IR lighting. |

### Capture mode

| Key | Default | Description |
|---|---|---|
| `capture_mode` | `still` | `still` saves a JPEG on motion; `movie` records a video clip |
| `movie_duration` | `10` | Length of recorded clip in seconds (only used when `capture_mode = movie`) |

**Still mode** — saves a single JPEG at the moment motion is detected. Lightweight, instant, no extra disk space overhead.

**Movie mode** — records a clip for `movie_duration` seconds starting from the moment motion is detected. Clips are saved as H264 MP4 and are playable inline in the web UI. A poster frame (thumbnail) is extracted automatically from the middle of each clip.

### Motion sensitivity

| Key | Default | Description |
|---|---|---|
| `sensitivity_threshold` | `25` | How much a pixel must change to be considered motion. Lower = more sensitive. |
| `min_contour_area` | `1500` | Minimum size (in pixels) of a moving region before it triggers a capture. Filters out noise and small objects like insects. |
| `cooldown_seconds` | `10` | Minimum time between captures. In movie mode, cooldown starts after the clip finishes recording. |

**Tuning sensitivity** — if the camera triggers too often:

1. Raise `sensitivity_threshold` first — this ignores subtle lighting changes:
   - `25` — default, catches minor movement
   - `50` — good for rooms with variable light or outdoor scenes
   - `100`+ — only obvious, fast movement

2. Raise `min_contour_area` to filter small objects:
   - `1500` — hand-sized or larger
   - `5000` — roughly head/torso sized
   - `10000`+ — only large movement across the frame

Watch triggers in real time while adjusting:
```bash
journalctl -u security-camera -f
```

### Storage

| Key | Default | Description |
|---|---|---|
| `image_dir` | `/home/pi/Pictures/motion` | Root directory for saved captures |
| `retention_days` | `90` | Age in days after which files are deleted by the nightly cron job |

Disk space is also enforced at runtime: if free space drops below 5%, the oldest captures are deleted automatically before each new save.

### Web UI

| Key | Default | Description |
|---|---|---|
| `port` | `80` | Port the web UI listens on |
| `host` | `0.0.0.0` | Bind address (default allows access from any device on the network) |
| `latest_count` | `8` | Number of captures loaded per scroll page |

---

## File layout

```
/home/pi/security-camera/
├── motion_detector.py     # captures frames, detects motion, saves captures
├── web_server.py          # Flask web UI
├── config.ini             # all configuration
└── templates/
    └── index.html         # web UI template

/home/pi/Pictures/motion/
└── YYYY-MM-DD/
    ├── HH-MM-SS.jpg       # still capture, or poster frame for a movie
    └── HH-MM-SS.mp4       # movie clip (when capture_mode = movie)

/etc/systemd/system/
├── security-camera.service
└── security-camera-web.service
```

## Logs

```bash
journalctl -u security-camera -f        # motion detector
journalctl -u security-camera-web -f    # web server
```
