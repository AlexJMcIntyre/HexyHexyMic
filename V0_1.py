import app
import time
import struct
import math
from machine import Pin, I2S
from events.input import Buttons, BUTTON_TYPES
from system.hexpansion.config import *



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
        self.buffer = bytearray(4096)
        
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
            ibuf=4096
        )
        

    def update(self, delta):
        """Check for button presses and read I2S data."""
        #print("reading")
        
        if self.button_states.get(BUTTON_TYPES["CANCEL"]):
            self.button_states.clear()
            self.minimise()
        #try:
        num_read = self.i2s.readinto(self.buffer)
        #if num_read > 0:
        self.volume = get_volume(self.buffer)
                
        #except Exception as e:
            # If needed, you can print or log the error
         #   pass


    def draw(self, ctx):
        """Draw the screen every frame."""
        ctx.save()
        ctx.rgb(0.2, 0, 0).rectangle(-120, -120, 240, 240).fill()
        ctx.rgb(0, 1, 0).move_to(-50, 0).text(f"Volume: {self.volume:.2f}")
        ctx.restore()


__app_export__ = ExampleApp

