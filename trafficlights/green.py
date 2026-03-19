#!/usr/bin/env python3
import RPi.GPIO as IO  
import os
from time import sleep 
from datetime import datetime
import numpy as np

IO.setmode(IO.BCM) 

RED = 24
YELLOW = 23
GREEN = 22
BUTTON = 25
BUZZER = 5
outputs = [RED, YELLOW, GREEN, BUZZER]

#set all outputs to be outputs
for output in outputs:
    IO.setup(output,IO.OUT)

IO.setup(BUTTON,IO.IN,pull_up_down=IO.PUD_UP)

IO.output(RED,0)
IO.output(YELLOW,0)
IO.output(GREEN,1)
#IO.cleanup()
