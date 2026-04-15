import app
import struct
import math
import time
from machine import Pin, I2S, I2C
from app_components import clear_background, Menu, Notification
from system.eventbus import eventbus
from system.patterndisplay.events import PatternDisable, PatternEnable
from system.scheduler.events import RequestForegroundPushEvent
from tildagonos import tildagonos

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
    
menu_items = [
    "HexyHexyMic!",
    "Vis Mode",
    "Color Palette",
    "Brightness"]

class MicApp(app.App):
    def __init__(self, config=None):
        eventbus.emit(PatternDisable()) # disable the ambient pattern. We're going to need those LEDs!
        self.hexpansion_config = config
        self.foregrounded = False

        self.buffersize = 1024 * 4 # this seems baked into the esp32, can't go lower. 

        self.rms = 0.0 # current rms volume
        self.rmin = 1.0 # rolling minimum
        self.rmax = 10.0 # rolling maximum
        self.relative = 0.1 # relative volume
        self.window_decay = 0.99 # how quickly the rolling min and max adjust to changes in volume. Closer to 1 is slower decay, closer to 0 is faster decay
        
        self.brightness_control = 0.5 # global brightness modifier
        self.led_high_levels = [0.0] * 12  # High water mark for each led
        self.led_high_decay = 0.3 # high water mark decay

        self.buffer = bytearray(self.buffersize) #buffer to get the raw bitstream from the mic

        # set up the microphone
        self.i2s = I2S(
            0,
            sck=self.hexpansion_config.pin[0],
            ws=self.hexpansion_config.pin[1],
            sd=self.hexpansion_config.pin[2],
            mode=I2S.RX,
            bits=32,
            format=I2S.MONO,
            rate=48000,
            ibuf=self.buffersize
        )
    
        #set up the menu        
        self.vismode = 0
        self.vismodes = ["RMS", "ZC", "FFT", "Vortex"]
        self.palette = 0   
        self.palettes = [("Neon",(0.83,0.49,0.38)),
                        ("Sunset",(0.02, 0.08, 0.16)),
                        ("Arctic",(0.61, 0.58, 0.53, 0.48)),
                        ("Flora",(0.42, 0.22, 0.15, 0.05)),
                        ("Berry", (0.95,0.88, 0.82, 0.75)),
                        ("Pride", (0.0, 0.08, 0.16, 0.33, 0.66, 0.81))
                        ]
        
        self.menu = Menu(
            self,
            menu_items,
            select_handler=self.select_handler,
            back_handler=self.back_handler,
        )
        self.notification = None

        # FFT prep
        self.num_bins = 12
        self.sample_count = 64 # Keep this small for speed!
        self.bin_maxes = [1.0] * 12

        self.angle = 0

        # Precompute Sin/Cos tables for the frequencies we care about
        self.sin_table = [math.sin(2 * math.pi * i / self.sample_count) for i in range(self.sample_count)]
        self.cos_table = [math.cos(2 * math.pi * i / self.sample_count) for i in range(self.sample_count)]

        #beat detection prep
        self.energy_history = [0.0] * 60 # Roughly 1-2 seconds of history
        self.last_beat_time = 0
        self.min_beat_interval = 300 # Minimum 300ms between beats (max ~200 BPM)
        self.last_beat_ms = time.ticks_ms()
        self.beat_interval = 500  # Start with a 120 BPM guess
        self.target_index = 6.0   # Adjust this (0-11) to define "bottom
        

        #end init
    
    def get_hue(self, distance):
        live_palette = self.palettes[self.palette][1]
        num_segments = len(live_palette) - 1

        # Ensure distance doesn't exceed 1.0
        distance = max(0, min(0.999, distance))

        scaled_dist = distance * num_segments
        index = int(math.floor(scaled_dist))  # The starting color index
        fraction = scaled_dist - index
        start_hue = live_palette[index]
        end_hue = live_palette[index + 1]
        # Simple LERP formula: start + (end - start) * fraction
        return start_hue + (end_hue - start_hue) * fraction
    
    def sample_audio(self, subsample = 1):
        num_bytes_read = self.i2s.readinto(self.buffer) # get the raw bitstream 
        if num_bytes_read <= 0: return

        samples = []
        for i in range(0, num_bytes_read, subsample * 4): # subsampling allows to to cut the number of samples
            val = struct.unpack('<i', self.buffer[i:i+4])[0] #4 bytes gives us our 32 bit word 
            samples.append(val >> 8) #bitshift since our 32 bit word only contains 24 bits of data 
        return samples
     
    def audio_RMS(self):
        samples = self.sample_audio(1)
        # 2. Find the DC offset of THIS specific block
        block_avg = sum(samples) / len(samples)
            
        # 3. Calculate RMS using centered samples
        sum_squares = 0
        for s in samples:
            centered = s - block_avg
            sum_squares += centered * centered


        #rolling volume window    
        self.rms = math.sqrt(sum_squares / len(samples))
        if self.rms < self.rmin:
            self.rmin = self.rms
        else:
            self.rmin = self.rmin / self.window_decay
        if self.rms > self.rmax:
            self.rmax = self.rms
        else:
            self.rmax = self.rmax * self.window_decay

        # Get relative position
        self.relative = (self.rms - self.rmin) / (self.rmax - self.rmin) if (self.rmax - self.rmin) > 0 else 0
        self.relative = self.relative**2

        # map this single brightness number to 12 leds:
        total_brightness = 12.0 * self.relative
        led_brightness = [0.0] * 12
        for i in range(12):
            if total_brightness >= 1:
                led_brightness[i] = 1
                total_brightness-=1
            else:
                led_brightness[i] = total_brightness
                total_brightness = 0
        #pass the led brightness to the linear led function:
        self.paint_leds_linear(led_brightness, 6)
        
    def audio_ZC(self):
        samples = self.sample_audio(4)

        avg = sum(samples) / len(samples)
        
        # Pass 2: Metrics
        sum_abs_diff = 0
        crossings = 0
        prev_sample = samples[0] - avg
        
        for s in samples:
            current_sample = s - avg
            sum_abs_diff += abs(current_sample)
            if (current_sample > 0 and prev_sample <= 0) or (current_sample < 0 and prev_sample >= 0):
                crossings += 1
            prev_sample = current_sample

        new_volume = sum_abs_diff / len(samples)
        self.delta = max(0, new_volume - self.rms) # Store as self.delta for the flash logic
        self.rms = new_volume
        
        self.pitch_factor = crossings / len(samples) 
        self.rmax = max(self.rms, self.rmax * 0.98)
        self.relative = (self.rms - self.rmin) / (self.rmax - self.rmin) if (self.rmax - self.rmin) > 0 else 0
       
        # 2. Balanced Pitch Mapping
        # Instead of hard-clamping at 1.0, we use a softer scaling.
        # We also reduce the multiplier slightly so 'normal' high pitches 
        # land around LED 10/11, leaving 12 for truly extreme frequencies.
        scaled_pitch = self.pitch_factor * 1.5
        if scaled_pitch > 0.98: scaled_pitch = 0.98 # Tiny buffer to prevent index overflow
        
        # Map to 0.0 - 11.0 range
        spawn_f = scaled_pitch * 11.0
        
        # 3. Sub-pixel Energy Injection
        current_energy = self.relative
        
        # Floor to get the first LED, Ceil/Modulo to get the second
        idx_a = int(spawn_f)
        idx_b = (idx_a + 1) % 12
        fract = spawn_f - idx_a
        
        # Proportional split
        led_brightness = [0.0] * 12
        led_brightness[idx_a] = current_energy * (1.0 - fract)
        led_brightness[idx_b] = current_energy * fract

        # 5. Draw the LEDs
        self.paint_leds_linear(led_brightness, 6)

    def audio_fft(self):
        samples = self.sample_audio(subsample=2)
        if not samples or len(samples) < self.sample_count: 
            return
        
        # --- OPTIMIZATION: Local Variable Caching ---
        # Accessing 'self' inside a tight loop is slow in MicroPython
        cos_t = self.cos_table
        sin_t = self.sin_table
        bin_m = self.bin_maxes
        sc = self.sample_count
        num_b = self.num_bins
        
        led_brightness = [0.0] * num_b

        for i in range(num_b):
            real = 0
            imag = 0
            k = i + 1 
            
            # Inner loop optimization: cache the lookup index increment
            # This is where 90% of the CPU time is spent
            for n in range(sc):
                idx = (k * n) % sc
                s_n = samples[n]
                real += s_n * cos_t[idx]
                imag -= s_n * sin_t[idx]
            
            mag = abs(real) + abs(imag)

            # Update rolling max
            current_max = max(mag, bin_m[i] * 0.99)
            bin_m[i] = current_max

            # Normalization and Contrast
            if current_max > 0:
                # Using (mag / current_max) ** 2.5
                led_brightness[i] = (mag / current_max) ** 2.5
            else:
                led_brightness[i] = 0

        self.paint_leds_linear(led_brightness, 6)

    def audio_vortex(self):
        current_time = time.ticks_ms()
        delta_ms = time.ticks_diff(current_time, self.last_beat_ms)
        
        if self.detect_beat():
            self.beat_interval = max(200, delta_ms) # Clamp to avoid crazy speeds
            self.last_beat_ms = current_time
            self.angle = self.target_index
        else:
            # 2. Predictive Drift
            rotation_progress = (12.0 / self.beat_interval) * delta_ms
            self.angle = (self.target_index + rotation_progress) % 12

        # 3. Dynamic Brightness (Volume still controls the "glow")
        samples = self.sample_audio(subsample=4)
        if samples:
            avg = sum(samples) / len(samples)
            energy = sum(abs(s - avg) for s in samples) / len(samples)
            self.rmax = max(energy, self.rmax * 0.98)
            rel = (energy / self.rmax) if self.rmax > 0 else 0
            intensity = rel ** 2
        else:
            intensity = 0.5
        # 4. Render
        led_brightness = [0.0] * 12
        center_led = int(self.angle)
        
        led_brightness[center_led] = intensity
        led_brightness[(center_led - 1) % 12] = intensity * 0.5
        led_brightness[(center_led - 2) % 12] = intensity * 0.2

        self.paint_leds_linear(led_brightness, 0)

    def paint_leds_linear(self, brightnesses, start_led = 1, saturation = 1.0):                
        if self.detect_beat():
            saturation = 0.8
        else:
            saturation = 1.0

        for i in range(12):
            h = self.get_hue(i/12.0) 

            self.led_high_levels[i] = max(self.led_high_levels[i], brightnesses[i], 0.0) # set high water mark and clamp above 0
            self.led_high_levels[i] = min(self.led_high_levels[i], 1.0) # clamp below 1

            r,g,b = hsv_to_rgb(h, saturation, self.led_high_levels[i] * self.brightness_control)
            j = (i + start_led) % 12
   
            tildagonos.leds[j+1] = (r, g, b)
            self.led_high_levels[i] = max(self.led_high_levels[i] * self.led_high_decay, 0) # decay high water mark
            
        tildagonos.leds.write()
        
    def detect_beat(self):
        current_time = time.ticks_ms()
        instant_energy = sum(self.led_high_levels)
        
        # Calculate Mean
        avg_energy = sum(self.energy_history) / len(self.energy_history)
        
        # Calculate Variance (how much the energy fluctuates)
        variance = sum((x - avg_energy) ** 2 for x in self.energy_history) / len(self.energy_history)
        std_dev = math.sqrt(variance)
        
        # Adaptive threshold: Sensitivity decreases as the music gets noisier
        # 1.0 is a base multiplier, adjusted by the variance
        dynamic_sensitivity = 1.0 + (std_dev / (avg_energy + 0.001)) 
        
        if instant_energy > (avg_energy * dynamic_sensitivity):
            if time.ticks_diff(current_time, self.last_beat_time) > self.min_beat_interval:
                self.last_beat_time = current_time
                return True

        self.energy_history.pop(0)
        self.energy_history.append(instant_energy)
        return False

    def update(self, delta):
        if not self.foregrounded: # Bring the app to the foreground on first run
            eventbus.emit(RequestForegroundPushEvent(self))
            self.foregrounded = True

        start_time = time.ticks_ms()
        budget_ms = 40 
            
        while time.ticks_diff(time.ticks_ms(), start_time) < budget_ms:
            if self.vismode == 0:
                self.audio_RMS()
            elif self.vismode == 1:
                self.audio_ZC()
            elif self.vismode == 2:
                self.audio_fft()
            elif self.vismode == 3:
                self.audio_vortex()

        self.menu.update(delta)
        if self.notification:
            self.notification.update(delta)

    def draw(self, ctx):
        """Clear screen each frame."""
        clear_background(ctx)
        self.menu.draw(ctx)
        if self.notification:
            self.notification.draw(ctx)
        return None

    def select_handler(self, item, idx):
        if item == "Vis Mode":
            self.vismode = (self.vismode + 1) % len(self.vismodes)
            self.notification = Notification(self.vismodes[self.vismode])
        if item == "Color Palette":
            self.palette = (self.palette + 1) % len(self.palettes)
            self.notification = Notification(self.palettes[self.palette][0])
        if item == "HexyHexyMic!":
            self.notification = Notification("HexyHexyMic by @GlitchEngine@Mastodon.social")
        if item == "Brightness":
            level = int(self.brightness_control * 10) + 1
            if level > 10: level = 1 # Wrap back to 10% instead of going to 0%
            self.brightness_control = level / 10
            self.notification = Notification("{}%".format(int(self.brightness_control * 100)))

    def back_handler(self):
        #self.i2s.deinit()
        self._cleanup()
        self.minimise()

    def _cleanup(self):
        #eventbus.remove(ButtonDownEvent, self._handle_buttondown, self.app)
        eventbus.emit(PatternEnable()) # disable the ambient pattern. We're going to need those LEDs!


__app_export__ = MicApp

