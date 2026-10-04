"""
Finds the best place to end a segment: the strongest natural pause (longest + deepest
relative dip in loudness) inside a window around the target length.

Only a small window (~2 minutes) of the huge audio file is decoded per call, so it works
on a 25-hour file without loading it into memory.
"""
import subprocess
import numpy as np
from scipy.ndimage import uniform_filter1d, median_filter

SR = 8000
HOP_S = 0.02


def _decode_window(audio_path: str, start: float, length: float) -> np.ndarray:
    cmd = [
        "ffmpeg", "-v", "error", "-ss", f"{start:.3f}", "-t", f"{length:.3f}",
        "-i", audio_path, "-ac", "1", "-ar", str(SR), "-f", "f32le", "-",
    ]
    raw = subprocess.run(cmd, capture_output=True, check=True).stdout
    return np.frombuffer(raw, dtype=np.float32)


def find_pauses(audio_path: str, start: float, length: float):
    """Returns list of dicts: {t (abs seconds, pause start), dur, depth, end}"""
    data = _decode_window(audio_path, start, length)
    hop = int(SR * HOP_S)
    n = len(data) // hop
    if n < 50:
        return []
    rms = np.sqrt(np.mean(data[: n * hop].reshape(n, hop) ** 2, axis=1) + 1e-12)
    db = uniform_filter1d(20 * np.log10(rms), 5)
    base = median_filter(db, size=250, mode="nearest")   # local baseline (~5 s)
    rel = db - base
    low = rel < -7.0

    pauses, i = [], 0
    while i < n:
        if low[i]:
            j = i
            while j < n and low[j]:
                j += 1
            dur = (j - i) * HOP_S
            if dur >= 0.12:
                pauses.append({
                    "t": start + i * HOP_S,
                    "end": start + j * HOP_S,
                    "dur": dur,
                    "depth": float(-rel[i:j].min()),
                })
            i = j
        else:
            i += 1
    return pauses


def find_cut(audio_path: str, start: float, target: float = 600.0,
             window: float = 45.0, total: float | None = None) -> float:
    """Absolute time (s) where the segment starting at `start` should end."""
    ideal = start + target
    if total is not None and ideal + window >= total:
        return total                                   # last segment: play to the end
    pauses = find_pauses(audio_path, ideal - window, 2 * window)
    if not pauses:
        return ideal                                   # fallback: hard cut (rare)

    def score(p):
        centre = (p["t"] + p["end"]) / 2
        # long + deep pause is more likely an ayah end; small penalty for distance
        return p["dur"] * 2.0 + p["depth"] * 0.1 - abs(centre - ideal) / window * 0.6

    best = max(pauses, key=score)
    return (best["t"] + best["end"]) / 2               # cut in the middle of the pause


if __name__ == "__main__":
    import sys
    path = sys.argv[1]
    start = 0.0
    total = float(subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", path],
        capture_output=True, text=True).stdout)
    tgt = float(sys.argv[2]) if len(sys.argv) > 2 else 600.0
    k = 1
    while start < total - 1:
        cut = find_cut(path, start, tgt, 45.0, total)
        print(f"segment {k}: {start:7.2f} -> {cut:7.2f}  (len {cut-start:6.2f}s)")
        start, k = cut, k + 1
