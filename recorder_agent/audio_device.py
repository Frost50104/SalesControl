"""ALSA audio device detection and validation."""

from __future__ import annotations

import logging
import re
import subprocess

log = logging.getLogger(__name__)


class AudioDeviceError(Exception):
    """Raised when the configured audio device is unavailable."""


def list_capture_devices() -> list[dict[str, str]]:
    """Return list of ALSA capture devices: [{card, device, name}]."""
    devices: list[dict[str, str]] = []
    try:
        output = subprocess.check_output(
            ["arecord", "-l"], text=True, stderr=subprocess.STDOUT, timeout=5,
        )
    except (subprocess.CalledProcessError, FileNotFoundError, subprocess.TimeoutExpired) as exc:
        log.warning("arecord_list_failed", extra={"error": str(exc)})
        return devices

    # Parse lines like: card 1: Device [USB Audio Device], device 0: USB Audio [USB Audio]
    pattern = re.compile(
        r"card\s+(\d+):\s+(\S+)\s+\[(.+?)\],\s+device\s+(\d+):\s+(.+?)\s+\[(.+?)\]"
    )
    for line in output.splitlines():
        m = pattern.search(line)
        if m:
            devices.append({
                "card": m.group(1),
                "card_id": m.group(2),
                "card_name": m.group(3),
                "device": m.group(4),
                "device_id": m.group(5),
                "device_name": m.group(6),
                "alsa_id": f"hw:{m.group(1)},{m.group(4)}",
            })
    return devices


def detect_usb_device() -> str:
    """Auto-detect the first USB audio capture device, return ALSA id like 'hw:1,0'."""
    devices = list_capture_devices()
    # prefer USB devices (card_name usually contains "USB")
    for dev in devices:
        if "usb" in dev["card_name"].lower() or "usb" in dev["device_name"].lower():
            log.info("usb_mic_detected", extra={"alsa_id": dev["alsa_id"], "card_name": dev["card_name"]})
            return dev["alsa_id"]
    if devices:
        dev = devices[0]
        log.warning("no_usb_mic_found_using_first", extra={"alsa_id": dev["alsa_id"], "card_name": dev["card_name"]})
        return dev["alsa_id"]
    raise AudioDeviceError(
        "No capture devices found. Check that a USB microphone is connected "
        "and run 'arecord -l' to verify."
    )


def validate_device(alsa_id: str) -> bool:
    """Quick check that the device can be opened for capture."""
    try:
        proc = subprocess.run(
            ["arecord", "-D", alsa_id, "-d", "1", "-f", "S16_LE", "-r", "48000", "-c", "1", "/dev/null"],
            capture_output=True, text=True, timeout=5,
        )
        if proc.returncode == 0:
            return True
        log.warning("device_validate_failed", extra={"alsa_id": alsa_id, "stderr": proc.stderr[:200]})
        return False
    except (subprocess.TimeoutExpired, FileNotFoundError) as exc:
        log.warning("device_validate_error", extra={"alsa_id": alsa_id, "error": str(exc)})
        return False


def resolve_device(configured: str) -> str:
    """Resolve the audio device: use configured value or auto-detect."""
    if configured:
        if validate_device(configured):
            log.info("audio_device_ok", extra={"alsa_id": configured})
            return configured
        raise AudioDeviceError(
            f"Configured audio device '{configured}' is not available. "
            f"Available devices: {list_capture_devices()}"
        )
    return detect_usb_device()
