"""Recoverable, verified night-mode transactions over existing lighting backends."""

from copy import deepcopy
from collections.abc import Mapping

try:
    from . import community_features
except ImportError:
    import community_features


def capture_rgb(led_root=community_features.RGB_ROOT):
    """Retain native values so restoring night mode does not quantize RGB colors."""
    device, indexes, maximum, brightness, intensity, limits, trigger = community_features._read_rgb(led_root)
    if trigger != "none":
        raise ValueError("An active LED trigger controls joystick lighting.")
    return {
        "indexes": indexes, "maximum": maximum, "brightness": brightness,
        "intensity": intensity, "limits": limits,
    }


def validate_rgb_snapshot(snapshot):
    if not isinstance(snapshot, Mapping):
        raise ValueError("Invalid RGB snapshot.")
    indexes = snapshot.get("indexes")
    limits = snapshot.get("limits")
    intensity = snapshot.get("intensity")
    maximum = snapshot.get("maximum")
    brightness = snapshot.get("brightness")
    if (
        not isinstance(indexes, list) or len(indexes) != 3
        or set(indexes) != set(community_features.RGB_CHANNELS)
        or not isinstance(limits, list) or len(limits) != 3
        or not isinstance(intensity, list) or len(intensity) != 3
        or type(maximum) is not int or not 1 <= maximum <= 65535
        or type(brightness) is not int or not 0 <= brightness <= maximum
        or any(type(limit) is not int or not 1 <= limit <= 65535 for limit in limits)
        or any(type(value) is not int or not 0 <= value <= limit for value, limit in zip(intensity, limits))
    ):
        raise ValueError("Invalid RGB snapshot.")
    return deepcopy(dict(snapshot))


def restore_rgb(snapshot, led_root=community_features.RGB_ROOT, writer=community_features._write_value):
    """Apply a native snapshot only to a matching device, with verified rollback."""
    try:
        target = validate_rgb_snapshot(snapshot)
        current = capture_rgb(led_root)
        if any(target[key] != current[key] for key in ("indexes", "maximum", "limits")):
            raise ValueError("The joystick RGB capabilities changed.")
        device = led_root / community_features.RGB_DEVICE_NAME
    except (OSError, ValueError, UnicodeError, TypeError):
        return {"success": False, "error": "The RGB snapshot cannot be restored on the current device."}
    if target == current:
        return {"success": True}
    try:
        writer(device / "multi_intensity", " ".join(map(str, target["intensity"])))
        writer(device / "brightness", str(target["brightness"]))
        if capture_rgb(led_root) != target:
            raise ValueError("RGB verification failed")
        return {"success": True}
    except (OSError, ValueError, UnicodeError):
        try:
            writer(device / "multi_intensity", " ".join(map(str, current["intensity"])))
            writer(device / "brightness", str(current["brightness"]))
            if capture_rgb(led_root) != current:
                raise ValueError("RGB rollback failed")
            return {"success": False, "error": "RGB verification failed; its previous state was restored."}
        except (OSError, ValueError, UnicodeError):
            return {"success": False, "error": "RGB verification and rollback failed. The saved snapshot is retained for recovery."}


def validate_snapshot(snapshot):
    if not isinstance(snapshot, Mapping) or type(snapshot.get("awake")) is not bool or type(snapshot.get("sleep")) is not bool:
        raise ValueError("The saved lighting snapshot is incomplete.")
    return {"awake": snapshot["awake"], "sleep": snapshot["sleep"], "rgb": validate_rgb_snapshot(snapshot.get("rgb"))}


class NightMode:
    """Snapshot before writing; retain a recovery journal until every step verifies."""

    def __init__(self, get_settings, commit, awake_status, set_awake, sleep_status, set_sleep,
                 rgb_capture=capture_rgb, rgb_restore=restore_rgb):
        self.get_settings = get_settings
        self.commit = commit
        self.awake_status = awake_status
        self.set_awake = set_awake
        self.sleep_status = sleep_status
        self.set_sleep = set_sleep
        self.rgb_capture = rgb_capture
        self.rgb_restore = rgb_restore
        self.error = None

    def _journal(self):
        value = self.get_settings().get("nightMode")
        return deepcopy(value) if isinstance(value, dict) else {}

    def _capture(self):
        awake, sleeping = self.awake_status(), self.sleep_status()
        if not awake.get("success") or not sleeping.get("success"):
            raise ValueError("All lighting interfaces must be readable before night mode can change them.")
        return validate_snapshot({"awake": awake.get("enabled"), "sleep": sleeping.get("enabled"), "rgb": self.rgb_capture()})

    def _write(self, snapshot):
        return self.commit({"nightMode": snapshot})

    def _restore(self, snapshot):
        # Continue all recovery steps even if one interface fails.
        outcomes = []
        for operation in (
            lambda: self.rgb_restore(snapshot["rgb"]),
            lambda: self.set_sleep(snapshot["sleep"]),
            lambda: self.set_awake(snapshot["awake"]),
        ):
            try:
                outcomes.append(bool(operation().get("success")))
            except Exception:
                outcomes.append(False)
        try:
            return all(outcomes) and self._capture() == snapshot
        except Exception:
            return False

    def _off(self, snapshot):
        off_rgb = deepcopy(snapshot["rgb"])
        off_rgb["brightness"] = 0
        for operation in (
            lambda: self.set_awake(False),
            lambda: self.set_sleep(False),
            lambda: self.rgb_restore(off_rgb),
        ):
            if not operation().get("success"):
                raise ValueError("A lighting interface did not confirm night mode.")
        current = self._capture()
        if current["awake"] or current["sleep"] or current["rgb"]["brightness"] != 0:
            raise ValueError("Night mode could not be verified.")

    def status(self):
        journal = self._journal()
        recoverable = False
        try:
            validate_snapshot(journal.get("snapshot"))
            recoverable = True
        except (ValueError, TypeError):
            pass
        available = False
        verified = False
        try:
            current = self._capture()
            available = True
            verified = not current["awake"] and not current["sleep"] and current["rgb"]["brightness"] == 0
        except Exception:
            pass
        active = journal.get("active") is True
        pending = journal.get("pending") is True
        error = self.error
        if (active or pending) and not recoverable:
            error = "The original lighting snapshot is missing or invalid. No automatic changes were made."
        elif active and not verified:
            error = error or "Night mode is enabled, but another lighting controller or device change altered its state."
        return {
            "success": error is None, "active": active, "pending": pending,
            "recoverable": recoverable, "available": available,
            "verified": active and verified, "error": error,
        }

    def set_enabled(self, enabled):
        if type(enabled) is not bool:
            return {"success": False, "error": "Night mode state must be boolean."}
        journal = self._journal()
        has_transaction = journal.get("active") is True or journal.get("pending") is True
        snapshot = None
        armed = False
        self.error = None
        try:
            if has_transaction:
                snapshot = validate_snapshot(journal.get("snapshot"))
            elif enabled:
                snapshot = self._capture()
            else:
                return self.status()
            # A persisted snapshot exists before the first hardware write.
            self._write({"active": bool(journal.get("active")), "pending": True, "snapshot": snapshot})
            armed = True
            if enabled:
                self._off(snapshot)
                self._write({"active": True, "pending": False, "snapshot": snapshot})
            else:
                if not self._restore(snapshot):
                    raise ValueError("The previous lighting state could not be fully restored.")
                self._write({"active": False, "pending": False, "snapshot": None})
        except Exception:
            if not armed:
                self.error = "Night mode could not prepare a recovery snapshot. No lighting changes were made."
                return {**self.status(), "success": False, "error": self.error}
            if enabled and snapshot is not None:
                restored = self._restore(snapshot)
                try:
                    self._write({"active": False, "pending": not restored, "snapshot": None if restored else snapshot})
                except Exception:
                    pass
                self.error = ("Night mode failed; the previous lighting state was restored."
                              if restored else "Night mode failed and recovery is incomplete. The original snapshot is retained; select Restore lighting to retry.")
            else:
                self.error = "The previous lighting state could not be fully restored. The snapshot is retained for recovery."
            return {**self.status(), "success": False, "error": self.error}
        return self.status()

    def startup(self):
        """Reuse the original snapshot on restart; never snapshot already-dark LEDs."""
        journal = self._journal()
        if journal.get("pending") is True:
            return self.set_enabled(False)
        if journal.get("active") is True:
            return self.set_enabled(True)
        return self.status()
