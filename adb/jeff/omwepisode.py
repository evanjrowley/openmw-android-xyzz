#!/usr/bin/env python3
"""Episode recorder: aligned frames + telemetry + input, for adapter data.

Captures a play session into one directory:
  episode-<ts>/
    frames/000001.jpg ...   periodic device screencaps
    episode.jsonl           {"t", "kind", ...} rows: state | input | frame

Sources: [Android DebugState] (STREAM telemetry) and [Android DebugInput]
(physical/injected controller events, OPENMW_DEBUG_EPISODE=1) streamed
from openmw.log via `adb shell tail -F`, plus host-side screencaps. Run
omwjeff.py or play by hand while this records.

  cd openmw-android/adb/jeff
  nix-shell -p python312 python312Packages.pillow --run \
    'python3 omwepisode.py --duration 120'
"""
import argparse
import json
import os
import subprocess
import sys
import threading
import time

SERIAL = os.environ.get("OMW_SERIAL", "642264a2")
PKG = os.environ.get("OMW_PKG", "is.xyz.omw_nightly.debug")
LOG = os.environ.get("OMW_LOG", "/sdcard/omw_nightly/config/openmw.log")


def adb(*args, binary=False):
    cmd = ["adb", "-s", SERIAL] + list(args)
    out = subprocess.run(cmd, capture_output=True)
    return out.stdout if binary else out.stdout.decode(errors="replace").replace("\r", "")


def bc(action, *extras):
    adb("shell", "am", "broadcast", "-p", PKG, "-a", action, *extras,
        ">/dev/null", "2>&1")


class Episode:
    def __init__(self, outdir, frame_interval, duration):
        self.out = outdir
        self.frame_interval = frame_interval
        self.duration = duration
        self.stop = threading.Event()
        self.lock = threading.Lock()
        self.counts = {"state": 0, "input": 0, "frame": 0}
        os.makedirs(os.path.join(outdir, "frames"), exist_ok=True)
        self.jsonl = open(os.path.join(outdir, "episode.jsonl"), "a")

    def row(self, kind, payload):
        with self.lock:
            self.jsonl.write(json.dumps({"t": time.time(), "kind": kind,
                                         **payload}) + "\n")
            self.jsonl.flush()
            self.counts[kind] = self.counts.get(kind, 0) + 1

    def log_reader(self):
        """Stream openmw.log and pick up state + input lines."""
        proc = subprocess.Popen(
            ["adb", "-s", SERIAL, "shell", f"tail -F -n 200 {LOG}"],
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        deadline = time.time() + self.duration + 20
        while time.time() < deadline and not self.stop.is_set():
            line = proc.stdout.readline()
            if not line:
                time.sleep(0.2)
                continue
            text = line.decode(errors="replace").strip()
            t = time.time()
            if "Android DebugState" in text:
                payload = text.split("Android DebugState]", 1)[-1].strip()
                self.row("state", {"data": payload})
            elif "Android DebugInput" in text:
                parts = text.split("Android DebugInput]", 1)[-1].split()
                if len(parts) == 3:
                    self.row("input", {"dev": parts[0], "id": int(parts[1]),
                                       "value": float(parts[2])})
        proc.kill()

    def frame_capturer(self):
        idx = 0
        deadline = time.time() + self.duration
        while time.time() < deadline and not self.stop.is_set():
            png = adb("exec-out", "screencap", "-p", binary=True)
            if png:
                try:
                    from PIL import Image
                    import io
                    im = Image.open(io.BytesIO(png)).convert("RGB")
                    name = f"frames/{idx:06d}.jpg"
                    im.save(os.path.join(self.out, name), quality=80)
                    self.row("frame", {"file": name,
                                       "w": im.width, "h": im.height})
                    idx += 1
                except Exception as e:
                    print(f"frame {idx} failed: {e}", file=sys.stderr)
            self.stop.wait(self.frame_interval)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--duration", type=float, default=60.0)
    ap.add_argument("--stream-period", type=int, default=30,
                    help="engine frames between telemetry lines (0=off)")
    ap.add_argument("--frame-interval", type=float, default=2.0)
    ap.add_argument("--out", default="")
    args = ap.parse_args()

    out = args.out or f"episode-{time.strftime('%Y%m%d-%H%M%S')}"
    ep = Episode(out, args.frame_interval, args.duration)
    print(f"recording {args.duration}s to {out}/ "
          f"(stream={args.stream_period}, frame every {args.frame_interval}s)")

    bc("is.xyz.omw.debug.STREAM", "--ei", "period", str(args.stream_period))
    threads = [threading.Thread(target=ep.log_reader, daemon=True),
               threading.Thread(target=ep.frame_capturer, daemon=True)]
    for t in threads:
        t.start()
    try:
        deadline = time.time() + args.duration
        while time.time() < deadline:
            time.sleep(0.5)
    except KeyboardInterrupt:
        pass
    finally:
        ep.stop.set()
        time.sleep(1.0)
        bc("is.xyz.omw.debug.STREAM", "--ei", "period", "0")
        with open(os.path.join(out, "manifest.json"), "w") as f:
            json.dump({"duration": args.duration,
                       "stream_period": args.stream_period,
                       "frame_interval": args.frame_interval,
                       "counts": ep.counts}, f, indent=1)
        print(f"done: {ep.counts}")


if __name__ == "__main__":
    main()
