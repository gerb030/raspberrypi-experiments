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

Edit `/home/pi/security-camera/config.ini`, then restart the relevant service.

| Section | Key | Default | Description |
|---|---|---|---|
| `[camera]` | `resolution_width` | `1280` | Capture width in pixels |
| `[camera]` | `resolution_height` | `720` | Capture height in pixels |
| `[camera]` | `framerate` | `10` | Frames per second |
| `[motion]` | `sensitivity_threshold` | `25` | Pixel difference threshold (lower = more sensitive) |
| `[motion]` | `min_contour_area` | `1500` | Minimum contour area to count as motion (filters noise) |
| `[motion]` | `cooldown_seconds` | `10` | Minimum seconds between saved photos |
| `[storage]` | `image_dir` | `/home/pi/Pictures/motion` | Root directory for saved images |
| `[storage]` | `retention_days` | `90` | Days before images are deleted by cron |
| `[web]` | `port` | `80` | Web UI port |
| `[web]` | `host` | `0.0.0.0` | Web UI bind address |
| `[web]` | `latest_count` | `8` | Images loaded per scroll page |

```bash
sudo systemctl restart security-camera        # after changing motion/camera settings
sudo systemctl restart security-camera-web    # after changing web settings
```

---

## File layout

```
/home/pi/security-camera/
├── motion_detector.py     # captures frames, detects motion, saves images
├── web_server.py          # Flask web UI
├── config.ini             # all configuration
└── templates/
    └── index.html         # web UI template

/home/pi/Pictures/motion/
└── YYYY-MM-DD/
    └── HH-MM-SS.jpg       # timestamped captures

/etc/systemd/system/
├── security-camera.service
└── security-camera-web.service
```

## Logs

```bash
journalctl -u security-camera -f        # motion detector
journalctl -u security-camera-web -f    # web server
```
