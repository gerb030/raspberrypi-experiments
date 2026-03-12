#!/bin/bash
DATE=$(date +"%Y-%m-%d_%H%M")
raspistill -o /var/www/html/catcam_$DATE.jpg
