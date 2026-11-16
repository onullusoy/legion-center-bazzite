"""Upstream OTA installation is disabled for the independent community fork."""


def ota_update():
    raise RuntimeError(
        'No community release channel is configured. Build this fork and use its local installer.'
    )
