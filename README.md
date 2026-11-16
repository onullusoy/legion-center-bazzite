# Legion Center — Bazzite Edition

Legion Center — Bazzite Edition adapts the [Legion Center](https://github.com/InnoVision-Games/legion-center) project for Bazzite and adds independently developed device controls and handheld-focused interface improvements for the original Lenovo Legion Go.

This project builds on the work of **InnoVision Games** and the handheld Linux community. It is not an official Lenovo or Bazzite project.

## Development status

This is a community-maintained project, not an official Lenovo, Bazzite, or InnoVision Games release. Hardware validation has been performed on one original Legion Go 8APU1 running Bazzite 45. Other Bazzite versions and Legion Go models need independent testing.

## Features

The home screen contains five short categories. Individual controls live on their own pages, with a Back action and controller B-button navigation.

| Menu | Controls |
| --- | --- |
| Fan Control | Three editable profiles, inline temperature sliders, reset to defaults, firmware verification |
| Lighting | Awake LED, sleep LED, joystick RGB, recoverable night mode |
| Battery & Power | Charge limit, opt-in AC/battery fan profiles, sleep battery summary |
| Controller | Experimental InputPlumber touchpad route and undo, bounded gyro motion test |
| System | Read-only diagnostics, resume health, fan-support repair |

All fan percentages are edited inline; numeric-entry popups are disabled. Night mode keeps a recovery snapshot and restores the previous lighting state. Power automation applies only on AC/battery transitions or an explicit Apply action, so it does not repeatedly override manual profile choices.

Firmware button remapping is not exposed in this edition. Configure back buttons through Steam Input on systems managed by InputPlumber.

## Compatibility

| Component | Tested configuration |
| --- | --- |
| Hardware | Lenovo Legion Go 8APU1, model 83E1 |
| BIOS | N3CN39WW |
| Operating system | Bazzite deck-gnome 45.20261115 |
| Kernel | 7.3.4-ogc6.1.fc45.x86_64 |
| Input management | InputPlumber |
| Performance management | PowerStation and SteamOS Manager |

Testing on one configuration does not establish support for every kernel, firmware revision, or Bazzite image.

## Using the fan profiles

1. Open **Decky → Legion Center → Fan control** in Gaming Mode.
2. Enable **Custom fan control**.
3. Select one of the three profile buttons.
4. Adjust each visible temperature row with its inline slider. Percentages are display-only; no numeric-entry popup is used.
5. Use **Reset to recommended** to reset only the selected slot.

The first slot preserves the existing fan curve during migration. The other two slots start with stronger cooling curves. All three slots can be edited. Changes are saved after firmware confirmation; a short debounce prevents a write for every controller input step.

The recommended curve is a conservative starting point based on the table read from the tested device. It is not a claim of optimal cooling or minimum noise for every unit.

| Temperature | 10°C | 20°C | 30°C | 40°C | 50°C | 60°C | 70°C | 80°C | 90°C | 100°C |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Recommended fan value | 44% | 48% | 55% | 60% | 71% | 79% | 87% | 87% | 100% | 100% |

The editor maintains a nondecreasing curve. It enforces a minimum of 87% at 70–80°C and 100% at 90–100°C. Displayed percentages are firmware control values, not measured RPM.

## Fan support on Bazzite

The fan backend requires `acpi_call` for the running kernel and the `/proc/acpi/call` interface. The local Bazzite integration uses a dedicated module-loading service rather than the upstream SteamOS installer.

The upstream fan installer uses `steamos-readonly`, `pacman`, and Valve kernel packages. That installation path is not compatible with Bazzite.

The module must match the running kernel. Rebuilding after an update requires matching kernel headers and a working compiler. If these are unavailable, the repair operation reports a failure instead of claiming that fan support is ready. A kernel upgrade and Secure Boot installation path have not yet been validated for public distribution.

## Lighting, battery, and power

Awake and sleep power-button lighting have separate controls. RGB changes require an explicit Apply action. Night mode snapshots all three lighting backends before changing them and verifies restoration; individual lighting edits are blocked until night mode is restored.

The charge-limit toggle reads the hardware state after changing it. Physical charge termination at 80% still requires observation during an actual charging cycle.

AC/battery fan automation is opt-in. Choose an existing fan slot for each power source, then either wait for a power transition or select Apply matching profile. It never enables custom fan control if the user has turned it off, and it does not add a competing TDP controller.

Sleep battery reports use real logind sleep/resume boundaries. A standard delay inhibitor protects the short entry sample and is released immediately after recording it; if protected sampling is unavailable, the cycle does not produce a loss estimate. No estimate is created without a valid matching record. A newly installed plugin shows no sleep history until a complete sleep cycle has been observed.

## Touchpad pointer route

Open **Controller → Touchpad pointer** to create or remove the plugin-owned InputPlumber touchpad target. This route is experimental. It was not confirmed to restore the physical touchpad in Steam Gaming Mode on the tested Bazzite configuration. A Bazzite issue reports that changing OpenGamepadUI's Target Gamepad Type to **HORIPAD Steam Controller** can restore the Legion Go touchpad in Gaming Mode; see [Bazzite issue #5770](https://github.com/ublue-os/bazzite/issues/5770). The profile and firmware behavior vary by system.

The plugin records ownership of the added route so **Undo pointer repair** removes only that route. If InputPlumber restarts or the session's input targets change, recheck the status and repair again if needed. The plugin never blindly restarts the controller service. Pointer movement and tapping must still be checked on the physical device.

## Gyro and resume diagnostics

The gyro page distinguishes advertised tablet/left/right capabilities from actual motion data. Its bounded motion test reads exposed tablet IIO values without grabbing input devices or changing filters. A zero-data result is not treated as proof of a broken sensor; left/right controller capabilities are not presented as verified motion streams.

Resume health checks controller presence, the saved fan preference, and firmware LED states. They are read-only and never restart InputPlumber or apply an unverified driver repair.

## Validation and limitations

Validated:

- Applying fan curves and reading the resulting table back from firmware.
- Switching between the two additional initial profile curves.
- Preserving the previous curve and enabled/disabled preference during installation.
- Profile isolation, persistence, invalid-curve rejection, and failure handling in automated tests.
- Power LED state changes and native charge-limit state transitions.

Not yet fully validated:

- Long gaming sessions across multiple thermal and power conditions.
- Suspend/resume behavior for every setting.
- Rebuilding and restoring support across kernel upgrades.
- Controller focus and layout across Steam and Decky versions.

The tested configuration does not expose fan RPM through the standard hwmon interface. A successful firmware read-back confirms the requested table, not the physical fan's measured speed. Firmware thermal protections remain enabled.

## Updates

This edition uses independent Bazzite version identifiers. The upstream reinstall/update action is not exposed because it would replace edition-specific changes. Community releases and update channels are maintained separately.

## Build and local installation

Requirements: Node.js, pnpm 8, Python 3, and an existing Decky Loader installation.

```sh
pnpm install --frozen-lockfile
pnpm check
./install.sh
```

The local installer requests administrator authentication, backs up the existing
plugin, and preserves the user's Decky settings. It does not install kernel
modules or disable Bazzite's filesystem protections. Fan support remains a
separate prerequisite.

To create an archive without installing it:

```sh
pnpm package
```

## Development and contributions

Keep changes focused, document the affected model and firmware, and include relevant validation. Hardware-facing changes should verify the resulting device state and preserve a recoverable previous configuration.

Public diagnostics must exclude usernames, home-directory paths, device serial numbers, and unrelated logs. Do not include local investigation artifacts or private settings in release archives.

## Credits and licensing

- **InnoVision Games** — the original Legion Center project.
- **Aarron Lee and LegionGoRemapper contributors** — the project's earlier plugin lineage.
- **hhd-dev, antheas, and corando98** — hardware protocol research and prior Legion Go work.
- **nix-community/acpi_call contributors** — the separate kernel module used by the fan backend.
- **Decky Loader, InputPlumber, and the Bazzite community** — supporting infrastructure.

Thank you to InnoVision Games and the Legion Center contributors for the original project, and to the Bazzite, Decky Loader, InputPlumber, and handheld Linux communities whose work supports this edition. Bazzite-specific compatibility work, additional controls, and interface changes in this repository were developed for this edition. Preserve all original copyright notices and license files. See [LICENSE](LICENSE) and [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md) for licensing and attribution details. The separate `acpi_call` module has its own GPL license and is not relicensed here.
