#!/usr/bin/env python3
import RPi.GPIO as IO  
import os
from time import sleep 
from datetime import datetime

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


IO.output(RED,1)
IO.output(GREEN,1)
IO.output(YELLOW,1)
i = 0 
while(i<10):
    IO.output(BUZZER,1)
    sleep(0.10)
    IO.output(BUZZER,0)
    sleep(0.40)
    i = i+1
IO.output(YELLOW,0)
IO.output(RED,0)
IO.output(BUZZER,0)

try:
    while True:
            IO.output(GREEN,1)
            sleep(0.5)
            IO.output(GREEN,0)
            sleep(2)
except (KeyboardInterrupt):
    #By doing this we reset the GPIO Pins back to default.
    print("Quitting Program")
    IO.output(RED,0)
    IO.output(YELLOW,0)
    IO.output(GREEN,0)
    IO.output(BUZZER,1)
    sleep(0.5)
    IO.output(BUZZER,0)
    IO.cleanup()
