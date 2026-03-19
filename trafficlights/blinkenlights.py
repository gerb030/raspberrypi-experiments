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
IO.output(GREEN,0)

loop_size = 32
sub_array_size = 3
blinken = np.random.choice([0, 1], size=(loop_size, sub_array_size))
n = 0 
try:
    while True: 
        while n < loop_size: 
            IO.output(RED, bool(blinken[n][0]))
            IO.output(YELLOW, bool(blinken[n][1])) 
            IO.output(GREEN, bool(blinken[n][2])) 
            sleep(1)
            n += 1
        n=0
except (KeyboardInterrupt):
    #By doing this we reset the GPIO Pins back to default.
    print("Quitting Program")
    IO.output(RED,0)
    IO.output(YELLOW,0)
    IO.output(GREEN,0)
    IO.cleanup()
