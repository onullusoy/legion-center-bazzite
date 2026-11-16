<div align="center">

<img src="assets/Icon.png" alt="Legion Center logo" width="120" />

# Legion Center — Bazzite Edition

**Fan curves, lighting, charge limit and controller tools for the Lenovo Legion Go on Bazzite.**
A [Decky Loader](https://decky.xyz) plugin for Gaming Mode.

[![License: BSD-3-Clause](https://img.shields.io/badge/license-BSD--3--Clause-blue.svg)](LICENSE)
![Bazzite](https://img.shields.io/badge/Bazzite-45-6f42c1)
![Decky Loader](https://img.shields.io/badge/Decky-Loader-1a9fff)
![Device](https://img.shields.io/badge/Lenovo-Legion%20Go-e2231a)
![Status](https://img.shields.io/badge/status-community%20tested-orange)

</div>

> 🙏 Built on top of [**Legion Center** by InnoVision Games](https://github.com/InnoVision-Games/legion-center). Huge thanks to them and the handheld Linux community. This is an independent community project, **not** an official Lenovo, Bazzite or InnoVision Games release.

---

## ✨ Features

| | Menu | What you get |
| --- | --- | --- |
| 🌀 | **Fan Control** | 3 editable profiles, inline temperature sliders, reset to recommended, firmware read-back verification |
| 💡 | **Lighting** | Awake / sleep power LED, joystick RGB, recoverable night mode |
| 🔋 | **Battery & Power** | 80% charge limit, opt-in AC / battery fan profiles, sleep battery summary |
| 🎮 | **Controller** | Experimental InputPlumber touchpad route (with undo), gyro motion test |
| 🩺 | **System** | Read-only diagnostics, resume health check, fan-support repair |

Everything is controller-friendly: each control has its own page, with a Back action and B-button navigation.

## ✅ Tested on

| Component | Version |
| --- | --- |
| Hardware | Lenovo Legion Go 8APU1 (83E1) |
| BIOS | N3CN39WW |
| OS | Bazzite deck-gnome 45.20261115 |
| Kernel | 7.3.4-ogc6.1.fc45.x86_64 |
| Input / power | InputPlumber, PowerStation, SteamOS Manager |

Other Bazzite images, kernels, firmware and Legion Go models need independent testing. Reports are welcome!

## 📦 Installation

**Requirements:** Bazzite, [Decky Loader](https://decky.xyz) already installed, plus Node.js, pnpm 8 and Python 3 to build.

```sh
git clone https://github.com/onullusoy/legion-center-bazzite.git
cd legion-center-bazzite

pnpm install --frozen-lockfile
pnpm check          # tests + type check + build
./install.sh        # asks for admin authentication
```

The installer backs up any existing plugin, keeps your Decky settings and restarts Decky Loader. Open **Decky → Legion Center** in Gaming Mode afterwards.

Want an archive instead of installing? Run `pnpm package` and find it in `artifacts/`.

### 🌀 Fan support prerequisite

Fan control needs the [`acpi_call`](https://github.com/nix-community/acpi_call) kernel module for your **running kernel** (`/proc/acpi/call` must exist). The installer does **not** install kernel modules or disable Bazzite's filesystem protections.

- The upstream SteamOS fan installer (`steamos-readonly`, `pacman`) does not work on Bazzite.
- After a kernel update the module must be rebuilt (matching headers and a compiler are required). If that isn't possible, the **System → repair** action reports a failure instead of pretending fan support is ready.
- Secure Boot setups have not been validated yet.

## 🚀 Quick start: fan profiles

1. In Gaming Mode open **Decky → Legion Center → Fan control**.
2. Enable **Custom fan control**.
3. Pick one of the three profile slots.
4. Drag the temperature sliders. Percentages are display-only, no keyboard popups.
5. **Reset to recommended** resets only the selected slot.

| Temp | 10° | 20° | 30° | 40° | 50° | 60° | 70° | 80° | 90° | 100° |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Fan | 44% | 48% | 55% | 60% | 71% | 79% | 87% | 87% | 100% | 100% |

The curve is always non-decreasing, with at least 87% at 70–80 °C and 100% at 90–100 °C. Values are firmware control values, not measured RPM, and firmware thermal protections stay on. The recommended curve is a conservative starting point from the tested unit, not a claim of optimal cooling for every device.

## 🔍 Good to know

- **Lighting:** RGB changes need an explicit Apply. Night mode snapshots all lighting before changing it and restores it afterwards.
- **Charge limit:** the toggle reads the hardware state back. Actual charge termination at 80% still needs to be observed over a real charge cycle.
- **AC / battery fan automation:** opt-in, only reacts to power transitions or **Apply matching profile**, never turns custom fan control on by itself.
- **Touchpad route:** experimental. It did not restore the physical touchpad in Steam Gaming Mode on the tested setup. See [Bazzite issue #5770](https://github.com/ublue-os/bazzite/issues/5770) for a possible workaround (HORIPAD Steam Controller target).
- **Gyro / resume checks:** read-only, they never restart InputPlumber or grab input devices.
- **Back buttons:** firmware remapping is not exposed; use Steam Input.

### Validated vs. still open

| ✅ Validated | ⏳ Not fully validated |
| --- | --- |
| Fan curve write and firmware read-back | Long gaming sessions across thermal / power conditions |
| Switching between profiles, persistence, invalid-curve rejection | Suspend/resume for every setting |
| Power LED changes, charge-limit state changes | Rebuilding fan support across kernel upgrades |
| 93 automated tests | Controller layout across Steam / Decky versions |

The tested unit exposes no fan RPM through standard hwmon, so a successful read-back confirms the requested table, not the physical fan speed.

## 🔄 Updates

This edition uses its own Bazzite version numbers (see `package.json`). The upstream reinstall/update action is hidden because it would overwrite this edition. Update by pulling the repo and running `./install.sh` again. More details in [docs/](docs/) ([automation](docs/automation.md), [roadmap](docs/roadmap.md)).

## 🤝 Contributing

Keep changes focused, name the affected model and firmware, and include how you validated it. Hardware-facing changes should verify the resulting device state and keep a recoverable previous configuration. Please remove usernames, home paths and serial numbers from any logs you share.

## 💜 Credits & license

- **InnoVision Games**: the original Legion Center project
- **Aarron Lee & LegionGoRemapper contributors**: earlier plugin lineage
- **hhd-dev, antheas, corando98**: Legion Go hardware protocol research
- **nix-community/acpi_call**: the kernel module behind fan control
- **Decky Loader, InputPlumber, Bazzite and the handheld Linux community**

Released under the [BSD 3-Clause License](LICENSE) with all original copyright notices preserved. See [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md) for details. `acpi_call` is a separate GPL module and is not relicensed here.
