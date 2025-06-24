import app
import time
import struct
import math
from machine import Pin, I2S
from events.input import Buttons, BUTTON_TYPES
from system.hexpansion.config import *
from tildagonos import tildagonos
from system.patterndisplay.events import PatternDisable
from system.eventbus import eventbus
from app_components import clear_background


def get_volume(data):
    """Calculate RMS volume from 16-bit samples."""
    total = 0
    count = len(data) // 2
    for i in range(0, len(data), 2):
        sample = struct.unpack("<h", data[i:i + 2])[0]
        total += sample * sample
    return math.sqrt(total / count) if count > 0 else 0

class ExampleApp(app.App):
    def __init__(self, config=None):
        self.button_states = Buttons(self)
        #self.hexpansion_config = None
        self.hexpansion_config = HexpansionConfig(2)
        self.volume = 0
        self.buffer = bytearray(1024)
        eventbus.emit(PatternDisable())
        
        # I2S configuration
        self.i2s = I2S(
            0,
            sck=self.hexpansion_config.pin[0],           # BCLK
            ws=self.hexpansion_config.pin[1],            # LRCLK
            sd=self.hexpansion_config.pin[2],            # DATA
            mode=I2S.RX,
            bits=16,
            format=I2S.MONO,
            rate=16000,
            ibuf=1024 * 4
        )
        

    def update(self, delta):
        """Check for button presses and read I2S data."""

        num_read = self.i2s.readinto(self.buffer)
        self.volume = get_volume(self.buffer)
        mix = min(int(self.volume/100),12)
        #print(mix)
        for i in range(0,12):
            if i <= mix:
                tildagonos.leds[i] = (0, 50, 50)
            else:
                tildagonos.leds[i] = (0, 0, 0)
    
    def draw(self, ctx):
        clear_background(ctx)




__app_export__ = ExampleApp
