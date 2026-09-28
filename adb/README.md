# ADB gamepad test helpers

Drive the running OpenMW debug build (`is.xyz.omw_nightly.debug`) the same
way the handheld's physical controls do — via the debug-only
`DebugInputReceiver` broadcast surface and the engine-side telemetry
(`0011-android-debug-telemetry.patch`). Requires the game to be running;
screenshots (`adb shell screencap`) remain the only *visual* check.

| script | purpose |
| --- | --- |
| `joy.sh` | raw injection: axis / pulse / stick / button tap (Android keycodes) |
| `state.sh [hint]` | one `[Android DebugState]` line: pos, yaw/pitch, cell, GUI mode, crosshair focus, nearest actor matching hint (bearing + distance) |
| `con.sh 'cmd'` | run one OpenMW console command (console open/clear/type/Enter/close) |
| `coc.sh "Cell, Name"` | `coc` teleport + post-load telemetry |
| `lookat.sh NAME [--walk] [--activate]` | closed-loop camera aim (calibrated turns), optional approach + activate |

Environment: `OMW_SERIAL` to target a device (`adb -s`), `OMW_PKG` to
override the package. `OMW_LOG` overrides the openmw.log path
(default `/sdcard/omw_nightly/config/openmw.log`).

Typical repeatable session:

```sh
adb shell input keyevent 61                     # (only if needed)
adb/joy.sh tap 20; adb/joy.sh tap 96            # main menu: New, confirm
# ... name dialog: adb shell input text ...; adb/joy.sh tap 96
adb/con.sh 'coc "Balmora, Caius Cosades'"'"' House"'
adb/con.sh 'enableplayercontrols'
adb/con.sh 'enableplayerviewswitch'
adb/lookat.sh "Caius Cosades" --walk --activate
```

Keycodes: A=96 B=97 X=99 Y=100 L1=102 R1=103 L3=106 R3=107, dpad 19-22,
start=108 select=109. Activate in-game is the LEFT TRIGGER (axis 4), not A.
