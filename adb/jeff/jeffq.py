#!/usr/bin/env python3
"""Interactive Jeff question helper for supervised (human-driven) runs.

Unlike omwjeff.py this does not actuate anything — it only screencaps and
asks Jeff questions, so a human (or shell script) can drive the gamepad.

Usage:
  jeffq.py shot [out.png]     screencap the device to a local PNG
  jeffq.py ask ASKFILE        ask the questions in ASKFILE (see below)

ASKFILE (JSON):
  {
    "state": "free-form context string (telemetry etc.)",
    "questions": {"key": {"type": "choice|noul|score", "instructions": ...,
                           "criteria": {...}}},        # criteria for choice only
    "image": "/tmp/omw_screen.png"                     # optional
  }

Prints one line per question: key -> choice (conf) and writes the raw
answers dict to /tmp/omw_answers.json.
"""
import base64
import io
import json
import os
import subprocess
import sys
import time
import urllib.request

SERIAL = os.environ.get("OMW_SERIAL", "642264a2")
JEFF_URL = os.environ.get("JEFF_URL", "http://10.126.193.1:8765")
MODEL = os.environ.get("JEFF_MODEL", "jeff-latest")


def shot(out="/tmp/omw_screen.png"):
    data = subprocess.run(["adb", "-s", SERIAL, "exec-out", "screencap", "-p"],
                          capture_output=True).stdout
    with open(out, "wb") as f:
        f.write(data)
    print(out)


def data_url(path, width=960):
    from PIL import Image
    im = Image.open(path).convert("RGB")
    if im.width > width:
        im = im.resize((width, int(im.height * width / im.width)))
    buf = io.BytesIO()
    im.save(buf, "JPEG", quality=80)
    return "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode()


def ask(state, questions, images=()):
    # Unchanging fields first, state last (Jeff prompt-cache hint).
    body = json.dumps({"model": MODEL, "questions": questions,
                       "images": list(images), "state": state}).encode()
    req = urllib.request.Request(JEFF_URL + "/v1/systemone", data=body,
                                 headers={"Content-Type": "application/json"})
    t0 = time.time()
    with urllib.request.urlopen(req, timeout=180) as f:
        resp = json.loads(f.read())
    return resp["answers"], time.time() - t0


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(2)
    cmd = sys.argv[1]
    if cmd == "shot":
        shot(sys.argv[2] if len(sys.argv) > 2 else "/tmp/omw_screen.png")
        return
    if cmd == "ask":
        spec = json.load(open(sys.argv[2]))
        imgs = []
        if spec.get("image"):
            imgs.append(data_url(spec["image"]))
        answers, dt = ask(spec["state"], spec["questions"], imgs)
        for name, a in answers.items():
            print(f"{name}: {a.get('choice')} (conf {a.get('confidence')})")
        print(f"[{dt * 1000:.0f} ms]", file=sys.stderr)
        with open("/tmp/omw_answers.json", "w") as f:
            json.dump(answers, f)
        return
    print(__doc__)
    sys.exit(2)


if __name__ == "__main__":
    main()
