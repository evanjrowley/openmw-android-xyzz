/*
    This file is part of OpenMW-Android.

    OpenMW-Android is free software: you can redistribute it and/or modify
    it under the terms of the GNU General Public License as published by
    the Free Software Foundation, either version 3 of the License, or
    (at your option) any later version.

    OpenMW-Android is distributed in the hope that it will be useful,
    but WITHOUT ANY WARRANTY; without even the implied warranty of
    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
    GNU General Public License for more details.

    You should have received a copy of the GNU General Public License
    along with OpenMW-Android.  If not, see <https://www.gnu.org/licenses/>.
*/

package debug

import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.util.Log
import android.view.InputDevice
import android.view.KeyEvent
import org.libsdl.app.SDLControllerManager
import ui.controls.GamepadEmulator

/**
 * Debug-only bridge that turns ADB broadcasts into real SDL controller
 * events, so automation can exercise the same input path as the handheld's
 * physical controls (analog axes, controller buttons) instead of the
 * keyboard/touch that `input keyevent`/`input tap` reach.
 *
 * GameActivity registers this receiver only when
 * [android.content.pm.ApplicationInfo.FLAG_DEBUGGABLE] is set, so release
 * builds carry the class but never listen for the actions.
 *
 * Examples (with the game running):
 * ```
 * adb shell am broadcast -p is.xyz.omw_nightly.debug \
 *     -a is.xyz.omw.debug.JOY_AXIS --ei axis 1 --ef value -1.0 --ei device 3
 * adb shell am broadcast -p is.xyz.omw_nightly.debug \
 *     -a is.xyz.omw.debug.JOY_STICK --ei stick 0 --ef x 1.0 --ef y 0.0
 * adb shell am broadcast -p is.xyz.omw_nightly.debug \
 *     -a is.xyz.omw.debug.JOY_PULSE --ei axis 1 --ef value -0.8 --ei duration_ms 400
 * adb shell am broadcast -p is.xyz.omw_nightly.debug \
 *     -a is.xyz.omw.debug.PAD_BUTTON --ei keycode 96 --ez down true
 * adb shell am broadcast -p is.xyz.omw_nightly.debug \
 *     -a is.xyz.omw.debug.STATE --es hint "Caius Cosades"
 * adb shell am broadcast -p is.xyz.omw_nightly.debug -a is.xyz.omw.debug.INFO
 * ```
 *
 * `device` is the Android InputDevice id (see the INFO action); it defaults
 * to the on-screen sticks' virtual device. Axis values are floats in
 * [-1; 1]; `keycode` is an Android keycode (96=A, 97=B, 98=X, 99=Y, 102=L2,
 * 103=R2, 108=start, 109=back, 19-22=dpad).
 *
 * JOY_PULSE holds an axis at `value` for `duration_ms` (release to 0 is
 * scheduled on-device), so pulse timing carries no ADB latency jitter —
 * calibrated camera turns stay reproducible.
 *
 * STATE asks the engine (see ControllerManager::androidDebugPoll in the
 * OpenMW patch series) to log a [Android DebugState] line to openmw.log:
 * player position/yaw/pitch, cell, GUI mode, the crosshair focus object,
 * and — when `hint` is given — the nearest actor whose name matches the
 * hint, with its bearing (degrees, relative to current yaw) and distance.
 */
class DebugInputReceiver(private val engineReady: () -> Boolean) : BroadcastReceiver() {

    override fun onReceive(context: Context, intent: Intent) {
        when (val action = intent.action) {
            ACTION_INFO -> logDeviceInfo()
            ACTION_STATE -> requestEngineState(intent)
            ACTION_JOY_AXIS, ACTION_JOY_STICK, ACTION_JOY_PULSE, ACTION_PAD_BUTTON,
            ACTION_JOY_STATE, ACTION_SERVO, ACTION_STREAM, ACTION_LOAD_SAVE, ACTION_ROUTE, ACTION_PROBE, ACTION_TELEM -> {
                if (!engineReady()) {
                    Log.i(TAG, "$action ignored: engine not running")
                    return
                }
                try {
                    inject(action, intent)
                } catch (e: Throwable) {
                    Log.e(TAG, "injection failed for $action", e)
                }
            }
        }
    }

    private fun inject(action: String, intent: Intent) {
        when (action) {
            ACTION_JOY_AXIS -> {
                val axis = intent.getIntExtra(EXTRA_AXIS, -1)
                val value = intent.getFloatExtra(EXTRA_VALUE, 0f).coerceIn(-1f, 1f)
                if (axis >= 0) {
                    sendAxis(resolveDevice(intent), axis, value)
                    Log.i(TAG, "joy axis=$axis value=$value")
                }
            }
            ACTION_JOY_PULSE -> {
                val axis = intent.getIntExtra(EXTRA_AXIS, -1)
                val value = intent.getFloatExtra(EXTRA_VALUE, 0f).coerceIn(-1f, 1f)
                val durationMs = intent.getIntExtra(EXTRA_DURATION_MS, 0).coerceAtLeast(0)
                if (axis >= 0 && durationMs > 0) {
                    val device = resolveDevice(intent)
                    sendAxis(device, axis, value)
                    pulseHandler.postDelayed({ sendAxis(device, axis, 0f) }, durationMs.toLong())
                    Log.i(TAG, "joy pulse axis=$axis value=$value ms=$durationMs")
                }
            }
            ACTION_JOY_STICK -> {
                val stick = intent.getIntExtra(EXTRA_STICK, 0)
                val x = intent.getFloatExtra(EXTRA_X, 0f).coerceIn(-1f, 1f)
                val y = intent.getFloatExtra(EXTRA_Y, 0f).coerceIn(-1f, 1f)
                val device = resolveDevice(intent)
                if (device == GamepadEmulator.VIRTUAL_DEVICE_ID) {
                    GamepadEmulator.updateStick(stick, x, y)
                } else {
                    sendAxis(device, stick * 2, x)
                    sendAxis(device, stick * 2 + 1, y)
                }
                Log.i(TAG, "stick=$stick x=$x y=$y device=$device")
            }
            ACTION_PAD_BUTTON -> {
                val keycode = intent.getIntExtra(EXTRA_KEYCODE, -1)
                val down = intent.getBooleanExtra(EXTRA_DOWN, true)
                if (keycode >= 0) {
                    val device = resolveDevice(intent)
                    if (device == GamepadEmulator.VIRTUAL_DEVICE_ID) {
                        GamepadEmulator.sendButton(keycode, down)
                    } else if (down) {
                        SDLControllerManager.onNativePadDown(device, keycode)
                    } else {
                        SDLControllerManager.onNativePadUp(device, keycode)
                    }
                    Log.i(TAG, "pad ${if (down) "down" else "up"} keycode=$keycode " +
                        "(${KeyEvent.keyCodeToString(keycode)}) device=$device")
                }
            }
            ACTION_JOY_STATE -> {
                val durationMs = intent.getIntExtra(EXTRA_DURATION_MS, 0).coerceAtLeast(0)
                nativeJoyState(
                    intent.getFloatExtra(EXTRA_X, 0f),
                    intent.getFloatExtra(EXTRA_Y, 0f),
                    intent.getFloatExtra(EXTRA_RX, 0f),
                    intent.getFloatExtra(EXTRA_RY, 0f),
                    intent.getFloatExtra(EXTRA_LT, 0f),
                    intent.getFloatExtra(EXTRA_RT, 0f),
                    durationMs)
                Log.i(TAG, "joy state ms=$durationMs")
            }
            ACTION_SERVO -> {
                val kind = intent.getStringExtra(EXTRA_KIND) ?: "cancel"
                when (kind) {
                    "cancel" -> nativeServoCancel()
                    "turn" -> nativeServo(1, intent.getFloatExtra(EXTRA_DEG, 0f), 0, "")
                    "face" -> nativeServo(2, 0f, 0, intent.getStringExtra(EXTRA_HINT) ?: "")
                    "walk" -> nativeServo(3, 0f,
                        intent.getIntExtra(EXTRA_DURATION_MS, 2000).coerceAtLeast(0), "")
                    "goto" -> nativeServo(4, 0f, 0, intent.getStringExtra(EXTRA_HINT) ?: "")
                    else -> Log.w(TAG, "unknown servo kind=$kind")
                }
                Log.i(TAG, "servo kind=$kind")
            }
            ACTION_STREAM -> {
                val period = intent.getIntExtra(EXTRA_PERIOD, 0).coerceAtLeast(0)
                nativeStream(period)
                Log.i(TAG, "stream period=$period")
            }
            ACTION_LOAD_SAVE -> {
                val path = intent.getStringExtra(EXTRA_PATH) ?: ""
                if (path.isNotEmpty()) {
                    nativeLoadSave(path)
                    Log.i(TAG, "load save path=$path")
                }
            }
            ACTION_ROUTE -> {
                val hint = intent.getStringExtra(EXTRA_HINT) ?: ""
                nativeRoute(hint)
                Log.i(TAG, "route hint=$hint")
            }
            ACTION_PROBE -> {
                val dx = intent.getFloatExtra("dx", 0f)
                val dy = intent.getFloatExtra("dy", 0f)
                val dist = intent.getFloatExtra("dist", 250f)
                nativeProbe(dx, dy, dist)
                Log.i(TAG, "probe dx=$dx dy=$dy dist=$dist")
            }
            ACTION_TELEM -> {
                val on = intent.getBooleanExtra("on", false)
                nativeTelem(on)
                Log.i(TAG, "telem on=$on")
            }
        }
    }

    private fun sendAxis(deviceId: Int, axis: Int, value: Float) {
        if (deviceId == GamepadEmulator.VIRTUAL_DEVICE_ID) {
            GamepadEmulator.sendAxis(axis, value)
        } else {
            SDLControllerManager.onNativeJoy(deviceId, axis, value)
        }
    }

    // First joystick-class input device (the handheld's built-in controller),
    // since injection without an explicit target almost certainly means
    // "drive the game the way the physical controls would".
    private fun resolveDevice(intent: Intent): Int {
        val requested = intent.getIntExtra(EXTRA_DEVICE, -1)
        if (requested >= 0) return requested
        for (id in InputDevice.getDeviceIds()) {
            val device = InputDevice.getDevice(id) ?: continue
            if (device.sources and InputDevice.SOURCE_CLASS_JOYSTICK != 0) return id
        }
        return GamepadEmulator.VIRTUAL_DEVICE_ID
    }

    private fun logDeviceInfo() {
        for (id in InputDevice.getDeviceIds()) {
            val device = InputDevice.getDevice(id) ?: continue
            Log.i(TAG, "InputDevice id=$id name='${device.name}' " +
                "sources=0x${Integer.toHexString(device.sources)}")
        }
        Log.i(TAG, "engineReady=${engineReady()} " +
            "virtualRegistered=${GamepadEmulator.isRegistered}")
    }

    // The engine answers asynchronously on its own thread: it logs one
    // "[Android DebugState]" line to openmw.log. Both entry points are
    // fired: the legacy 0011 poll (works even while controls are disabled)
    // and the 0012 census/servo tick (superset line, game view only) —
    // whichever runs last in a frame writes the richer line the harness
    // reads with `tail -1`.
    private fun requestEngineState(intent: Intent) {
        if (!engineReady()) {
            Log.i(TAG, "STATE ignored: engine not running")
            return
        }
        val hint = intent.getStringExtra(EXTRA_HINT) ?: ""
        try {
            nativeDebugRequest(hint)
        } catch (e: Throwable) {
            Log.e(TAG, "legacy state request failed", e)
        }
        try {
            nativeDebugState2(hint)
            Log.i(TAG, "state requested")
        } catch (e: Throwable) {
            Log.e(TAG, "state v2 request failed (old engine build?)", e)
        }
    }

    companion object {
        private const val TAG = "OmwDebugInput"
        private val pulseHandler = android.os.Handler(android.os.Looper.getMainLooper())

        @JvmStatic
        private external fun nativeDebugRequest(hint: String)

        @JvmStatic
        private external fun nativeDebugState2(hint: String)

        @JvmStatic
        private external fun nativeServo(kind: Int, deg: Float, ms: Int, hint: String)

        @JvmStatic
        private external fun nativeServoCancel()

        @JvmStatic
        private external fun nativeStream(periodFrames: Int)

        @JvmStatic
        private external fun nativeRoute(hint: String)

        @JvmStatic
        private external fun nativeProbe(dx: Float, dy: Float, dist: Float)

        @JvmStatic
        private external fun nativeTelem(on: Boolean)

        @JvmStatic
        private external fun nativeLoadSave(path: String)

        @JvmStatic
        private external fun nativeJoyState(x0: Float, y0: Float, rx: Float, ry: Float,
            lt: Float, rt: Float, durationMs: Int)

        const val ACTION_JOY_AXIS = "is.xyz.omw.debug.JOY_AXIS"
        const val ACTION_JOY_STICK = "is.xyz.omw.debug.JOY_STICK"
        const val ACTION_JOY_PULSE = "is.xyz.omw.debug.JOY_PULSE"
        const val ACTION_JOY_STATE = "is.xyz.omw.debug.JOY_STATE"
        const val ACTION_PAD_BUTTON = "is.xyz.omw.debug.PAD_BUTTON"
        const val ACTION_SERVO = "is.xyz.omw.debug.SERVO"
        const val ACTION_STREAM = "is.xyz.omw.debug.STREAM"
        const val ACTION_LOAD_SAVE = "is.xyz.omw.debug.LOAD_SAVE"
        const val ACTION_ROUTE = "is.xyz.omw.debug.ROUTE"
        const val ACTION_PROBE = "is.xyz.omw.debug.PROBE"
        const val ACTION_TELEM = "is.xyz.omw.debug.TELEM"
        const val ACTION_STATE = "is.xyz.omw.debug.STATE"
        const val ACTION_INFO = "is.xyz.omw.debug.INFO"

        const val EXTRA_AXIS = "axis"
        const val EXTRA_VALUE = "value"
        const val EXTRA_STICK = "stick"
        const val EXTRA_X = "x"
        const val EXTRA_Y = "y"
        const val EXTRA_RX = "rx"
        const val EXTRA_RY = "ry"
        const val EXTRA_LT = "lt"
        const val EXTRA_RT = "rt"
        const val EXTRA_KEYCODE = "keycode"
        const val EXTRA_DOWN = "down"
        const val EXTRA_DEVICE = "device"
        const val EXTRA_DURATION_MS = "duration_ms"
        const val EXTRA_HINT = "hint"
        const val EXTRA_KIND = "kind"
        const val EXTRA_DEG = "deg"
        const val EXTRA_PERIOD = "period"
        const val EXTRA_PATH = "path"
    }
}
