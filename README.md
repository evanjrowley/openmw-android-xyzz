# OpenMW for Android — OpenMW 0.51.0

[![CI](https://github.com/evanjrowley/openmw-android-xyzz/actions/workflows/ci.yml/badge.svg?branch=openmw-0.51)](https://github.com/evanjrowley/openmw-android-xyzz/actions/workflows/ci.yml)

Android port of [OpenMW](https://openmw.org/) **0.51.0**, a modern open-source
reimplementation of The Elder Scrolls III: Morrowind. This fork revives the
archived OpenMW for Android project (the 0.48-era codebase) and updates it to
OpenMW 0.51.0 for modern arm64-v8a devices — developed and tested on a
Retroid Pocket 6.

Actively developed on the `openmw-0.51` branch.

> [!NOTE]
> This fork was **vibe coded** — the entire 0.51.0 update was developed with
> an AI coding agent. See
> [Credits — Artificial Intelligence (AI)](#artificial-intelligence-ai).

## Status

* The engine is upstream **OpenMW 0.51.0** with an Android runtime patch
  series (rendering, input, lifecycle) carried in this repository.
* CI builds the APK from a clean checkout on every push to `openmw-0.51`
  (see `.github/workflows/ci.yml`); the APK and unstripped `libopenmw.so`
  are published as workflow artifacts. Release builds are tagged
  (e.g. `0.51.0-50`).
* On the Retroid Pocket 6, the **Analog** and **Digital** trigger switch
  modes are supported: L2/R2 work in-game (Activate/Use) and in the
  controller menus. The **Both** trigger mode is not supported — it
  double-reports trigger events in menus.
* This fork is not distributed through Google Play or F-Droid, and it is
  not affiliated with https://omw.xyz.is/ — build it yourself or grab the
  artifacts from the Actions/Releases tabs.

**You must supply your own game data files** from a legitimately obtained
copy of The Elder Scrolls III: Morrowind (point the launcher at the
Morrowind `Data Files` directory on first launch).

## Building

Everything is managed declaratively with [Nix](https://nixos.org/) (see
`flake.nix`): the Android SDK/NDK (r28.2), OpenJDK 17, cmake, ninja, ccache
and autotools. The only host requirement is Nix with flakes enabled.

The build has three steps: the C/C++ dependency layer, the OpenMW engine
itself, and the Java launcher (APK).

### Prerequisites

A checkout of upstream OpenMW at the `openmw-0.51.0` tag as a git worktree
next to this repository (the engine build expects it at `../openmw-0.51`;
CI performs this step automatically):

```
git clone https://github.com/OpenMW/openmw.git
git -C openmw worktree add ../openmw-0.51 openmw-0.51.0
```

### Step 1: Build the dependency layer

From the `buildscripts` directory:

```
nix develop -c bash -c './build.sh --arch arm64 --ccache'
```

Downloads and cross-compiles the dependencies (Boost, SDL2, OpenAL, FFmpeg,
gl4es, LuaJIT, lz4, …), installing them into `buildscripts/prefix/<arch>`
and copying the shared libraries into `app/src/main/jniLibs/`.

### Step 2: Build the host ICU (once)

```
nix develop -c bash build-icu-host.sh
```

Builds the host-side ICU 70.1 required by OpenMW's ICU cross-build.
Idempotent; only needed the first time (or after `buildscripts/icu-host`
is removed).

### Step 3: Build the OpenMW engine

```
nix develop -c bash -c './build-openmw.sh'
```

Cross-builds `libopenmw.so` from the OpenMW source tree (applying the
Android patch series under `buildscripts/patches/`), copies it into
`app/src/main/jniLibs/` and deploys the engine assets (vfs, shaders,
defaults) into `app/src/main/assets/`.

### Step 4: Build the APK

From the repository root:

```
nix develop -c ./gradlew assembleNightlyDebug
```

The resulting APK lands at
`app/build/outputs/apk/nightly/debug/omw_debug_<version>.apk`; transfer it
to the device and install. `assembleMainlineDebug` builds the non-nightly
variant.

## CI

GitHub Actions (`.github/workflows/ci.yml`) runs the same pipeline from a
clean checkout on every push to `openmw-0.51` and publishes the APK and an
unstripped `libopenmw.so` as workflow artifacts. The dependency-layer
caches (Nix store, ICU, prefix, ccache) make follow-up runs substantially
faster than the first.

## Notes for developers

### Debugging native code

You can debug native code with `ndk-gdb`. To use it, once you've built the
libraries and the APK and installed the APK, run the application and let it
stay on the main menu. Then `cd` to `app/src/main` and run `./gdb.sh [arch]`.
The `arch` variable has to match the library your device will use
(`arm64` is the relevant one for this port).

This also automatically enables gdb to use unstripped libraries, so you get
proper symbols, source code references, etc.

### Engine patches

The Android-specific engine changes live under `buildscripts/patches/`:
`openmw-0.51/` (the OpenMW patch series, applied by `build-openmw.sh` on a
pristine source tree) and `sdl2/` (the SDL Android controller-mapping fix).
`patches/openmw-0.51-android/` contains the vendored reference patch stack
that the engine build applies first.

## Credits

This port stands on several sources. The branches, patches and projects
below are what made the 0.51 port possible.

### Source code

- **[OpenMW](https://github.com/OpenMW/openmw)** (tag `openmw-0.51.0`) —
  the engine itself, cross-built from upstream source. © The OpenMW team,
  GPL-3.0. Home page: [openmw.org](https://openmw.org/).
- **[xyzz/openmw-android](https://github.com/xyzz/openmw-android)** — the
  base codebase this fork continues (the archived 0.48-era Android port).
  Original Java code by sandstranger, Ilya Zhuravlev (xyzz) and
  contributors; build scripts originally by sandstranger and bwhaines.
- **[Andiweli/OpenMW-Android](https://github.com/Andiweli/OpenMW-Android)**
  — the OpenMW 0.51 Android runtime this port adopted (their patch stack,
   vendored under `buildscripts/patches/openmw-0.51-android/` and applied
  by the engine build): GL4ES shader compatibility, the post-processing
  and shadow rework, explicit object fog, the surface lifecycle bridge, the
  loading screen and controller-input fixes, and much of the current on-device
  behavior. © Andiweli and contributors.

### Libraries and translation layer

- **[ptitSeb/gl4es](https://github.com/ptitSeb/gl4es)** and the
  **[sisah2/gl4es](https://github.com/sisah2/gl4es)** fork (pinned
  `5ac069d8`, built with the patches under `buildscripts/patches/gl4es/`) —
  the desktop-OpenGL-to-GLES translation layer that lets the 0.51 renderer
  run on Adreno GLES2. © ptitSeb, sisah2 and contributors.
- **[libsdl-org/SDL](https://github.com/libsdl-org/SDL)** (release-2.30.12)
  — window, input and EGL glue, with an Android controller-mapping patch
  under `buildscripts/patches/sdl2/`.
- **[codekidX/storage-chooser](https://github.com/codekidX/storage-chooser)**
  (vendored under `storagechooser/`) — the in-app game-directory picker.
- The remaining dependency layer builds from upstream releases: Boost
  1.83, OpenAL 1.23.1, FFmpeg 6.1.2, LuaJIT, lz4, freetype, libpng,
  libjpeg-turbo, sqlite, YAML-CPP, RecastNavigation, Bullet, MyGUI 3.4.3
  and [ICU 70.1](https://github.com/unicode-org/icu/releases/tag/release-70-1)
  (the host build required by OpenMW's ICU cross-build).

### Build and CI tooling

- **[Nix](https://github.com/NixOS/nix)** and
  [NixOS/nixpkgs](https://github.com/NixOS/nixpkgs) — the declarative build
  environment (`flake.nix`: Android SDK/NDK r28.2, OpenJDK 17, cmake,
  ninja, ccache).
- [DeterminateSystems/nix-installer-action](https://github.com/DeterminateSystems/nix-installer-action),
  [nix-community/cache-nix-action](https://github.com/nix-community/cache-nix-action)
  and GitHub's official [actions/checkout](https://github.com/actions/checkout),
  [actions/cache](https://github.com/actions/cache) and
  [actions/upload-artifact](https://github.com/actions/upload-artifact) —
  the CI pipeline in `.github/workflows/ci.yml`.

### Artificial Intelligence (AI)

- **[ZCode](https://z.ai)** — the AI coding agent used to develop this fork
  end to end (the 0.51.0 port, the Android runtime patches, the build
  system and CI), powered by **GLM-5.3-Flash** from Z.ai / Zhipu AI's
  [September 2026 GLM-5.3-Flash Usage Campaign](https://docs.z.ai/devpack/notice/event-glm-5.3-flash). 
  All AI-generated work was developed and verified inside an isolated
  development VM to compensate for both [known and realized risks](https://news.ycombinator.com/item?id=49750694).
