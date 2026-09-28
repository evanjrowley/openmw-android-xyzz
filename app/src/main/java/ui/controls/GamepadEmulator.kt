/*
    Copyright (C) 2018, 2019 Ilya Zhuravlev

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

package ui.controls

import org.libsdl.app.SDLControllerManager

internal object GamepadEmulator {

    // random device ID to make sure it doesn't conflict with anything
    internal const val VIRTUAL_DEVICE_ID = 1384510555

    private var registered = false

    internal val isRegistered: Boolean
        get() = registered

    private fun ensureRegistered() {
        // Registering before the joystick subsystem is up would set the flag
        // while SDL drops the device, leaving the touch sticks dead for the
        // whole session. pollInputDevices() only runs once SDL is ready.
        if (registered || !SDLControllerManager.joystickSubsystemReady) return
        registered = true
        SDLControllerManager.nativeAddJoystick(VIRTUAL_DEVICE_ID, "Virtual", "Virtual",
            0xbad, 0xf00d,
            false, -0x1,
            // axis_mask = LEFTX|LEFTY: SDL's Android auto-mapping only adds
            // leftx/lefty bindings for axis-mask bits, so without this the
            // virtual stick axes are unbound and the stick does nothing.
            4, 0x0003, 0, 0)
    }

    fun updateStick(stickId: Int, x: Float, y: Float) {
        ensureRegistered()
        SDLControllerManager.onNativeJoy(VIRTUAL_DEVICE_ID, stickId * 2, x)
        SDLControllerManager.onNativeJoy(VIRTUAL_DEVICE_ID, stickId * 2 + 1, y)
    }

    fun sendAxis(axis: Int, value: Float) {
        ensureRegistered()
        SDLControllerManager.onNativeJoy(VIRTUAL_DEVICE_ID, axis, value)
    }

    fun sendButton(keycode: Int, down: Boolean) {
        ensureRegistered()
        if (down) {
            SDLControllerManager.onNativePadDown(VIRTUAL_DEVICE_ID, keycode)
        } else {
            SDLControllerManager.onNativePadUp(VIRTUAL_DEVICE_ID, keycode)
        }
    }

}
