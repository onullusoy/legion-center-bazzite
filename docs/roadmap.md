# Community feature roadmap

The scope below is based on reports from original Legion Go users running Bazzite. Reports from Windows, the Legion Go S, and the Legion Go 2 are not evidence that the same issue exists on every original Legion Go.

## Implemented for evaluation

- **Independent sleep LED control.** Uses the documented suspend selector and checks firmware read-back. The awake power LED remains separate. Saved preferences are restored when the plugin starts.
- **Native joystick RGB controls.** Reads kernel channel ordering and limits, supports brightness and color, and verifies explicit writes. Active LED triggers are respected. No background poller repeatedly overwrites another RGB tool.
- **Read-only system diagnostics.** Shows the recognized model, BIOS and kernel versions, service state, fan interface, controller presence, and gyro device count. It does not expose device serial numbers, usernames, home-directory paths, or raw logs. Gyro presence is not treated as proof that motion data reaches Steam Input.

These features have mock and temporary-sysfs tests. Sleep/wake behavior, physical RGB output, and interaction with Steam's lighting controls still require device testing before release.

## Integrated features and remaining device validation

| Area | Potential contribution | Release requirement |
| --- | --- | --- |
| Touchpad pointer | A native touchpad target can be attached and removed without replacing existing controller targets | Target creation/undo verified; physical pointer behavior still needs checking in Gaming Mode |
| Resume health | Read-only controller, fan, and LED verification after real resume signals | Observe a real suspend/resume cycle; never restart InputPlumber blindly during a game |
| Gyro setup | Capability status plus a bounded tablet IIO motion test | Controller capabilities are not represented as verified left/right motion streams |
| AC/battery profiles | Opt-in transition-only selection of one of the three fan slots | Verify a physical charger transition; no competing TDP controller is added |
| Sleep battery use | Protected logind sleep entry, BOOTTIME duration, and a text loss summary | Observe a real sleep cycle; no estimate is emitted for an unreliable sample |

No automatic controller-service restart, hibernation setup, TDP override, or driver repair is included in this work.

## References

- [Original Legion Go sleep-light report](https://www.reddit.com/r/LegionGo/comments/1wbo12b/how_committed_are_you/)
- [Bazzite 44/45 desktop touchpad report](https://www.reddit.com/r/Bazzite/comments/1xv8j54/legion_go_1_touchpad_on_bazzite_deck_4445/)
- [Original Legion Go Bazzite 45 discussion and gyro reports](https://www.reddit.com/r/Bazzite/comments/1xu9gwh/updating_from_version_43_to_45_bow_good_on_lenovo/)
- [Original Legion Go Linux resume discussion](https://www.reddit.com/r/LegionGo/comments/1wd8qkf/status_of_non_windows_on_legion_go_z1e/)
- [TDP settings reverting discussion](https://www.reddit.com/r/LegionGo/comments/1tkaudp/tdp_settings_reverting/)
- [Sleep battery-loss discussion](https://www.reddit.com/r/LegionGo/comments/1u7gzd4/bazzite_is_10000_times_buggier_than_windows_11/)
- [Sleep LED protocol reference](https://github.com/hhd-dev/adjustor/blob/master/src/adjustor/core/lenovo.py)
- [Linux multicolor LED interface](https://docs.kernel.org/leds/leds-class-multicolor.html)
- [InputPlumber documentation](https://shadowblip.github.io/InputPlumber/usage/)
- [PowerStation](https://github.com/ShadowBlip/PowerStation)

## To-do

- **VERIFY — 2026-11-16: Legion Decky rename** (delivered by commit `583a2d8`). On the Legion Go, in Desktop Mode run `git clone https://github.com/onullusoy/legion-decky.git && cd legion-decky && pnpm install --frozen-lockfile && pnpm check && ./install.sh` (for an existing checkout, use `git pull --ff-only` instead of cloning). Return to Gaming Mode, open Decky → Legion Decky, and check that the menu entry and panel heading both say **Legion Decky**. Open About and confirm version **1.1.6**. Confirm previously saved fan profiles and lighting preferences are still present, and that only one copy of the plugin appears. Expected: the renamed plugin loads normally with existing settings. The internal `LegionCenter` installation directory and existing backup paths remain unchanged.
