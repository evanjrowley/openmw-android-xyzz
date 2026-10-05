#!/usr/bin/env python3
"""Minimal telemetry-driven driver for the OpenMW debug surface.

Run inside nix-shell -p python312. Everything is world-absolute: turns are
computed from telemetry yaw, so no hand math. Seeds omwpilot.py.
"""
import os
import re
import subprocess
import sys
import time

SERIAL = os.environ.get("OMW_SERIAL", "642264a2")
PKG = "is.xyz.omw_nightly.debug"
LOG = "/sdcard/omw_nightly/config/openmw.log"


def adb(*args):
    return subprocess.run(["adb", "-s", SERIAL, "shell", *args],
                          capture_output=True, text=True, timeout=30)


def bc(action, *extra):
    adb("am", "broadcast", "-p", PKG, "-a", f"is.xyz.omw.debug.{action}", *extra)


def state(hint=""):
    extra = ("--es", "hint", hint) if hint else ()
    bc("STATE", *extra)
    time.sleep(1.4)
    out = adb(f"grep 'Android DebugState' {LOG} | tail -1").stdout.strip()
    return out


def num(pat, s, cast=float):
    m = re.search(pat, s)
    return cast(m.group(1)) if m else None


def pos_yaw(telem):
    m = re.search(r"pos=([-\d.]+),([-\d.]+),([-\d.]+) yaw=([-\d.]+)", telem)
    return (float(m.group(1)), float(m.group(2)), float(m.group(3)),
            float(m.group(4))) if m else (None, None, None, None)


def turn_to(world_yaw, tol=3.0, tries=3):
    for _ in range(tries):
        x, y, z, yaw = pos_yaw(state())
        if yaw is None:
            return False
        rel = (world_yaw - yaw + 540) % 360 - 180
        if abs(rel) < tol:
            return True
        bc("SERVO", "--es", "kind", "turn", "--ef", "deg", f"{rel:.1f}")
        time.sleep(2.5 + abs(rel) / 90)
    return False


def walk(ms=1200):
    bc("SERVO", "--es", "kind", "walk", "--ei", "duration_ms", str(ms))
    time.sleep(ms / 1000 + 2.5)


def goto(hint, wait=16):
    bc("SERVO", "--es", "kind", "goto", "--es", "hint", hint)
    time.sleep(wait)


def face(hint, wait=7):
    bc("SERVO", "--es", "kind", "face", "--es", "hint", hint)
    time.sleep(wait)


def activate():
    bc("JOY_PULSE", "--ei", "axis", "4", "--ef", "value", "1.0",
       "--ei", "duration_ms", "350")
    time.sleep(2.5)


def probe(dx=0.0, dy=0.0, dist=250.0):
    bc("PROBE", "--ef", "dx", str(dx), "--ef", "dy", str(dy),
       "--ef", "dist", str(dist))
    time.sleep(0.5)
    return adb(f"grep 'Android DebugProbe' {LOG} | tail -1").stdout.strip()


def route(hint):
    bc("ROUTE", "--es", "hint", hint)
    time.sleep(0.5)
    return adb(f"grep 'Android DebugRoute' {LOG} | tail -1").stdout.strip()


def bearing_to(tx, ty, telem):
    _, px, py, yaw = (None, *pos_yaw(telem)[1:3], pos_yaw(telem)[3])
    import math
    return (math.degrees(math.atan2(tx - px, ty - py)) - yaw + 540) % 360 - 180


def dismiss_dialogs(rounds=4):
    for _ in range(rounds):
        t = state()
        if "InteractiveMessageBox" not in t:
            return t
        bc("PAD_BUTTON", "--ei", "keycode", "96", "--ez", "down", "true")
        time.sleep(0.15)
        bc("PAD_BUTTON", "--ei", "keycode", "96", "--ez", "down", "false")
        time.sleep(2)
    return state()


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "state"
    if cmd == "state":
        print(state(sys.argv[2] if len(sys.argv) > 2 else ""))
    elif cmd == "north":
        turn_to(0.0) and [walk(2500) or print(state().split(" ")[3])
                          for _ in range(int(sys.argv[2] if len(sys.argv) > 2 else 3))]
    elif cmd == "probe":
        print(probe(float(sys.argv[2]), float(sys.argv[3]) if len(sys.argv) > 3 else 0.0))
    elif cmd == "route":
        print(route(sys.argv[2]))
