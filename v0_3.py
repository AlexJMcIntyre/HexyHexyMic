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


class ExampleApp(app.App):
    def __init__(self, config=None):
        eventbus.emit(PatternDisable())

        self.hexpansion_config = HexpansionConfig(2)

        self.volume = 0
        self.rmin = 1.0
        self.rmax = 100.0
        self.relative = 0

        self.alpha = 0.99
        self.buffer = bytearray(1024)

        self.led_levels = [0] * 12      # Current level for each LED
        self.peak_levels = [0] * 12     # Peak/trail levels
        self.decay_rate = 100             # Amount of decay per frame (tweak)

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

    def get_volume(self):
        """Calculate RMS volume and maintain rolling range."""
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

        # Get relative position
        self.relative = (self.volume - self.rmin) / (self.rmax - self.rmin) if (self.rmax - self.rmin) > 0 else 0
        self.relative = max(min(self.relative, 1), 0)

    def update(self, delta):
        """Update LEDs with gradual lighting and trailing effect."""
        self.get_volume()

        num_leds = int(math.pow(self.relative, 2) * 12)

        # Update led_levels
        for idx, led in enumerate(self.led_order):
            target_level = 255 if idx < num_leds else 0
            # Smooth the level (instant rise, quick fall), you can tweak this
            self.led_levels[idx] = target_level if target_level > self.led_levels[idx] else max(self.led_levels[idx] - self.decay_rate, 0)

            # Maintain peak_levels
            if self.led_levels[idx] > self.peak_levels[idx]:
                self.peak_levels[idx] = self.led_levels[idx]
            else:
                self.peak_levels[idx] = max(self.peak_levels[idx] - self.decay_rate // 2, 0)

        # Push to LEDs
        for idx, led in enumerate(self.led_order):
            live_level = self.led_levels[idx]
            trail_level = self.peak_levels[idx]
            brightness = max(live_level, trail_level)
            r, g, b = hsv_to_rgb(0.5,1,brightness // 5)

            # Set LED color (teal shade for example), scaled by brightness
            tildagonos.leds[led] = (0,brightness // 5, brightness // 5)

        tildagonos.leds.write()

    def draw(self, ctx):
        """Clear screen each frame."""
        clear_background(ctx)


__app_export__ = ExampleApp

