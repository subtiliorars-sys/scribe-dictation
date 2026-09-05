"""
Audio sound bank and activation/deactivation acoustic cues for Scribe Dictation.

Provides a rich library of synthesized in-memory audio feedback sound themes
with multi-tier access (Free/Trial, Basic, and Pro Exclusive):

- Free / Trial Tier (3 Core Sounds):
    * Classic Beep/Boop (Default)
    * Subtle Mechanical Tick
    * Soft Ambient Chime

- Basic Tier (7 Polished Sounds - includes Free):
    * Gentle Bubble / Water Droplet
    * Digital 8-Bit Chirp
    * Tactile Wooden Tap
    * Modern UI Bubble Pop

- Pro Exclusive Tier (Wide Variety - 18 Themes):
    * Vintage Cassette Tape Deck
    * Mechanical Keyboard "Thock"
    * Fighter Jet HUD / Radar Lock
    * Neural Cyber Pulse
    * Glass Crystal Chime
    * Submarine Sonar Ping
    * Studio DSLR Camera Shutter
    * Cosmic Synth Warp
    * Vintage Typewriter Carriage Bell
    * Acoustic Marimba Triad
    * Zen Tibetan Singing Bowl

Zero external WAV asset dependencies: all waveforms are procedurally synthesized
into pristine, 16-bit 44.1kHz mono WAV in-memory byte buffers for zero-latency,
zero-I/O playback.
"""

from dataclasses import dataclass
import io
import logging
import math
import os
import random
import struct
import sys
import threading
from typing import Callable, Dict, List, Optional, Tuple
import wave

from PySide6.QtCore import QSettings

ORGANIZATION = "PrivacyScribe"
APP_NAME = "Privacy Scribe"

logger = logging.getLogger(__name__)
if not logger.handlers:
    try:
        log_dir = os.path.join(
            os.environ.get("LOCALAPPDATA")
            or os.environ.get("APPDATA")
            or os.path.expanduser("~"),
            "PrivacyScribe",
        )
        os.makedirs(log_dir, exist_ok=True)
        _handler = logging.FileHandler(
            os.path.join(log_dir, "sound.log"), encoding="utf-8"
        )
        _handler.setFormatter(
            logging.Formatter("%(asctime)s %(levelname)s %(message)s")
        )
        logger.addHandler(_handler)
        logger.setLevel(logging.DEBUG)
    except Exception:
        pass
SETTINGS_PLAY_SOUNDS = "play_sounds"
SETTINGS_SOUND_THEME = "sound_theme"
SETTINGS_SOUND_VOLUME = "sound_volume"
DEFAULT_SOUND_THEME = "classic_beep"
DEFAULT_SOUND_VOLUME = 80


@dataclass(frozen=True)
class SoundTheme:
    """Representation of an audio sound theme."""

    id: str
    name: str
    description: str
    tier: str  # "free", "basic", "pro"
    is_pro: bool
    category: str  # "Free / Trial", "Basic Edition", "Pro Exclusive"


def _generate_wav(samples: List[float], sample_rate: int = 44100) -> bytes:
    """Pack floating-point audio samples (-1.0 to 1.0) into a standard 16-bit PCM WAV byte buffer."""
    buf = io.BytesIO()
    with wave.open(buf, "wb") as f:
        f.setnchannels(1)
        f.setsampwidth(2)
        f.setframerate(sample_rate)
        raw = bytearray()
        for s in samples:
            val = int(max(-1.0, min(1.0, s)) * 32767)
            raw.extend(struct.pack("<h", val))
        f.writeframes(raw)
    return buf.getvalue()


# ── Sound Synthesizers ────────────────────────────────────────────────────────


def _synth_classic_beep() -> Tuple[bytes, bytes]:
    """Classic clean sine beeps with warm presence (rising start / falling stop)."""
    sample_rate = 44100
    dur = 0.085
    n_samples = int(dur * sample_rate)

    # Start: High, cheerful 1050Hz -> 1250Hz rising confirmation beep
    start_samples = [0.0] * n_samples
    for i in range(n_samples):
        t = i / sample_rate
        attack = min(1.0, t / 0.006)
        decay = math.exp(-t * 35.0)
        freq = 1050.0 + 200.0 * (t / dur)
        start_samples[i] = math.sin(2 * math.pi * freq * t) * attack * decay * 0.85

    # Stop: Lower, warm 680Hz -> 520Hz grounding boop
    stop_samples = [0.0] * n_samples
    for i in range(n_samples):
        t = i / sample_rate
        attack = min(1.0, t / 0.006)
        decay = math.exp(-t * 32.0)
        freq = 680.0 - 160.0 * (t / dur)
        stop_samples[i] = math.sin(2 * math.pi * freq * t) * attack * decay * 0.85

    return _generate_wav(start_samples, sample_rate), _generate_wav(
        stop_samples, sample_rate
    )


def _synth_subtle_tick() -> Tuple[bytes, bytes]:
    """Ultra-clean, minimalist mechanical tick / transient tap."""
    sample_rate = 44100
    rng = random.Random(101)

    # Start: 35ms crisp 1600Hz transient click with solid mechanical presence
    dur_start = 0.035
    n_start = int(dur_start * sample_rate)
    start_samples = [0.0] * n_start
    for i in range(n_start):
        t = i / sample_rate
        env = math.exp(-t * 140.0)
        noise = (rng.random() * 2 - 1) * env * 0.35
        tone = math.sin(2 * math.pi * 1600 * t) * env * 0.65
        start_samples[i] = (noise + tone) * 0.85

    # Stop: 40ms subtle 520Hz wooden tactile tap
    dur_stop = 0.040
    n_stop = int(dur_stop * sample_rate)
    stop_samples = [0.0] * n_stop
    for i in range(n_stop):
        t = i / sample_rate
        env = math.exp(-t * 110.0)
        thud = math.sin(2 * math.pi * 520 * t) * env * 0.7
        body = math.sin(2 * math.pi * 180 * t) * env * 0.3
        stop_samples[i] = (thud + body) * 0.85

    return _generate_wav(start_samples, sample_rate), _generate_wav(
        stop_samples, sample_rate
    )


def _synth_soft_chime() -> Tuple[bytes, bytes]:
    """Soft ambient bell chime with warm harmonic decay."""
    sample_rate = 44100
    dur = 0.060
    n_samples = int(dur * sample_rate)

    # Start: 880Hz A5 + 1760Hz octave harmonic
    start_samples = [0.0] * n_samples
    for i in range(n_samples):
        t = i / sample_rate
        env = math.exp(-t * 60.0)
        h1 = math.sin(2 * math.pi * 880 * t) * 0.65
        h2 = math.sin(2 * math.pi * 1760 * t) * 0.25
        h3 = math.sin(2 * math.pi * 2640 * t) * 0.10
        start_samples[i] = (h1 + h2 + h3) * env

    # Stop: 587Hz D5 + 1174Hz harmonic
    stop_samples = [0.0] * n_samples
    for i in range(n_samples):
        t = i / sample_rate
        env = math.exp(-t * 55.0)
        h1 = math.sin(2 * math.pi * 587 * t) * 0.70
        h2 = math.sin(2 * math.pi * 1174 * t) * 0.25
        stop_samples[i] = (h1 + h2) * env

    return _generate_wav(start_samples, sample_rate), _generate_wav(
        stop_samples, sample_rate
    )


def _synth_gentle_bubble() -> Tuple[bytes, bytes]:
    """Gentle marimba / water drop frequency-modulated bubble."""
    sample_rate = 44100
    dur = 0.045
    n_samples = int(dur * sample_rate)

    # Start: Rising FM pitch 520Hz -> 1100Hz
    start_samples = [0.0] * n_samples
    for i in range(n_samples):
        t = i / sample_rate
        freq = 520.0 + 580.0 * (t / dur)
        env = math.sin(math.pi * (t / dur)) ** 1.5
        start_samples[i] = math.sin(2 * math.pi * freq * t) * env * 0.75

    # Stop: Falling FM pitch 880Hz -> 440Hz
    stop_samples = [0.0] * n_samples
    for i in range(n_samples):
        t = i / sample_rate
        freq = 880.0 - 440.0 * (t / dur)
        env = math.sin(math.pi * (t / dur)) ** 1.5
        stop_samples[i] = math.sin(2 * math.pi * freq * t) * env * 0.75

    return _generate_wav(start_samples, sample_rate), _generate_wav(
        stop_samples, sample_rate
    )


def _synth_digital_blip() -> Tuple[bytes, bytes]:
    """Retro digital 8-bit micro-arpeggio chirp."""
    sample_rate = 44100
    dur = 0.030
    n_samples = int(dur * sample_rate)
    half = n_samples // 2

    # Start: Ascending two-step chirp (988Hz B5 -> 1318Hz E6)
    start_samples = [0.0] * n_samples
    for i in range(n_samples):
        t = i / sample_rate
        freq = 988.0 if i < half else 1318.0
        env = math.exp(-((i % half) / sample_rate) * 110.0)
        start_samples[i] = math.sin(2 * math.pi * freq * t) * env * 0.6

    # Stop: Descending two-step blip (1046Hz C6 -> 659Hz E5)
    stop_samples = [0.0] * n_samples
    for i in range(n_samples):
        t = i / sample_rate
        freq = 1046.0 if i < half else 659.0
        env = math.exp(-((i % half) / sample_rate) * 110.0)
        stop_samples[i] = math.sin(2 * math.pi * freq * t) * env * 0.6

    return _generate_wav(start_samples, sample_rate), _generate_wav(
        stop_samples, sample_rate
    )


def _synth_wooden_tap() -> Tuple[bytes, bytes]:
    """Tactile organic wooden block tap."""
    sample_rate = 44100
    dur = 0.030
    n_samples = int(dur * sample_rate)
    rng = random.Random(88)

    # Start: Warm resonant 850Hz + 220Hz wood snap
    start_samples = [0.0] * n_samples
    for i in range(n_samples):
        t = i / sample_rate
        env = math.exp(-t * 260.0)
        noise = (rng.random() * 2 - 1) * env * 0.25
        h1 = math.sin(2 * math.pi * 850 * t) * 0.6
        h2 = math.sin(2 * math.pi * 220 * t) * 0.4
        start_samples[i] = (h1 + h2 + noise) * env

    # Stop: Damped 480Hz lower wooden tap
    stop_samples = [0.0] * n_samples
    for i in range(n_samples):
        t = i / sample_rate
        env = math.exp(-t * 240.0)
        h1 = math.sin(2 * math.pi * 480 * t) * 0.7
        h2 = math.sin(2 * math.pi * 140 * t) * 0.3
        stop_samples[i] = (h1 + h2) * env

    return _generate_wav(start_samples, sample_rate), _generate_wav(
        stop_samples, sample_rate
    )


def _synth_modern_pop() -> Tuple[bytes, bytes]:
    """Crisp synthetic modern UI bubble pop."""
    sample_rate = 44100
    dur = 0.025
    n_samples = int(dur * sample_rate)

    # Start: Rapid ascending glide 650Hz -> 1450Hz
    start_samples = [0.0] * n_samples
    for i in range(n_samples):
        t = i / sample_rate
        freq = 650.0 + 800.0 * (t / dur)
        env = math.sin(math.pi * (t / dur)) ** 1.8
        start_samples[i] = math.sin(2 * math.pi * freq * t) * env * 0.8

    # Stop: Downward pop 950Hz -> 380Hz
    stop_samples = [0.0] * n_samples
    for i in range(n_samples):
        t = i / sample_rate
        freq = 950.0 - 570.0 * (t / dur)
        env = math.sin(math.pi * (t / dur)) ** 1.8
        stop_samples[i] = math.sin(2 * math.pi * freq * t) * env * 0.8

    return _generate_wav(start_samples, sample_rate), _generate_wav(
        stop_samples, sample_rate
    )


# ── Pro Exclusive Synthesizers ────────────────────────────────────────────────


def _synth_tape_recorder() -> Tuple[bytes, bytes]:
    """Authentic physical vintage cassette tape deck mechanical press/release clunk."""
    sample_rate = 44100
    rng = random.Random(42)

    dur_press = 0.085
    n_press = int(dur_press * sample_rate)
    press_samples = [0.0] * n_press
    for i in range(n_press):
        t = i / sample_rate
        snap_env = math.exp(-t * 180.0)
        snap_noise = (rng.random() * 2 - 1) * snap_env * 0.45
        snap_tone = math.sin(2 * math.pi * 3400 * t) * snap_env * 0.35

        pitch = 180.0 * math.exp(-t * 25.0)
        thud_env = math.exp(-t * 38.0)
        thud = math.sin(2 * math.pi * pitch * t) * thud_env * 0.75

        case_env = math.exp(-t * 60.0)
        case_res = math.sin(2 * math.pi * 920 * t) * case_env * 0.25

        press_samples[i] = snap_noise + snap_tone + thud + case_res

    dur_rel = 0.095
    n_rel = int(dur_rel * sample_rate)
    rel_samples = [0.0] * n_rel
    for i in range(n_rel):
        t = i / sample_rate
        snap_env = math.exp(-t * 220.0)
        snap_noise = (rng.random() * 2 - 1) * snap_env * 0.5
        snap_click = math.sin(2 * math.pi * 2600 * t) * snap_env * 0.4

        clunk_env = math.exp(-t * 32.0)
        clunk_low = math.sin(2 * math.pi * 140 * t) * clunk_env * 0.65
        chassis_body = math.sin(2 * math.pi * 620 * t) * math.exp(-t * 50.0) * 0.35

        rel_samples[i] = snap_noise + snap_click + clunk_low + chassis_body

    return _generate_wav(press_samples, sample_rate), _generate_wav(
        rel_samples, sample_rate
    )


def _synth_tactile_thock() -> Tuple[bytes, bytes]:
    """Custom mechanical keyboard switch bottom-out and release thock."""
    sample_rate = 44100
    rng = random.Random(77)

    dur_press = 0.042
    n_press = int(dur_press * sample_rate)
    press_samples = [0.0] * n_press
    for i in range(n_press):
        t = i / sample_rate
        snap_env = math.exp(-t * 280.0)
        click = math.sin(2 * math.pi * 3200 * t) * snap_env * 0.4
        noise = (rng.random() * 2 - 1) * snap_env * 0.3

        thock_env = math.exp(-t * 90.0)
        thock = math.sin(2 * math.pi * 190 * t) * thock_env * 0.85
        chassis = math.sin(2 * math.pi * 450 * t) * math.exp(-t * 120.0) * 0.3

        press_samples[i] = click + noise + thock + chassis

    dur_rel = 0.038
    n_rel = int(dur_rel * sample_rate)
    rel_samples = [0.0] * n_rel
    for i in range(n_rel):
        t = i / sample_rate
        snap_env = math.exp(-t * 260.0)
        snap = math.sin(2 * math.pi * 2400 * t) * snap_env * 0.5
        upstroke = math.sin(2 * math.pi * 280 * t) * math.exp(-t * 110.0) * 0.65
        rel_samples[i] = snap + upstroke

    return _generate_wav(press_samples, sample_rate), _generate_wav(
        rel_samples, sample_rate
    )


def _synth_fighter_hud() -> Tuple[bytes, bytes]:
    """Fighter jet cockpit tactical HUD radar lock chirps."""
    sample_rate = 44100

    dur_start = 0.042
    n_start = int(dur_start * sample_rate)
    start_samples = [0.0] * n_start
    p1_end = int(0.014 * sample_rate)
    p2_start = int(0.022 * sample_rate)
    p2_end = int(0.038 * sample_rate)

    for i in range(n_start):
        t = i / sample_rate
        if i < p1_end:
            local_t = t
            env = math.sin(math.pi * (local_t / 0.014)) ** 1.2
            start_samples[i] = math.sin(2 * math.pi * 2600 * t) * env * 0.7
        elif p2_start <= i < p2_end:
            local_t = (i - p2_start) / sample_rate
            env = math.sin(math.pi * (local_t / 0.016)) ** 1.2
            start_samples[i] = math.sin(2 * math.pi * 3300 * t) * env * 0.75

    dur_stop = 0.040
    n_stop = int(dur_stop * sample_rate)
    stop_samples = [0.0] * n_stop
    for i in range(n_stop):
        t = i / sample_rate
        env = math.exp(-t * 70.0)
        h1 = math.sin(2 * math.pi * 320 * t) * 0.75
        h3 = math.sin(2 * math.pi * 960 * t) * 0.25
        stop_samples[i] = (h1 + h3) * env

    return _generate_wav(start_samples, sample_rate), _generate_wav(
        stop_samples, sample_rate
    )


def _synth_sci_fi_pulse() -> Tuple[bytes, bytes]:
    """Futuristic neural cyber upward sweep and bass downward pulse."""
    sample_rate = 44100
    dur = 0.060
    n_samples = int(dur * sample_rate)

    start_samples = [0.0] * n_samples
    for i in range(n_samples):
        t = i / sample_rate
        freq = 380.0 * math.exp(t * 32.0)
        env = math.sin(math.pi * (t / dur)) ** 1.2
        c1 = math.sin(2 * math.pi * freq * t) * 0.6
        c2 = math.sin(2 * math.pi * (freq * 1.02) * t) * 0.2
        start_samples[i] = (c1 + c2) * env

    stop_samples = [0.0] * n_samples
    for i in range(n_samples):
        t = i / sample_rate
        freq = 2400.0 * math.exp(-t * 34.0)
        env = math.sin(math.pi * (t / dur)) ** 1.2
        c1 = math.sin(2 * math.pi * freq * t) * 0.65
        sub = math.sin(2 * math.pi * 120 * t) * math.exp(-t * 40.0) * 0.35
        stop_samples[i] = (c1 + sub) * env

    return _generate_wav(start_samples, sample_rate), _generate_wav(
        stop_samples, sample_rate
    )


def _synth_crystal_bell() -> Tuple[bytes, bytes]:
    """Crystalline glass bell chord with shimmering decay."""
    sample_rate = 44100
    dur = 0.085
    n_samples = int(dur * sample_rate)

    start_samples = [0.0] * n_samples
    for i in range(n_samples):
        t = i / sample_rate
        env = math.exp(-t * 45.0)
        b1 = math.sin(2 * math.pi * 1760 * t) * 0.55
        b2 = math.sin(2 * math.pi * 2637 * t) * 0.35
        b3 = math.sin(2 * math.pi * 3520 * t) * 0.15
        start_samples[i] = (b1 + b2 + b3) * env

    stop_samples = [0.0] * n_samples
    for i in range(n_samples):
        t = i / sample_rate
        env = math.exp(-t * 40.0)
        b1 = math.sin(2 * math.pi * 1174 * t) * 0.60
        b2 = math.sin(2 * math.pi * 1480 * t) * 0.35
        stop_samples[i] = (b1 + b2) * env

    return _generate_wav(start_samples, sample_rate), _generate_wav(
        stop_samples, sample_rate
    )


def _synth_sonar_ping() -> Tuple[bytes, bytes]:
    """Acoustic naval submarine sonar ping and hull echo return."""
    sample_rate = 44100
    dur = 0.080
    n_samples = int(dur * sample_rate)

    start_samples = [0.0] * n_samples
    for i in range(n_samples):
        t = i / sample_rate
        attack = min(1.0, t / 0.003)
        decay = math.exp(-t * 38.0)
        tone = math.sin(2 * math.pi * 1450 * t) * 0.75
        harm = math.sin(2 * math.pi * 2900 * t) * 0.15
        start_samples[i] = (tone + harm) * attack * decay

    dur_stop = 0.075
    n_stop = int(dur_stop * sample_rate)
    stop_samples = [0.0] * n_stop
    for i in range(n_stop):
        t = i / sample_rate
        attack = min(1.0, t / 0.004)
        decay = math.exp(-t * 42.0)
        tone = math.sin(2 * math.pi * 380 * t) * 0.8
        stop_samples[i] = tone * attack * decay

    return _generate_wav(start_samples, sample_rate), _generate_wav(
        stop_samples, sample_rate
    )


def _synth_camera_shutter() -> Tuple[bytes, bytes]:
    """Studio DSLR camera mechanical shutter snap and mirror return."""
    sample_rate = 44100
    rng = random.Random(99)

    dur_start = 0.042
    n_start = int(dur_start * sample_rate)
    start_samples = [0.0] * n_start
    for i in range(n_start):
        t = i / sample_rate
        env = math.exp(-t * 190.0)
        noise = (rng.random() * 2 - 1) * env * 0.45
        mirror = math.sin(2 * math.pi * 220 * t) * math.exp(-t * 80.0) * 0.6
        blade = math.sin(2 * math.pi * 3600 * t) * env * 0.35
        start_samples[i] = noise + mirror + blade

    dur_stop = 0.045
    n_stop = int(dur_stop * sample_rate)
    stop_samples = [0.0] * n_stop
    for i in range(n_stop):
        t = i / sample_rate
        env = math.exp(-t * 170.0)
        noise = (rng.random() * 2 - 1) * env * 0.4
        clack = math.sin(2 * math.pi * 180 * t) * math.exp(-t * 70.0) * 0.65
        spring = math.sin(2 * math.pi * 2800 * t) * env * 0.3
        stop_samples[i] = noise + clack + spring

    return _generate_wav(start_samples, sample_rate), _generate_wav(
        stop_samples, sample_rate
    )


def _synth_cosmic_warp() -> Tuple[bytes, bytes]:
    """Cosmic analog synthesizer resonant warp sweep."""
    sample_rate = 44100
    dur = 0.070
    n_samples = int(dur * sample_rate)

    # Start: Resonant upward filter sweep (240Hz -> 1800Hz with detuned sub)
    start_samples = [0.0] * n_samples
    for i in range(n_samples):
        t = i / sample_rate
        f_main = 240.0 * math.exp(t * 28.0)
        env = math.sin(math.pi * (t / dur)) ** 1.3
        osc1 = math.sin(2 * math.pi * f_main * t) * 0.6
        osc2 = math.sin(2 * math.pi * (f_main * 1.5) * t) * 0.25
        start_samples[i] = (osc1 + osc2) * env

    # Stop: Downward cosmic resonance drop
    stop_samples = [0.0] * n_samples
    for i in range(n_samples):
        t = i / sample_rate
        f_main = 1600.0 * math.exp(-t * 36.0)
        env = math.sin(math.pi * (t / dur)) ** 1.3
        osc1 = math.sin(2 * math.pi * f_main * t) * 0.65
        sub = math.sin(2 * math.pi * 110 * t) * math.exp(-t * 30.0) * 0.3
        stop_samples[i] = (osc1 + sub) * env

    return _generate_wav(start_samples, sample_rate), _generate_wav(
        stop_samples, sample_rate
    )


def _synth_typewriter_bell() -> Tuple[bytes, bytes]:
    """Vintage mechanical typewriter key click and carriage return bell ding."""
    sample_rate = 44100
    rng = random.Random(65)

    # Start: Heavy typewriter key strike (metallic snap + typebar thud)
    dur_start = 0.045
    n_start = int(dur_start * sample_rate)
    start_samples = [0.0] * n_start
    for i in range(n_start):
        t = i / sample_rate
        snap_env = math.exp(-t * 250.0)
        snap = (rng.random() * 2 - 1) * snap_env * 0.4
        metal = math.sin(2 * math.pi * 3200 * t) * snap_env * 0.45
        thud = math.sin(2 * math.pi * 210 * t) * math.exp(-t * 80.0) * 0.65
        start_samples[i] = snap + metal + thud

    # Stop: Bright carriage return silver bell ding (2793Hz F7 + 5587Hz)
    dur_stop = 0.090
    n_stop = int(dur_stop * sample_rate)
    stop_samples = [0.0] * n_stop
    for i in range(n_stop):
        t = i / sample_rate
        env = math.exp(-t * 38.0)
        b1 = math.sin(2 * math.pi * 2793 * t) * 0.7
        b2 = math.sin(2 * math.pi * 5587 * t) * 0.3
        stop_samples[i] = (b1 + b2) * env

    return _generate_wav(start_samples, sample_rate), _generate_wav(
        stop_samples, sample_rate
    )


def _synth_marimba_chord() -> Tuple[bytes, bytes]:
    """Warm acoustic marimba felt mallet chord."""
    sample_rate = 44100
    dur = 0.075
    n_samples = int(dur * sample_rate)

    # Start: C5 Major Triad (523Hz C5, 659Hz E5, 784Hz G5)
    start_samples = [0.0] * n_samples
    for i in range(n_samples):
        t = i / sample_rate
        env = math.exp(-t * 50.0)
        n1 = math.sin(2 * math.pi * 523.25 * t) * 0.50
        n2 = math.sin(2 * math.pi * 659.25 * t) * 0.35
        n3 = math.sin(2 * math.pi * 783.99 * t) * 0.25
        start_samples[i] = (n1 + n2 + n3) * env

    # Stop: Warm interval (440Hz A4, 523Hz C5)
    stop_samples = [0.0] * n_samples
    for i in range(n_samples):
        t = i / sample_rate
        env = math.exp(-t * 45.0)
        n1 = math.sin(2 * math.pi * 440.0 * t) * 0.60
        n2 = math.sin(2 * math.pi * 523.25 * t) * 0.40
        stop_samples[i] = (n1 + n2) * env

    return _generate_wav(start_samples, sample_rate), _generate_wav(
        stop_samples, sample_rate
    )


def _synth_zen_bowl() -> Tuple[bytes, bytes]:
    """Meditative Tibetan singing bowl harmonic shimmer."""
    sample_rate = 44100
    dur = 0.095
    n_samples = int(dur * sample_rate)

    # Start: 432Hz healing harmonic + 864Hz octave
    start_samples = [0.0] * n_samples
    for i in range(n_samples):
        t = i / sample_rate
        attack = min(1.0, t / 0.005)
        decay = math.exp(-t * 30.0)
        f1 = math.sin(2 * math.pi * 432.0 * t) * 0.65
        f2 = math.sin(2 * math.pi * 864.0 * t) * 0.25
        f3 = math.sin(2 * math.pi * 1296.0 * t) * 0.10
        start_samples[i] = (f1 + f2 + f3) * attack * decay

    # Stop: 324Hz deep bowl grounding tone
    stop_samples = [0.0] * n_samples
    for i in range(n_samples):
        t = i / sample_rate
        attack = min(1.0, t / 0.005)
        decay = math.exp(-t * 32.0)
        f1 = math.sin(2 * math.pi * 324.0 * t) * 0.75
        f2 = math.sin(2 * math.pi * 648.0 * t) * 0.25
        stop_samples[i] = (f1 + f2) * attack * decay

    return _generate_wav(start_samples, sample_rate), _generate_wav(
        stop_samples, sample_rate
    )


# ── Sound Registry & Theme Mapping ───────────────────────────────────────────

THEME_SYNTHESIZERS: Dict[str, Callable[[], Tuple[bytes, bytes]]] = {
    # Free / Trial Tier (3 Themes)
    "classic_beep": _synth_classic_beep,
    "subtle_tick": _synth_subtle_tick,
    "soft_chime": _synth_soft_chime,
    # Basic Tier (4 Additional Themes = 7 Total)
    "gentle_bubble": _synth_gentle_bubble,
    "digital_blip": _synth_digital_blip,
    "wooden_tap": _synth_wooden_tap,
    "modern_pop": _synth_modern_pop,
    # Pro Exclusive Tier (11 Additional Themes = 18 Total)
    "tape_recorder": _synth_tape_recorder,
    "tactile_thock": _synth_tactile_thock,
    "fighter_hud": _synth_fighter_hud,
    "sci_fi_pulse": _synth_sci_fi_pulse,
    "crystal_bell": _synth_crystal_bell,
    "sonar_ping": _synth_sonar_ping,
    "camera_shutter": _synth_camera_shutter,
    "cosmic_warp": _synth_cosmic_warp,
    "typewriter_bell": _synth_typewriter_bell,
    "marimba_chord": _synth_marimba_chord,
    "zen_bowl": _synth_zen_bowl,
}

SOUND_THEMES: Dict[str, SoundTheme] = {
    # ── Free / Trial Tier Themes (3 Core) ──
    "classic_beep": SoundTheme(
        id="classic_beep",
        name="Classic Beep & Boop",
        description="Clean 1200Hz / 850Hz dual-frequency audio tone bursts.",
        tier="free",
        is_pro=False,
        category="Free / Trial",
    ),
    "subtle_tick": SoundTheme(
        id="subtle_tick",
        name="Subtle Mechanical Tick",
        description="Minimalist 1800Hz transient click and gentle wooden tap.",
        tier="free",
        is_pro=False,
        category="Free / Trial",
    ),
    "soft_chime": SoundTheme(
        id="soft_chime",
        name="Soft Ambient Chime",
        description="Gentle harmonic bell chime with warm acoustic decay.",
        tier="free",
        is_pro=False,
        category="Free / Trial",
    ),
    # ── Basic Tier Themes (7 Total) ──
    "gentle_bubble": SoundTheme(
        id="gentle_bubble",
        name="Gentle Bubble",
        description="Frequency-modulated rising and falling resonant water droplet.",
        tier="basic",
        is_pro=False,
        category="Basic Edition",
    ),
    "digital_blip": SoundTheme(
        id="digital_blip",
        name="Digital 8-Bit Chirp",
        description="Two-tone ascending and descending retro micro-arpeggios.",
        tier="basic",
        is_pro=False,
        category="Basic Edition",
    ),
    "wooden_tap": SoundTheme(
        id="wooden_tap",
        name="Tactile Wooden Tap",
        description="Warm organic wood block transient click and body resonance.",
        tier="basic",
        is_pro=False,
        category="Basic Edition",
    ),
    "modern_pop": SoundTheme(
        id="modern_pop",
        name="Modern UI Bubble Pop",
        description="Crisp synthetic interface pop and glide tone.",
        tier="basic",
        is_pro=False,
        category="Basic Edition",
    ),
    # ── Pro Exclusive Tier Themes (18 Total) ──
    "tape_recorder": SoundTheme(
        id="tape_recorder",
        name="Vintage Cassette Tape Deck",
        description="Tactile solenoid head clamp latch and spring unlock clunk.",
        tier="pro",
        is_pro=True,
        category="Pro Exclusive",
    ),
    "tactile_thock": SoundTheme(
        id="tactile_thock",
        name="Mechanical Keyboard 'Thock'",
        description="Premium tactile switch bottom-out snap and housing resonance.",
        tier="pro",
        is_pro=True,
        category="Pro Exclusive",
    ),
    "fighter_hud": SoundTheme(
        id="fighter_hud",
        name="Fighter Jet HUD Radar Lock",
        description="Twin tactical supersonic lock chirps and confirmation lock tone.",
        tier="pro",
        is_pro=True,
        category="Pro Exclusive",
    ),
    "sci_fi_pulse": SoundTheme(
        id="sci_fi_pulse",
        name="Neural Cyber Pulse",
        description="Futuristic upward laser sweep and downward plasma sub-bass warp.",
        tier="pro",
        is_pro=True,
        category="Pro Exclusive",
    ),
    "crystal_bell": SoundTheme(
        id="crystal_bell",
        name="Glass Crystal Chime",
        description="Crystalline dual bell chord and resonant singing bowl decay.",
        tier="pro",
        is_pro=True,
        category="Pro Exclusive",
    ),
    "sonar_ping": SoundTheme(
        id="sonar_ping",
        name="Submarine Sonar Ping",
        description="1450Hz acoustic naval sonar carrier ping and hull echo return.",
        tier="pro",
        is_pro=True,
        category="Pro Exclusive",
    ),
    "camera_shutter": SoundTheme(
        id="camera_shutter",
        name="Studio DSLR Camera Shutter",
        description="Mechanical reflex mirror slap and focal curtain reset clack.",
        tier="pro",
        is_pro=True,
        category="Pro Exclusive",
    ),
    "cosmic_warp": SoundTheme(
        id="cosmic_warp",
        name="Cosmic Synth Warp",
        description="Analog synthesizer resonant upward sweep and deep sub drop.",
        tier="pro",
        is_pro=True,
        category="Pro Exclusive",
    ),
    "typewriter_bell": SoundTheme(
        id="typewriter_bell",
        name="Vintage Typewriter Carriage Bell",
        description="Heavy mechanical key strike and silver carriage return bell.",
        tier="pro",
        is_pro=True,
        category="Pro Exclusive",
    ),
    "marimba_chord": SoundTheme(
        id="marimba_chord",
        name="Acoustic Marimba Triad",
        description="Warm wooden felt mallet C-major chord and acoustic interval.",
        tier="pro",
        is_pro=True,
        category="Pro Exclusive",
    ),
    "zen_bowl": SoundTheme(
        id="zen_bowl",
        name="Zen Tibetan Singing Bowl",
        description="432Hz healing harmonic shimmer and deep grounding tone.",
        tier="pro",
        is_pro=True,
        category="Pro Exclusive",
    ),
}

FREE_SOUND_THEMES: List[str] = [k for k, v in SOUND_THEMES.items() if v.tier == "free"]
BASIC_SOUND_THEMES: List[str] = [
    k for k, v in SOUND_THEMES.items() if v.tier in ("free", "basic")
]
PRO_SOUND_THEMES: List[str] = list(SOUND_THEMES.keys())

# In-memory WAV cache: Dict[theme_id, (start_wav_bytes, stop_wav_bytes)]
_SOUND_CACHE: Dict[str, Tuple[bytes, bytes]] = {}
_CACHE_LOCK = threading.Lock()


def get_sound_theme(theme_id: str) -> Optional[SoundTheme]:
    """Retrieve metadata for a sound theme by ID."""
    return SOUND_THEMES.get(theme_id)


def list_sound_themes() -> List[SoundTheme]:
    """Return all registered sound themes."""
    return list(SOUND_THEMES.values())


def get_sound_themes_for_tier(tier: str = "pro") -> List[SoundTheme]:
    """Return sound themes accessible for the specified licensing tier ('free', 'basic', 'pro')."""
    tier_lower = tier.lower()
    if tier_lower == "free":
        return [v for v in SOUND_THEMES.values() if v.tier == "free"]
    elif tier_lower == "basic":
        return [v for v in SOUND_THEMES.values() if v.tier in ("free", "basic")]
    return list(SOUND_THEMES.values())


def get_theme_wav_buffers(theme_id: str) -> Tuple[bytes, bytes]:
    """Get the cached (start_wav, stop_wav) byte buffers for a given theme, synthesizing on demand."""
    if theme_id not in SOUND_THEMES:
        theme_id = DEFAULT_SOUND_THEME

    with _CACHE_LOCK:
        if theme_id not in _SOUND_CACHE:
            synth_fn = THEME_SYNTHESIZERS.get(theme_id, _synth_classic_beep)
            _SOUND_CACHE[theme_id] = synth_fn()
        return _SOUND_CACHE[theme_id]


# ── Audio Playback Engine ─────────────────────────────────────────────────────


def _apply_volume(wav_bytes: bytes, volume_percent: int) -> bytes:
    """Scale the 16-bit PCM WAV samples by a volume percentage (0-100)."""
    if volume_percent >= 100:
        return wav_bytes
    if volume_percent <= 0:
        return b""

    factor = volume_percent / 100.0
    try:
        in_buf = io.BytesIO(wav_bytes)
        with wave.open(in_buf, "rb") as r:
            n_channels = r.getnchannels()
            sampwidth = r.getsampwidth()
            framerate = r.getframerate()
            n_frames = r.getnframes()
            raw_frames = r.readframes(n_frames)

        if sampwidth != 2:
            return wav_bytes

        count = len(raw_frames) // 2
        samples = struct.unpack(f"<{count}h", raw_frames)
        scaled = [int(max(-32768, min(32767, s * factor))) for s in samples]
        new_frames = struct.pack(f"<{count}h", *scaled)

        out_buf = io.BytesIO()
        with wave.open(out_buf, "wb") as w:
            w.setnchannels(n_channels)
            w.setsampwidth(sampwidth)
            w.setframerate(framerate)
            w.writeframes(new_frames)
        return out_buf.getvalue()
    except Exception:
        return wav_bytes


def _play_wav_buffer_win32(wav_bytes: bytes):
    """Play WAV buffer on Windows via winsound PlaySound.

    winsound.PlaySound raises RuntimeError if SND_MEMORY is combined with
    SND_ASYNC (CPython refuses this because the buffer could be garbage
    collected while Windows is still playing from it asynchronously). Play
    synchronously instead, off the calling thread, so the GUI never blocks
    and the buffer stays alive for the duration of playback.
    """

    def _blocking_play():
        try:
            import winsound

            flags = winsound.SND_MEMORY | winsound.SND_NODEFAULT
            winsound.PlaySound(wav_bytes, flags)
        except Exception:
            logger.exception(
                "winsound.PlaySound(SND_MEMORY) failed, falling back to Beep"
            )
            try:
                import winsound

                winsound.Beep(1000, 30)
            except Exception:
                logger.exception("winsound.Beep fallback also failed")

    threading.Thread(target=_blocking_play, daemon=True).start()


def _get_sounddevice_output_target() -> Tuple[Optional[int], int]:
    """Find the optimal output device and native hardware sample rate for low-latency playback."""
    try:
        import sounddevice as sd

        # 1. On Windows, explicitly prioritize WASAPI then DirectSound over legacy MME
        if sys.platform == "win32":
            for h in sd.query_hostapis():
                if (
                    "WASAPI" in h.get("name", "")
                    and h.get("default_output_device", -1) >= 0
                ):
                    dev_idx = h["default_output_device"]
                    info = sd.query_devices(dev_idx)
                    if info.get("max_output_channels", 0) > 0:
                        return dev_idx, int(info.get("default_samplerate", 44100))

            for h in sd.query_hostapis():
                if (
                    "DirectSound" in h.get("name", "")
                    and h.get("default_output_device", -1) >= 0
                ):
                    dev_idx = h["default_output_device"]
                    info = sd.query_devices(dev_idx)
                    if info.get("max_output_channels", 0) > 0:
                        return dev_idx, int(info.get("default_samplerate", 44100))

        # 2. Standard default output device (macOS CoreAudio, Linux ALSA/Pulse, or default)
        default_out = sd.default.device[1]
        if default_out is not None and default_out >= 0:
            info = sd.query_devices(default_out)
            return default_out, int(info.get("default_samplerate", 44100))
    except Exception:
        pass
    return None, 44100


def _play_wav_buffer_sounddevice(wav_bytes: bytes) -> bool:
    """Attempt playback using sounddevice (WASAPI/DirectSound/CoreAudio/Pulse).

    Upmixes mono to stereo so modern multi-channel surround topologies
    (Nahimic, SteelSeries Sonar, Realtek 7.1) do not drop or isolate the signal.
    Resamples to the device's native hardware sample rate (e.g. 48kHz on Windows Realtek)
    so WASAPI shared-mode streams are accepted without PaErrorCode -9997.
    Prepends a 25ms silence ramp so hardware DACs in power-saving mode have time
    to wake up and do not swallow short transient clicks.
    """
    try:
        import sounddevice as sd
        import numpy as np

        with wave.open(io.BytesIO(wav_bytes), "rb") as w:
            src_sr = w.getframerate()
            n_channels = w.getnchannels()
            frames = w.readframes(w.getnframes())

        samples = np.frombuffer(frames, dtype=np.int16).astype(np.float32) / 32768.0

        dev_idx, target_sr = _get_sounddevice_output_target()

        # Resample if device native rate differs from WAV source rate (e.g. 44.1k -> 48k)
        if target_sr > 0 and target_sr != src_sr:
            num_out = int(len(samples) * target_sr / src_sr)
            if num_out > 0:
                samples = np.interp(
                    np.linspace(0, len(samples), num_out, endpoint=False),
                    np.arange(len(samples)),
                    samples,
                )
            play_sr = target_sr
        else:
            play_sr = src_sr

        if n_channels == 1:
            samples = np.column_stack([samples, samples])

        pad_len = int(0.025 * play_sr)
        silence = np.zeros((pad_len, 2), dtype=np.float32)
        samples = np.vstack([silence, samples])

        def _worker():
            try:
                sd.play(samples, play_sr, device=dev_idx, blocking=True)
            except Exception as exc:
                logger.debug("sounddevice worker playback failed: %s", exc)

        threading.Thread(target=_worker, daemon=True).start()
        return True
    except Exception as exc:
        logger.debug("sounddevice playback skipped or failed (%s)", exc)
        return False


def _play_wav_buffer_crossplatform(wav_bytes: bytes):
    """Play WAV buffer across Windows / macOS / Linux."""
    # 1. Preferred path: sounddevice (high fidelity, low latency, stereo upmix)
    if _play_wav_buffer_sounddevice(wav_bytes):
        return

    if sys.platform == "win32":
        _play_wav_buffer_win32(wav_bytes)
        return

    try:
        import tempfile
        import subprocess

        def _bg_play():
            with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
                f.write(wav_bytes)
                temp_name = f.name
            try:
                if sys.platform == "darwin":
                    subprocess.run(
                        ["afplay", temp_name],
                        check=False,
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                    )
                else:
                    subprocess.run(
                        ["aplay", "-q", temp_name],
                        check=False,
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                    )
            finally:
                try:
                    os.unlink(temp_name)
                except Exception:
                    pass

        threading.Thread(target=_bg_play, daemon=True).start()
    except Exception:
        pass


def play_sound(
    start: bool,
    theme_id: Optional[str] = None,
    tier: Optional[str] = None,
    is_pro: Optional[bool] = None,
    volume: Optional[int] = None,
):
    """
    Play the activation (start=True) or deactivation (start=False) sound.

    Respects SETTINGS_PLAY_SOUNDS and SETTINGS_SOUND_THEME from QSettings.
    Enforces tier gating: users attempting to play sounds beyond their tier
    are safely redirected to DEFAULT_SOUND_THEME (classic_beep).
    """
    try:
        settings = QSettings(ORGANIZATION, APP_NAME)
        val = settings.value(SETTINGS_PLAY_SOUNDS, True)
        if isinstance(val, str) and val.lower() in ("false", "0"):
            return
        elif isinstance(val, bool) and not val:
            return

        if volume is None:
            try:
                volume = int(
                    settings.value(SETTINGS_SOUND_VOLUME, DEFAULT_SOUND_VOLUME)
                )
            except (ValueError, TypeError):
                volume = DEFAULT_SOUND_VOLUME

        if not theme_id:
            theme_id = str(settings.value(SETTINGS_SOUND_THEME, DEFAULT_SOUND_THEME))

        theme_obj = SOUND_THEMES.get(theme_id)
        if not theme_obj:
            theme_id = DEFAULT_SOUND_THEME
            theme_obj = SOUND_THEMES[DEFAULT_SOUND_THEME]

        # Determine effective user tier
        if tier is None:
            if is_pro is None:
                from scribe_dictation.licensing import is_offline_cache_valid

                is_pro = is_offline_cache_valid()
            tier = "pro" if is_pro else "free"

        tier = tier.lower()
        if tier == "free" and theme_id not in FREE_SOUND_THEMES:
            theme_id = DEFAULT_SOUND_THEME
        elif tier == "basic" and theme_id not in BASIC_SOUND_THEMES:
            theme_id = DEFAULT_SOUND_THEME

        start_wav, stop_wav = get_theme_wav_buffers(theme_id)
        target_wav = start_wav if start else stop_wav

        target_wav = _apply_volume(target_wav, volume)
        if not target_wav:
            return

        logger.debug("play_sound start=%s theme=%s volume=%s", start, theme_id, volume)
        _play_wav_buffer_crossplatform(target_wav)
    except Exception:
        logger.exception("Failed to play sound (%s)", theme_id)


def preview_sound(theme_id: str, start: bool = True, volume: Optional[int] = None):
    """Directly preview a sound theme (for settings dialog auditioning)."""
    try:
        if theme_id not in SOUND_THEMES:
            theme_id = DEFAULT_SOUND_THEME
        start_wav, stop_wav = get_theme_wav_buffers(theme_id)
        target_wav = start_wav if start else stop_wav

        if volume is None:
            settings = QSettings(ORGANIZATION, APP_NAME)
            try:
                volume = int(
                    settings.value(SETTINGS_SOUND_VOLUME, DEFAULT_SOUND_VOLUME)
                )
            except (ValueError, TypeError):
                volume = DEFAULT_SOUND_VOLUME

        target_wav = _apply_volume(target_wav, volume)
        if not target_wav:
            return

        logger.debug(
            "preview_sound start=%s theme=%s volume=%s", start, theme_id, volume
        )
        _play_wav_buffer_crossplatform(target_wav)
    except Exception:
        logger.exception("Failed to preview sound (%s)", theme_id)


__all__ = [
    "SoundTheme",
    "SOUND_THEMES",
    "FREE_SOUND_THEMES",
    "BASIC_SOUND_THEMES",
    "PRO_SOUND_THEMES",
    "DEFAULT_SOUND_THEME",
    "DEFAULT_SOUND_VOLUME",
    "SETTINGS_SOUND_THEME",
    "SETTINGS_SOUND_VOLUME",
    "SETTINGS_PLAY_SOUNDS",
    "get_sound_theme",
    "list_sound_themes",
    "get_sound_themes_for_tier",
    "get_theme_wav_buffers",
    "play_sound",
    "preview_sound",
]
