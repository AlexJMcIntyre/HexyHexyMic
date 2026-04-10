import app
import struct
import math
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
    "Color Palette"]

class MicApp(app.App):
    def __init__(self, config=None):
        eventbus.emit(PatternDisable()) # disable the ambient pattern. We're going to need those LEDs!
        self.hexpansion_config = config
        self.foregrounded = False

        self.buffersize = 1024 * 4

        self.rms = 0.0 # current rms volume
        self.rmin = 1.0 # rolling minimum
        self.rmax = 10.0 # rolling maximum
        self.relative = 0.1 # relative volume
        self.window_decay = 0.99 # how quickly the rolling min and max adjust to changes in volume. Closer to 1 is slower decay, closer to 0 is faster decay
        self.led_decay = 0.3 # high water mark decay
        self.brightness_control = 0.5
        self.led_levels = [0.0] * 12  # Current level for each LED

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
    
                
        self.vismode = 0
        self.vismodes = ["RMS", "ZC", "FFT"]
        self.palette = 0   
        self.palettes = [("Neon",(0.78,0.85,0.52)),
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

        # Precompute Sin/Cos tables for the frequencies we care about
        self.sin_table = [math.sin(2 * math.pi * i / self.sample_count) for i in range(self.sample_count)]
        self.cos_table = [math.cos(2 * math.pi * i / self.sample_count) for i in range(self.sample_count)]

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

        total_brightness = 12.0 * self.relative
        
        for i in range(12):
            if total_brightness >= 1:
                led_brightness = 1
                total_brightness-=1
            else:
                led_brightness = total_brightness
                total_brightness = 0
            #print(self.led_levels[i],led_brightness)
            self.led_levels[i] = max(self.led_levels[i],led_brightness) # set high water mark
            
            h = self.get_hue(i/12.0)            
            r,g,b = hsv_to_rgb(h, 1.0, self.led_levels[i] * self.brightness_control)
            
            #tildagonos.leds[led] = (0,int(self.led_levels[i]*255), int(self.led_levels[i]*255)) # paint leds
            j = (i+6)%12
            tildagonos.leds[j+1] = (r, g, b)
            
            self.led_levels[i] = max(self.led_levels[i] * self.led_decay, 0) # decay high water mark
            
        tildagonos.leds.write()
        
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
        scaled_pitch = self.pitch_factor * 2.5
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
        self.led_levels[idx_a] = max(self.led_levels[idx_a], current_energy * (1.0 - fract))
        self.led_levels[idx_b] = max(self.led_levels[idx_b], current_energy * fract)

        # 5. Draw the LEDs
        for i in range(12):
            h = self.get_hue(i/12.0)  
            val = self.led_levels[i] * self.brightness_control
            
            # # Impact White-flash logic
            sat = 1.0
            # if hasattr(self, 'delta') and self.delta > (self.rmax * 0.2):
            #     sat = 0.6
            #     val = min(1.0, val + 0.2)

            r, g, b = hsv_to_rgb(h, sat, val)
            j = (i+6)%12
            tildagonos.leds[j+1] = (r, g, b)
            
            # 6. Decay (using your preferred 0.5 value)
            self.led_levels[i] *= 0.75
            if self.led_levels[i] < 0.01: self.led_levels[i] = 0

        tildagonos.leds.write()
    
    def audio_fft(self):
        samples = self.sample_audio(subsample=2) # Lower resolution for speed
        if not samples or len(samples) < self.sample_count: return
        
        # We only analyze the first few 'k' harmonics to map to LEDs
        for i in range(self.num_bins):
            real = 0
            imag = 0
            k = i + 1 # Target frequency harmonic
            
            for n in range(self.sample_count):
                # Optimized lookup index
                idx = (k * n) % self.sample_count
                real += samples[n] * self.cos_table[idx]
                imag -= samples[n] * self.sin_table[idx]
            
            # Magnitude approximation (faster than sqrt)
            mag = abs(real) + abs(imag)

            #per-bin rolling max
            self.bin_maxes[i] = max(mag, self.bin_maxes[i] * 0.99)

            # 2. Normalize 0.0 to 1.0 based on the rolling max
            if self.bin_maxes[i] > 0:
                normalized = mag / self.bin_maxes[i]
            else:
                normalized = 0

            contrast_val = normalized ** 2.5
            
            # Update level and clamp
            self.led_levels[i] = max(self.led_levels[i], contrast_val)
            self.led_levels[i] = min(1.0, self.led_levels[i])

            h = self.get_hue(i/12.0)            

            #clamp led_level
            v = self.led_levels[i] * self.brightness_control
            r,g,b = hsv_to_rgb(h, 1.0, v)
            
            j = (i + 6) % 12
            tildagonos.leds[j+1] = (r, g, b)
            
            self.led_levels[i] = max(self.led_levels[i] * self.led_decay, 0) # decay high water mark
            
        tildagonos.leds.write()
        
                        
                    

    def update(self, delta):
        if not self.foregrounded: # Bring the app to the foreground on first run
            eventbus.emit(RequestForegroundPushEvent(self))
            self.foregrounded = True
            
        """Update LEDs with gradual lighting and trailing effect."""

        if self.vismode == 0:
            self.audio_RMS()
        elif self.vismode == 1:
            self.audio_ZC()
        elif self.vismode == 2:
            self.audio_fft()
        

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


    def back_handler(self):
        self._cleanup()
        #self.i2s.deinit()
        self.minimise()




    def _cleanup(self):
        #eventbus.remove(ButtonDownEvent, self._handle_buttondown, self.app)
        eventbus.emit(PatternEnable()) # disable the ambient pattern. We're going to need those LEDs!



__app_export__ = MicApp

