#!/usr/bin/env python3
"""
promo_music.py — synthesise the original background bed for the promo tour.

    python scripts/promo_music.py                  # -> promo/audio/tour_theme.wav
    python scripts/promo_music.py --seconds 32 --out promo/audio/short_bed.wav

WHY GENERATE IT. A promo video needs music that is safe to post. Library tracks
carry attribution terms, "royalty-free" rarely means claim-free, and a Content ID
match mutes the video or strikes the account — on the one asset the launch is
built around. This is synthesised from scratch, so it is ours outright: no
licence, no attribution, nothing to be claimed.

It is a BED, not a song: it sits under a silent screen-capture and must never
pull attention off the UI. Hence no drums, no melody hook, slow harmonic motion.

Everything is additive (sine partials) rather than analogue-style saw/square
oscillators — a naive saw at these frequencies aliases into harsh inharmonic
partials, and additive simply cannot alias. Reverb is FFT convolution against an
exponentially-decaying noise burst, with a different seed per channel so the
stereo image opens up.
"""
from __future__ import annotations

import argparse
import os
import struct
import sys

import numpy as np

SR = 44100
REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(REPO, "promo", "audio", "tour_theme.wav")

BPM = 90.0
BEAT = 60.0 / BPM
BAR = 4 * BEAT                      # 2.667s

# D major, voiced for smooth leading: vi - IV - I - V. Warm and unresolved
# enough to loop without announcing itself every four bars.
CHORDS = [
    ("Bm", [59, 62, 66], 47),       # B3 D4 F#4 over B2
    ("G",  [59, 62, 67], 43),       # B3 D4 G4  over G2
    ("D",  [57, 62, 66], 50),       # A3 D4 F#4 over D3
    ("A",  [57, 61, 64], 45),       # A3 C#4 E4 over A2
]


def midi(n: float) -> float:
    return 440.0 * 2 ** ((n - 69) / 12.0)


def adsr(n: int, a: float, d: float, s: float, r: float) -> np.ndarray:
    """Sample-accurate envelope; every voice gets one so nothing clicks."""
    a, d, r = max(int(a * SR), 1), max(int(d * SR), 1), max(int(r * SR), 1)
    sus = max(n - a - d - r, 0)
    env = np.concatenate([
        np.linspace(0, 1, a, endpoint=False),
        np.linspace(1, s, d, endpoint=False),
        np.full(sus, s),
        np.linspace(s, 0, r),
    ])
    return np.resize(env, n) if len(env) != n else env


def partials(freq: float, n: int, harms, amps, detune_cents=0.0) -> np.ndarray:
    t = np.arange(n) / SR
    f = freq * 2 ** (detune_cents / 1200.0)
    out = np.zeros(n)
    for h, a in zip(harms, amps):
        if f * h >= SR / 2:         # never write a partial above Nyquist
            continue
        out += a * np.sin(2 * np.pi * f * h * t + np.random.uniform(0, 2 * np.pi))
    return out / max(sum(amps), 1e-9)


def add(buf: np.ndarray, sig: np.ndarray, at: float, gain: float) -> None:
    i = int(at * SR)
    j = min(i + len(sig), len(buf))
    if i < len(buf):
        buf[i:j] += sig[: j - i] * gain


def reverb_ir(seconds: float, decay: float, seed: int) -> np.ndarray:
    rng = np.random.default_rng(seed)
    n = int(seconds * SR)
    ir = rng.normal(0, 1, n) * np.exp(-np.arange(n) / (decay * SR))
    ir[: int(0.006 * SR)] = 0                      # pre-delay
    return ir / (np.sqrt(np.sum(ir ** 2)) + 1e-9)


def fftconv(x: np.ndarray, ir: np.ndarray) -> np.ndarray:
    n = 1 << int(np.ceil(np.log2(len(x) + len(ir) - 1)))
    y = np.fft.irfft(np.fft.rfft(x, n) * np.fft.rfft(ir, n), n)
    return y[: len(x)]


def shelf(x: np.ndarray) -> np.ndarray:
    """+5 dB above ~3 kHz, -4 dB below ~140 Hz, both as smooth sigmoid shelves.

    Measured on the first render: 44% of the energy sat in 120-500 Hz and only
    0.2% above 6 kHz, i.e. muffled and boomy on anything but headphones.
    """
    n = len(x)
    f = np.fft.rfftfreq(n, 1 / SR)
    g = 10 ** ((5.0 / (1 + np.exp(-(f - 3000) / 900))) / 20)
    g *= 10 ** ((-4.0 / (1 + np.exp((f - 140) / 60))) / 20)
    return np.fft.irfft(np.fft.rfft(x) * g, n)


def build(seconds: float) -> np.ndarray:
    np.random.seed(7)
    n = int(seconds * SR)
    pad = np.zeros(n); arp = np.zeros(n); bass = np.zeros(n); bell = np.zeros(n)

    bars = int(np.ceil(seconds / BAR))
    for b in range(bars):
        t0 = b * BAR
        name, tones, root = CHORDS[b % len(CHORDS)]
        cycle = b // len(CHORDS)

        # --- pad: three stacked detunes per chord tone, slow in, long tail ---
        ln = int(BAR * 1.9 * SR)
        env = adsr(ln, 0.55, 0.5, 0.72, BAR * 0.85)
        for tone in tones:
            for det in (-7.0, 0.0, 7.0):
                v = partials(midi(tone), ln, [1, 2, 3, 4, 6],
                             [1, .5, .28, .16, .08], det)
                add(pad, v * env, t0, 0.30)

        # --- bass: one soft root per bar ---
        ln = int(BAR * 1.05 * SR)
        v = partials(midi(root), ln, [1, 2], [1, .22])
        add(bass, v * adsr(ln, 0.02, 0.35, 0.55, BAR * 0.5), t0, 0.42)

        # --- arp: eighth notes, the only thing carrying motion ---
        if b >= 2:
            up = [tones[0], tones[1], tones[2], tones[1] + 12,
                  tones[2], tones[1], tones[0], tones[1]]
            grow = min(1.0, (b - 2) / 6.0)          # fade the arp in over 6 bars
            for k, tone in enumerate(up):
                ln = int(0.5 * SR)
                v = partials(midi(tone + 12), ln, [1, 2, 3, 4, 6], [1, .42, .24, .13, .07])
                e = np.exp(-np.arange(ln) / (0.16 * SR)) * adsr(ln, 0.004, .02, 1, .05)
                add(arp, v * e, t0 + k * BEAT / 2, 0.24 * grow)

        # --- bell: one shimmer at the top of each four-bar cycle ---
        if b % len(CHORDS) == 0 and cycle >= 1:
            ln = int(2.6 * SR)
            v = partials(midi(tones[0] + 24), ln, [1, 2.76, 5.4, 8.9], [1, .38, .18, .08])
            add(bell, v * np.exp(-np.arange(ln) / (0.85 * SR)), t0, 0.19)

    dry = pad * 0.50 + bass * 0.78 + arp * 0.95 + bell * 0.95
    dry = shelf(dry)

    # --- stereo: a different IR per side widens it without phasing ---
    wet_l = fftconv(dry, reverb_ir(1.5, 0.42, 11))
    wet_r = fftconv(dry, reverb_ir(1.5, 0.42, 29))
    left = dry * 0.78 + wet_l * 0.42
    right = dry * 0.78 + wet_r * 0.42

    st = np.stack([left, right], axis=1)
    st *= np.tile(adsr(n, 1.6, 0.1, 1.0, 3.4).reshape(-1, 1), (1, 2))
    st = np.tanh(st * 1.25) / np.tanh(1.25)        # soft knee, no hard clipping
    peak = np.max(np.abs(st))
    if peak > 0:
        st *= 10 ** (-1.5 / 20) / peak             # leave 1.5 dBFS of headroom
    return st


def write_wav(path: str, data: np.ndarray) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    pcm = (np.clip(data, -1, 1) * 32767).astype("<i2").tobytes()
    with open(path, "wb") as f:
        f.write(b"RIFF" + struct.pack("<I", 36 + len(pcm)) + b"WAVEfmt ")
        f.write(struct.pack("<IHHIIHH", 16, 1, 2, SR, SR * 4, 4, 16))
        f.write(b"data" + struct.pack("<I", len(pcm)) + pcm)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seconds", type=float, default=62.0)
    ap.add_argument("--out", default=OUT)
    a = ap.parse_args()
    data = build(a.seconds)
    write_wav(a.out, data)
    rms = float(np.sqrt(np.mean(data ** 2)))
    print(f"wrote {a.out}  {a.seconds:.1f}s  peak "
          f"{20*np.log10(np.max(np.abs(data))+1e-9):.1f} dBFS  "
          f"rms {20*np.log10(rms+1e-9):.1f} dBFS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
