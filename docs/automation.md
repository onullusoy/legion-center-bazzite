# Lighting and power automation

## Night mode

Night mode is an explicit, verified transaction over three independent interfaces:
the awake power-button LED, the sleep LED, and the joystick RGB rings.

Before changing any light, the plugin saves the current hardware state and a
pending recovery journal in its settings. Native RGB channel order, limits, and
raw values are preserved; restoring the snapshot does not round colors through
percentages. A failed transaction attempts to restore all three interfaces. If
recovery cannot be verified, the snapshot remains available for **Restore lighting**.

Restarting the plugin does not replace the original snapshot with the already-dark
state. An active night-mode snapshot is reused for one startup verification; an
incomplete transaction is recovered instead. Normal awake/sleep preference
restoration is skipped during this recovery. Individual lighting edits are blocked
until night mode is restored, so they cannot silently change the meaning of its
snapshot.

The plugin does not repeatedly force lights off. An external application changing
the lights is reported as an unverified night-mode state. Native RGB triggers are
respected; the plugin does not disable a trigger to take control.

## AC and battery fan profiles

Power profile automation is disabled by default. The user chooses one existing
fan slot for charger power and one for battery power. Configuration changes only
prime the current source; the next real source transition applies the matching
profile once. **Apply matching profile now** is an explicit alternative.

Manual profile changes are retained until the next power transition. Automation
never turns custom fan control on. If custom fan control is off, a transition is
recorded as skipped and the firmware's automatic preference is preserved. An
unverified fan write is not saved as the active profile. No second TDP controller
or performance daemon is introduced.

## Sleep battery summaries and resume health

Sleep entry and exit come from logind's
[`PrepareForSleep`](https://www.freedesktop.org/software/systemd/man/latest/org.freedesktop.login1.html)
signal, monitored with the system `dbus-monitor` tool. No scheduling gap or elapsed
idle time is treated as a sleep event. `CLOCK_BOOTTIME` includes suspend duration;
a per-boot marker prevents a reboot from becoming a fake sleep-loss estimate.

A standard logind **delay** inhibitor protects the short sleep-entry battery sample
and settings commit. It is released in a `finally` path as soon as that work ends,
then reacquired after resume. It is never a block inhibitor; logind's configured
maximum delay still applies. The plugin checks that budget and marks unprotected
or late samples unreliable instead of producing a false zero-drain estimate.
If the monitor or delay lock is unavailable, the UI reports that state. The helper
uses the system `systemd-inhibit`, `busctl`, and Python 3 tools and never prompts
for an authentication password.

A completed pair records duration, battery percentage change, and energy change
when the power-supply interface provides it. Percentages are coarse estimates;
charging during sleep is reported as a gain rather than battery drain. Missing
samples, an unmatched resume event, or a changed boot marker do not produce an
invented estimate. At most ten cycles are retained, with three recent summaries
shown in the interface. No completed record is shown before a real cycle occurs.

Resume health checks controller presence, InputPlumber status, the configured
fan table or intentional full-speed flag, and saved LED preferences. These are
read-only checks. The plugin does not restart InputPlumber, override TDP, or
silently reapply settings as a repair. A manual **Check now** action can refresh
the same diagnostics.

The public status API excludes the internal recovery snapshot, per-boot marker,
device serial numbers, usernames, and filesystem paths.

## Validation boundaries

Mocked hardware and temporary-sysfs tests cover transaction rollback, restart
recovery, profile isolation, disabled-fan preservation, real signal parsing,
duplicate boundaries, reboot rejection, charging during sleep, and missing
battery data. Physical LED behavior across suspend, actual charger transitions,
and real sleep/resume measurements must also be checked on supported hardware.
