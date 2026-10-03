#!/usr/bin/env python3
"""Jeff-driven OpenMW gamepad control loop (v2).

Each tick: screencap the device + pull one engine telemetry line, describe the
situation to the local Jeff System-1 model, let it pick ONE gamepad action,
execute it over the DebugInputReceiver broadcast surface, and log everything.

v2: landmark memory (named objects the crosshair swept over), context-sized
option sets, anti-spin notes, door lore, door_seen perception question.

Architecture note (per Jeff README: "reason in code, decide with Jeff"): the
harness owns memory and telemetry parsing; Jeff owns the per-tick decision.

Run inside nix (Pillow):
  cd openmw-android/adb/jeff
  nix-shell -p python312 python312Packages.pillow --run \
    'python3 omwjeff.py --task "..." --ticks 30'

Needs the debug build (DebugInputReceiver) and patch 0011 telemetry.
Env: OMW_SERIAL, OMW_PKG, JEFF_URL, JEFF_MODEL.
"""
import argparse
import base64
import json
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request

SERIAL = os.environ.get("OMW_SERIAL", "642264a2")
PKG = os.environ.get("OMW_PKG", "is.xyz.omw_nightly.debug")
JEFF_URL = os.environ.get("JEFF_URL", "http://10.126.191.1:8765")
MODEL = os.environ.get("JEFF_MODEL", "jeff-latest")
LOG = os.environ.get("OMW_LOG", "/sdcard/omw_nightly/config/openmw.log")

# ---------------------------------------------------------------- adb layer

def adb(*args, binary=False):
    cmd = ["adb", "-s", SERIAL] + list(args)
    out = subprocess.run(cmd, capture_output=True)
    return out.stdout if binary else out.stdout.decode(errors="replace").replace("\r", "")


def bc(action, *extras):
    """Fire one DebugInputReceiver broadcast (errors ignored; app may be gone)."""
    adb("shell", "am", "broadcast", "-p", PKG, "-a", action, *extras,
        ">/dev/null", "2>&1")


def screencap(width):
    """Device frame as a base64 JPEG data URL, plus a local PIL copy."""
    png = adb("exec-out", "screencap", "-p", binary=True)
    if not png:
        return None, None
    from PIL import Image
    import io
    im = Image.open(io.BytesIO(png)).convert("RGB")
    if width < im.width:
        im = im.resize((width, round(im.height * width / im.width)))
    buf = io.BytesIO()
    im.save(buf, format="JPEG", quality=80)
    b64 = base64.b64encode(buf.getvalue()).decode()
    return "data:image/jpeg;base64," + b64, im


def telemetry(hint=""):
    """One fresh [Android DebugState] line's payload (empty string if none)."""
    mark = adb("shell", f"grep -c 'Android DebugState' {LOG} 2>/dev/null || true").strip()
    try:
        mark = int(mark or 0)
    except ValueError:
        mark = 0
    extras = ["--es", "hint", hint] if hint else []
    bc("is.xyz.omw.debug.STATE", *extras)
    for _ in range(15):
        time.sleep(0.3)
        n = adb("shell", f"grep -c 'Android DebugState' {LOG} 2>/dev/null || true").strip()
        try:
            if int(n or 0) > mark:
                break
        except ValueError:
            pass
    lines = adb("shell", f"grep 'Android DebugState' {LOG} | tail -1").strip()
    return lines.split("Android DebugState]", 1)[-1].strip()


def parse_gui(telem):
    m = re.search(r"gui=(-?\d+)", telem)
    return int(m.group(1)) if m else None


def parse_faced(telem):
    m = re.search(r"faced='([^']*)'", telem)
    if not m or m.group(1) in ("none", ""):
        return None, None
    d = re.search(r"fdist=(-?[\d.]+)", telem)
    return m.group(1), (float(d.group(1)) if d else None)


def parse_yaw(telem):
    m = re.search(r"yaw=(-?[\d.]+)", telem)
    return float(m.group(1)) if m else None


def parse_target(telem):
    """hint= line: target='Name' tbearing=<deg rel to yaw> tdist=<units>."""
    m = re.search(r"target='([^']*)' tbearing=(-?[\d.]+) tdist=(-?[\d.]+)", telem)
    if not m:
        return None, None, None
    return m.group(1), float(m.group(2)), float(m.group(3))


TURN_RATE = 0.0876  # degrees per ms at full stick deflection (measured)


def proportional_turn(bearing):
    """Turn toward `bearing` (deg relative to current yaw).

    Preferred path: the engine-side SERVO primitive (patch 0012) — a closed
    look loop at frame rate that finishes aligned within ~1.5°. Falls back
    to host-side proportional pulses on older builds (no DebugServo log).
    """
    ms = int(min(1500, max(150, abs(bearing) / TURN_RATE)))
    axis_val = "1.0" if bearing > 0 else "-1.0"
    mark = adb("shell",
               f"grep -c 'DebugServo' {LOG} 2>/dev/null || true").strip()
    bc("is.xyz.omw.debug.SERVO", "--es", "kind", "turn", "--ef", "deg",
       f"{bearing:.1f}")
    for _ in range(40):  # servo logs done=aligned/blocked/timeout when finished
        time.sleep(0.25)
        n = adb("shell",
                f"grep -c 'DebugServo' {LOG} 2>/dev/null || true").strip()
        if n.isdigit() and int(n) > (int(mark) if mark.isdigit() else 0):
            return
    bc("is.xyz.omw.debug.JOY_PULSE", "--ei", "axis", "2", "--ef", "value",
       axis_val, "--ei", "duration_ms", str(ms))

# ---------------------------------------------------------------- Jeff layer

SCENE_ACTIONS = {
    "wall": "A wall or large solid object blocks the way within a couple of steps",
    "open_path": "The ground ahead is walkable for several meters (floor, road, corridor)",
    "stairs_up": "A staircase or ramp leads upward ahead",
    "stairs_down": "A staircase or slope leads downward ahead",
    "door": "A closed door (usually wooden, often in an arched frame) faces you",
    "npc": "A person or creature stands ahead",
    "clutter": "Furniture, crates, pillars or other objects clutter the way",
    "void": "Darkness or something unreadable",
}

PROMISING_DIRS = {
    "straight_ahead": "The goal is most likely reached by continuing forward",
    "left": "The goal is most likely reached by turning left",
    "right": "The goal is most likely reached by turning right",
    "behind": "The goal is most likely behind; turn around",
}


def perception_questions():
    return {
        "scene": {"type": "choice",
                  "instructions": "Look at what is directly ahead of the "
                                  "character (center of the frame).",
                  "criteria": dict(SCENE_ACTIONS)},
        "promising": {"type": "choice",
                      "instructions": "Which direction most likely leads "
                                      "toward the goal?",
                      "criteria": dict(PROMISING_DIRS)},
        "door_centered": {"type": "noul",
                          "instructions": "Is a closed door directly under "
                                          "the crosshair at the center?"},
    }

MENU_ACTIONS = {
    "dpad_up": "Move the menu selection up one entry",
    "dpad_down": "Move the menu selection down one entry",
    "dpad_left": "Move the menu selection / toggle left",
    "dpad_right": "Move the menu selection / toggle right",
    "button_a": "Activate the highlighted menu entry (A button)",
    "button_b": "Cancel / go back / close the current window (B button)",
    "button_y": "Alternate action on the highlighted entry (Y button)",
    "wait": "Do nothing for a moment and re-assess",
}

ACT = {
    "forward": lambda: bc("is.xyz.omw.debug.JOY_PULSE", "--ei", "axis", "1", "--ef", "value", "-1.0", "--ei", "duration_ms", "1000"),
    "back": lambda: bc("is.xyz.omw.debug.JOY_PULSE", "--ei", "axis", "1", "--ef", "value", "1.0", "--ei", "duration_ms", "600"),
    "strafe_left": lambda: bc("is.xyz.omw.debug.JOY_PULSE", "--ei", "axis", "0", "--ef", "value", "-1.0", "--ei", "duration_ms", "600"),
    "strafe_right": lambda: bc("is.xyz.omw.debug.JOY_PULSE", "--ei", "axis", "0", "--ef", "value", "1.0", "--ei", "duration_ms", "600"),
    "turn_left": lambda: bc("is.xyz.omw.debug.JOY_PULSE", "--ei", "axis", "2", "--ef", "value", "-1.0", "--ei", "duration_ms", "800"),
    "turn_right": lambda: bc("is.xyz.omw.debug.JOY_PULSE", "--ei", "axis", "2", "--ef", "value", "1.0", "--ei", "duration_ms", "800"),
    "activate": lambda: bc("is.xyz.omw.debug.JOY_PULSE", "--ei", "axis", "4", "--ef", "value", "1.0", "--ei", "duration_ms", "350"),
    "attack": lambda: bc("is.xyz.omw.debug.JOY_PULSE", "--ei", "axis", "5", "--ef", "value", "1.0", "--ei", "duration_ms", "350"),
    "look_up": lambda: bc("is.xyz.omw.debug.JOY_PULSE", "--ei", "axis", "3", "--ef", "value", "-1.0", "--ei", "duration_ms", "300"),
    "look_down": lambda: bc("is.xyz.omw.debug.JOY_PULSE", "--ei", "axis", "3", "--ef", "value", "1.0", "--ei", "duration_ms", "300"),
    "wait": lambda: time.sleep(0.5),
}
for _btn, _key in (("dpad_up", 19), ("dpad_down", 20), ("dpad_left", 21),
                   ("dpad_right", 22), ("button_a", 96), ("button_b", 97),
                   ("button_y", 100)):
    def _tap(key=_key):
        bc("is.xyz.omw.debug.PAD_BUTTON", "--ei", "keycode", str(key),
           "--ez", "down", "true")
        time.sleep(0.15)
        bc("is.xyz.omw.debug.PAD_BUTTON", "--ei", "keycode", str(key),
           "--ez", "down", "false")
    ACT[_btn] = _tap


def ask(state, questions, images=()):
    """POST to /v1/systemone; returns the answers dict (raises on failure)."""
    # Unchanging parts first, changing last (Jeff prompt-cache hint).
    body = json.dumps({"model": MODEL, "questions": questions,
                       "images": list(images), "state": state}).encode()
    req = urllib.request.Request(JEFF_URL + "/v1/systemone", data=body,
                                 headers={"Content-Type": "application/json"})
    t0 = time.time()
    with urllib.request.urlopen(req, timeout=180) as f:
        resp = json.loads(f.read())
    return resp["answers"], time.time() - t0


def choice_q(actions, instructions):
    return {"type": "choice", "instructions": instructions,
            "criteria": {k: v for k, v in actions.items()}}

# ---------------------------------------------------------------- main loop

def norm_yaw(a):
    """Normalize degrees to (-180, 180]."""
    while a <= -180:
        a += 360
    while a > 180:
        a -= 360
    return a


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--task", required=True, help="high-level goal for every tick")
    ap.add_argument("--hint", default="", help="telemetry hint: nearest actor name substring")
    ap.add_argument("--ticks", type=int, default=30)
    ap.add_argument("--sleep", type=float, default=0.4, help="pause after acting")
    ap.add_argument("--image-width", type=int, default=960)
    ap.add_argument("--menu", action="store_true", help="force the menu action set")
    ap.add_argument("--observe-only", action="store_true", help="screenshot+Jeff, no actuation")
    ap.add_argument("--frames", default="/tmp/omwjeff_frames", help="frame dump dir")
    ap.add_argument("--transcript", default="", help="JSONL transcript path")
    args = ap.parse_args()

    os.makedirs(args.frames, exist_ok=True)
    tr_path = args.transcript or f"/tmp/omwjeff-{time.strftime('%H%M%S')}.jsonl"
    tr = open(tr_path, "a")

    history = []      # (action, short result)
    landmarks = []    # (name, yaw, dist) — named objects the crosshair swept
    act_streak = 0    # consecutive activations that opened no dialog

    try:
        ask("warmup", {"ping": {"type": "noul"}})
    except Exception as e:
        print(f"jeff warmup failed: {e}", file=sys.stderr)

    for tick in range(args.ticks):
        # Neutral axis event: keeps the idle orbit camera from engaging
        # between ticks (any joystick input resets its timer).
        bc("is.xyz.omw.debug.JOY_AXIS", "--ei", "axis", "2", "--ef", "value", "0.0")
        img_b64, im = screencap(args.image_width)
        if im is None:
            print(f"[{tick}] no screenshot - device/app gone?")
            time.sleep(2)
            continue
        frame_path = f"{args.frames}/tick{tick:03d}.jpg"
        im.save(frame_path, quality=80)

        telem = telemetry(args.hint)
        gui = parse_gui(telem)
        faced_name, faced_dist = parse_faced(telem)
        yaw = parse_yaw(telem)

        if faced_name and yaw is not None:
            if not any(lm[0] == faced_name for lm in landmarks):
                landmarks.append((faced_name, yaw, faced_dist))
                landmarks = landmarks[-6:]

        if args.menu:
            regime = "menu"
        elif gui is None:
            regime = None
        else:
            regime = "game" if gui == -1 else "menu"

        questions = {}
        if regime is None:
            questions["menu_open"] = {
                "type": "noul",
                "instructions": "Does the frame show a menu, dialog or window overlaying the game world?"}
        if regime != "menu":
            questions.update(perception_questions())
        else:
            questions["action"] = choice_q(MENU_ACTIONS,
                "Pick the single best next gamepad action toward the goal.")

        state = build_state(args.task, telem, history, regime, landmarks)
        try:
            answers, dt = ask(state, questions, [img_b64] if img_b64 else [])
        except (urllib.error.URLError, KeyError, ValueError) as e:
            print(f"[{tick}] jeff failed: {e}; waiting")
            time.sleep(2)
            continue

        if regime is None:
            regime = "menu" if answers.get("menu_open", {}).get("noul", 0) > 0.5 else "game"

        if regime == "menu":
            pick = answers.get("action", {}).get("choice", "wait")
            conf = answers.get("action", {}).get("confidence", 0.0)
            probs = answers.get("action", {}).get("probabilities", {})
        else:
            scene = answers.get("scene", {})
            promising = answers.get("promising", {})
            door_c = answers.get("door_centered", {}).get("noul", 0.0)
            scene_pick = scene.get("choice", "void")
            scene_conf = scene.get("confidence", 0.0)
            dir_pick = promising.get("choice", "straight_ahead")

            # Harness policy ("reason in code, decide with Jeff"): Jeff
            # classifies the scene; the code maps classification to actions.
            # A hinted target (telemetry target=/tbearing=/tdist=) lets the
            # code steer proportionally; Jeff still gates the activation.
            tname, tbear, tdist = parse_target(telem)
            blocked = bool(history and history[-1][0] in ("forward", "strafe_left",
                                                          "strafe_right")
                           and not history[-1][1])
            # Activation retries: twice without a dialog opening means the
            # crosshair is probably off vertically — probe with the pitch axis.
            if act_streak >= 2 and gui == -1:
                pick = "look_down" if act_streak % 2 == 0 else "look_up"
            turn_dir = {"left": -70, "right": 70, "behind": 145,
                        "straight_ahead": 0}.get(dir_pick, 70)
            door_named = bool(faced_name and "door" in faced_name.lower())
            if door_named or (door_c > 0.75 and faced_name
                              and faced_dist and faced_dist < 220):
                pick = "activate"
            elif tname:
                # Code-steered approach toward the hinted target.
                if abs(tbear) > 15:
                    pick = "steer"          # proportional_turn(tbear)
                elif tdist > 130:
                    pick = "forward"
                elif scene_pick == "npc" or door_c > 0.5 or abs(tbear) < 8:
                    pick = "activate"
                else:
                    pick = "forward"
            elif scene_pick in ("open_path", "stairs_up", "stairs_down") \
                    and not blocked:
                pick = "forward"
            elif scene_pick == "npc":
                pick = "activate" if (faced_dist and faced_dist < 220) else "forward"
            elif scene_pick == "door":
                pick = "activate" if (faced_name and faced_dist
                                      and faced_dist < 260) else "forward"
            else:  # wall, clutter, void, or blocked forward: rotate
                pick = {"left": "turn_left", "right": "turn_right",
                        "behind": "turn_right",
                        "straight_ahead": "turn_right"}.get(dir_pick,
                                                            "turn_right")
            conf, probs = scene_conf, scene.get("probabilities", {})
            pick_note = (f"scene={scene_pick}({scene_conf:.2f}) dir={dir_pick} "
                         f"door_c={door_c:.2f} blocked={blocked}"
                         + (f" target={tname} tbear={tbear:.0f} tdist={tdist:.0f}"
                            if tname else ""))

        result = ""
        if not args.observe_only:
            if pick == "steer":
                _, tbear, _ = parse_target(telem)
                proportional_turn(tbear or 0.0)
                pick = f"steer({tbear:.0f}deg)" if tbear is not None else "steer"
            else:
                ACT.get(pick, ACT["wait"])()
            time.sleep(args.sleep)
            telem2 = telemetry(args.hint)
            result = diff(telem, telem2)
            act_streak = act_streak + 1 if pick == "activate" and "gui" not in result else 0

        history.append((pick, result))
        history = history[-4:]


        top3 = sorted(probs.items(), key=lambda kv: -kv[1])[:3]
        print(f"[{tick}] {regime:4s} -> {pick:12s} conf={conf:.2f} "
              f"top={top3} {dt*1000:.0f}ms"
              + (f"\n     {pick_note}" if regime == "game" else "")
              + (f"\n     telem: {telem[:200]}" if telem else "")
              + (f"\n     delta: {result}" if result else ""))
        tr.write(json.dumps({"tick": tick, "regime": regime, "pick": pick,
                             "conf": conf, "probs": probs, "state": state,
                             "answers": {k: v for k, v in answers.items()},
                             "telemetry": telem, "delta": result,
                             "landmarks": landmarks,
                             "frame": frame_path}) + "\n")
        tr.flush()

    tr.close()
    print("transcript:", tr_path)


def build_state(task, telem, history, regime, landmarks=()):
    s = [f"You are playing the open-world RPG Morrowind on a gamepad. GOAL: {task}."]
    s.append("The crosshair is the small dot at the center of the frame. "
             "Translucent on-screen touch-control overlays (circles, icons, "
             "bars) are drawn over the frame; ignore them.")
    s.append("Telemetry fields: faced = name of the object currently under "
             "your crosshair (empty string = unnamed wall/furniture, none = "
             "nothing), fdist = its distance (64 units = 1 meter). Doors and "
             "NPCs show their names in faced; walls do not.")
    if regime == "menu":
        s.append("A menu or dialog window is currently open; gamepad buttons "
                 "navigate it.")
    if telem:
        s.append(f"Current telemetry: {telem}")
    if landmarks:
        seen = "; ".join(f"{n} at yaw={y:.0f} dist={d if d else '?'}"
                         for n, y, d in landmarks)
        s.append(f"Named objects your crosshair has swept over this session: {seen}.")
    if history:
        s.append("Recent actions and their engine results: " + "; ".join(
            f"{a} ({r or 'no engine change'})" for a, r in history))
    return " ".join(s)


def diff(before, after):
    """Compact engine-state delta between two telemetry lines."""
    if not after or before == after:
        return ""
    parts = []
    for key in ("cell", "faced", "target"):
        b = re.search(rf"{key}='([^']*)'", before or "")
        a = re.search(rf"{key}='([^']*)'", after)
        if a and a.group(1) != (b.group(1) if b else None):
            parts.append(f"{key}={a.group(1)}")
    b = re.search(r"gui=(-?\d+)", before or "")
    a = re.search(r"gui=(-?\d+)", after)
    if a and a.group(1) != (b.group(1) if b else None):
        parts.append(f"gui {b.group(1) if b else '?'}->{a.group(1)}")
    return ", ".join(parts)


if __name__ == "__main__":
    main()
