# Jeff-driven gamepad control loop

`omwjeff.py` closes the loop between the [Jeff](https://github.com/firelex/jeff)
System-1 model (`http://10.126.191.1:8765`) and the running debug build:
each tick it screencaps the device, pulls one `[Android DebugState]`
telemetry line (patch `0011-android-debug-telemetry`), asks Jeff a small set
of questions about the frame, and executes the mapped gamepad action through
the `DebugInputReceiver` broadcast surface.

## Architecture: reason in code, decide with Jeff

Jeff-Qwen3.5-0.8B is a classifier, not a planner (its own README says so).
What actually worked over five iterations of live runs:

1. **v1 "pick the next action from 11 options"** — degenerate. Zero-shot
   confidence on unfamiliar dark frames is ~0.1-0.2; the model settles on
   safe-sounding options (`wait`) or repeats one turn forever.
2. **v3 "fewer options + bigger pulses"** — better but still timid in dark
   interiors.
3. **v4 (current): Jeff answers *perception* questions, code picks the
   action.** One request per tick carries three questions:
   - `scene` (choice): wall / open_path / stairs_up / stairs_down / door /
     npc / clutter / void — what is directly ahead;
   - `promising` (choice): which direction serves the goal
     (straight_ahead / left / right / behind);
   - `door_centered` (noul).
   The harness policy maps that (plus telemetry: `faced` object name,
   distances, hint-target bearing) to one gamepad primitive. In bright
   scenes Jeff's scene confidence reaches 0.7-0.9; in the dark basements of
   the Balmora Guild of Mages it read walls as open floor (0.2-0.37) and
   the run descended two levels into a corner. Vision quality bounds this
   loop — outdoor/daylight and lit interiors are its element.
4. **Hinted-target steering**: with `--hint Caius` the telemetry carries
   `target=<name> tbearing=<deg> tdist=<units>`; the code then runs the
   engine-side `SERVO face <hint>` primitive (a frame-rate closed look
   loop that finishes aligned within ~1.5°), walks with `SERVO walk`
   (stops itself when blocked), and **Jeff gates the activation**
   (scene==npc). This took Caius from "six blind activation attempts" to a
   hands-free steer → walk → activate → dialog-open sequence. Since patch
   0012 the entire steering path lives on the engine: forward/turn are
   SERVO primitives, back/strafe/look are JOY_STATE on-device holds
   (verified: walks of 150-220 units per tick vs ~50 with raw pulses);
   only the activate/attack trigger crossings remain plain pulses.

When a menu/dialog is open (telemetry `gui != -1`) the loop switches to a
menu action set (dpad/A/B/Y) and Jeff picks those directly — it drove the
Caius dialog (asked topics, said Goodbye) and recovered from its own stray
B-press opening the inventory in game view.

## Usage

```sh
cd openmw-android/adb/jeff
OMW_SERIAL=642264a2 nix-shell -p python312 python312Packages.pillow --run \
  'python3 omwjeff.py --hint Caius \
     --task "Walk to Caius Cosades and start a conversation with him." \
     --ticks 18 --transcript /tmp/jeff_run.jsonl'
```

- `--task` goes into every tick's state text verbatim.
- `--hint <name>` enables the nearest-actor target line (telemetry).
- `--menu` forces the menu action set; otherwise `gui` telemetry chooses.
- `--observe-only` skips actuation (perception rehearsal).
- Every tick: transcript JSONL row + frame JPEG under `/tmp/omwjeff_frames/`.

Per-tick wall time is dominated by the Jeff server: ~10 s text-only,
~16-20 s with one image (measured 2026-10-02; the README's 22 ms figure
needs their GPU class). Image size (480-960 px) makes no difference to
that cost, so frames are sent at 960 px.

## What Jeff was asked (request shape)

POST `/v1/systemone` `{model, questions, images, state}` — unchanging
fields first, changing `state` last (their prompt-cache advice); images are
base64 **data URLs** (`data:image/jpeg;base64,...`), max 4. Answers:
`{choice, confidence, probabilities{...}}` per choice question, `{noul:
p}` for yes/no. Option keys must be short words, never numbers.

## Engine-side knobs the loop relies on

- Left trigger (axis 4) = Activate in game view; fire as a pulse ≥350 ms.
- B (keycode 97) is Inventory in game view but Goodbye/Cancel in menus —
  the same press means different things per regime; the loop's regime
  switch prevents most crossfire but not an unlucky tick.
- Idle orbit camera engages after ~30 s without input; the loop sends a
  neutral axis event each tick so the camera stays where Jeff left it.
- The on-screen touch overlay (sticks, icons) is drawn on every frame;
  Jeff is told to ignore it in the state text.
