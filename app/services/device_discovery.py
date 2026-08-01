from __future__ import annotations

from app.services.android_wrappers import AdbWrapper, FastbootWrapper, SamsungDownloadWrapper
from app.services.device_models import DiscoveryResult


class DeviceDiscoveryAgent:
    def __init__(self, adb=None, fastboot=None, samsung=None) -> None:
        self.adb = adb or AdbWrapper()
        self.fastboot = fastboot or FastbootWrapper()
        self.samsung = samsung or SamsungDownloadWrapper()

    def discover(self) -> DiscoveryResult:
        devices = []
        errors = []
        wrappers = (
            ("adb", self.adb), ("fastboot", self.fastboot),
            ("samsung_download", self.samsung),
        )
        tools = {name: getattr(wrapper, "executable", None) for name, wrapper in wrappers}
        for name, wrapper in wrappers:
            try:
                devices.extend(wrapper.list_devices())
            except RuntimeError as error:
                errors.append(str(error))

        unique = {}
        for device in devices:
            unique[(device.serial, device.mode)] = device
        ordered = tuple(sorted(unique.values(), key=lambda item: (item.serial, item.mode.value)))
        return DiscoveryResult(devices=ordered, tools=tools, errors=tuple(errors))
