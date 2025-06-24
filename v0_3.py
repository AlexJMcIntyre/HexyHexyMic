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


class ExampleApp(app.App):
    def __init__(self, config=None):
        # disable the LED pattern so we can use LEDs for visualisation
        eventbus.emit(PatternDisable())

        # set up hexpansion
        self.hexpansion_config = HexpansionConfig(2)

        self.volume = 0 # absolue
        self.rmin = 1  # Rolling min
        self.rmax = 100  # Rolling max
        self.relative = 0  # factor
        
        self.alpha = 0.99  # Higher = slower background adaptation
        self.buffer = bytearray(1024)

        # I2S configuration
        self.i2s = I2S(
            0,
            sck=self.hexpansion_config.pin[0],  # BCLK
            ws=self.hexpansion_config.pin[1],   # LRCLK
            sd=self.hexpansion_config.pin[2],   # DATA
            mode=I2S.RX,
            bits=16,
            format=I2S.MONO,
            rate=16000,
            ibuf=1024 * 4
        )

    def get_volume(self):
        """Calculate the RMS volume and update rolling background average."""
        self.i2s.readinto(self.buffer)

        total = 0
        count = len(self.buffer) // 2
        for i in range(0, len(self.buffer), 2):
            sample = struct.unpack("<h", self.buffer[i:i + 2])[0]
            total += sample * sample
        rms = math.sqrt(total / count) if count > 0 else 0

        self.volume = rms
        
        if self.volume < self.rmin:
            self.rmin = self.volume
        else:
            self.rmin = self.rmin / self.alpha
            
        if self.volume > self.rmax:
            self.rmax = self.volume
        else:
            self.rmax = self.rmax * self.alpha
        
        self.relative = max(min((self.volume-self.rmin)/(self.rmax - self.rmin),1),0)
        

    def update(self, delta):
        """Update the LEDs based on the volume relative to background."""
        self.get_volume()

        # Scale to LED range
        mix = int(math.pow(self.relative,2) * 12)

        for i in range(1, 13):
            if i <= mix:
                tildagonos.leds[i] = (0, 50, 50)  # Bright
            else:
                tildagonos.leds[i] = (0, 0, 0)      # Off
        tildagonos.leds.write()

    def draw(self, ctx):
        """Clear the screen."""
        clear_background(ctx)
        #print("min=", self.rmin, ", max=", self.rmax, "Relative=", self.relative)


__app_export__ = ExampleApp

