import app
import struct
import math
from machine import Pin, I2S
from system.hexpansion.config import *
from tildagonos import tildagonos
from system.patterndisplay.events import PatternDisable
from system.eventbus import eventbus
from app_components import clear_background

def hsv_to_rgb(h, s, v):
    h_i = int(h * 6)
    f = h * 6 - h_i
    p = int(255 * v * (1 - s))
    q = int(255 * v * (1 - f * s))
    t = int(255 * v * (1 - (1 - f) * s))
    v = int(255 * v)
    h_i = h_i % 6
    if h_i == 0:
        return v, t, p
    elif h_i == 1:
        return q, v, p
    elif h_i == 2:
        return p, v, t
    elif h_i == 3:
        return p, q, v
    elif h_i == 4:
        return t, p, v
    else:
        return v, p, q


class MicApp(app.App):
    def __init__(self, config=None):
        
        eventbus.emit(PatternDisable()) # disable the ambient pattern. 
        self.hexpansion_config = HexpansionConfig(2) # set the hexpansion socket.

        self.volume = 0.0 # current absolute volume
        self.rmin = 1.0 # rolling minimum
        self.rmax = 10.0 # rolling maximum
        self.relative = 0.1 # relative volume
        self.vl_decay = 0.99 # volume limit decay

        self.buffer = bytearray(1024)

        self.led_levels = [0.0] * 12  # Current level for each LED
        self.led_decay = .4 # led decay factor

        # set up the microphone
        self.i2s = I2S(
            0,
            sck=self.hexpansion_config.pin[0],
            ws=self.hexpansion_config.pin[1],
            sd=self.hexpansion_config.pin[2],
            mode=I2S.RX,
            bits=16,
            format=I2S.MONO,
            rate=16000,
            ibuf=1024 * 4
        )

        # Order of LEDs from bottom -> top
        self.led_order = [6, 7, 5, 8, 4, 9, 3, 10, 2, 11, 1, 12]
        self.hue = 0.0
        self.brightness_control = 0.5

    def get_volume(self):
        # Calculate RMS volume and maintain rolling range
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
            self.rmin = self.rmin / self.vl_decay
        if self.volume > self.rmax:
            self.rmax = self.volume
        else:
            self.rmax = self.rmax * self.vl_decay

        # Get relative position
        self.relative = (self.volume - self.rmin) / (self.rmax - self.rmin) if (self.rmax - self.rmin) > 0 else 0
        self.relative = math.pow(max(min(self.relative, 1), 0),2)
        
    def paint_leds(self):
        
        total_brightness = 12.0 * self.relative
        
        for i, led in enumerate(self.led_order):
            if total_brightness >= 1:
                led_brightness = 1
                total_brightness-=1
            else:
                led_brightness = total_brightness
                total_brightness = 0
            #print(self.led_levels[i],led_brightness)
            self.led_levels[i] = max(self.led_levels[i],led_brightness) # set high water mark
            
            r,g,b = hsv_to_rgb(self.hue + (i * 0.02), 1.0, self.led_levels[i] * self.brightness_control)
            
            #tildagonos.leds[led] = (0,int(self.led_levels[i]*255), int(self.led_levels[i]*255)) # paint leds
            tildagonos.leds[led] = (r, g, b) # paint leds
            
            self.led_levels[i] = max(self.led_levels[i] - self.led_decay, 0) # decay high water mark
            
        tildagonos.leds.write()
        
        self.hue += 0.01
        if self.hue >= 1.0:
            self.hue-= 1.0
            
            

    def update(self, delta):
        """Update LEDs with gradual lighting and trailing effect."""
        self.get_volume()

        self.paint_leds()
            

        

    def draw(self, ctx):
        """Clear screen each frame."""
        clear_background(ctx)


__app_export__ = MicApp

