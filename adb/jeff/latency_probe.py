#!/usr/bin/env python3
"""Measure Jeff server latency: health + warm text + image decisions.

Run right after (re)pointing JEFF_URL at a new server — the first query
of a cold server loads the checkpoint (~60s on the CUDA host, minutes on
CPU), so expect one slow call before the timings settle.

  nix-shell -p python312 --run 'python3 latency_probe.py'
"""
import base64
import io
import json
import os
import statistics
import sys
import time
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from omwjeff import ask  # noqa: E402

JEFF_URL = os.environ.get("JEFF_URL", "http://10.126.193.1:8765")

ACTIONS = {
    "forward": "Walk straight ahead for about half a second",
    "turn_left": "Rotate the view left by about 35 degrees",
    "turn_right": "Rotate the view right by about 35 degrees",
    "activate": "Press Activate (left trigger)",
}


def main():
    with urllib.request.urlopen(JEFF_URL + "/health", timeout=15) as f:
        health = json.loads(f.read())
    print("health:", health)

    state = ("You are playing the open-world RPG Morrowind on a gamepad. "
             "GOAL: explore. Choose the next action.")
    q = {"action": {"type": "choice",
                    "instructions": "Pick the best next action.",
                    "criteria": dict(ACTIONS)}}

    print("warming (first decision may load the checkpoint)...")
    ask(state, q)
    times = []
    for _ in range(3):
        _, dt = ask(state + " run", q)
        times.append(dt)
    print(f"text decision: median {statistics.median(times)*1000:.0f}ms "
          f"({', '.join(f'{t*1000:.0f}ms' for t in times)})")

    # A tiny synthetic frame is enough to time the vision path; needs Pillow.
    try:
        from PIL import Image
    except ImportError:
        print("image decision: skipped (Pillow not installed; run in "
              "nix-shell -p python312 python312Packages.pillow)")
        return
    im = Image.new("RGB", (640, 360), (30, 25, 20))
    buf = io.BytesIO()
    im.save(buf, format="JPEG", quality=70)
    img = "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode()
    times = []
    for _ in range(2):
        _, dt = ask(state, q, [img])
        times.append(dt)
    print(f"image decision (640px): median {statistics.median(times)*1000:.0f}ms "
          f"({', '.join(f'{t*1000:.0f}ms' for t in times)})")


if __name__ == "__main__":
    main()
