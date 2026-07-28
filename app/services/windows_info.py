import json
import os
import platform
import socket
import subprocess
from datetime import datetime

import psutil


class WindowsInfoService:
    def __init__(self):
        self.creation_flags = 0

        if os.name == "nt":
            self.creation_flags = getattr(
                subprocess,
                "CREATE_NO_WINDOW",
                0,
            )

    def collect_all(self):
        return {
            "generated_at": datetime.now().isoformat(
                timespec="seconds"
            ),
            "system": self.get_system_information(),
            "hardware": self.get_hardware_information(),
            "bios": self.get_bios_information(),
            "memory": self.get_memory_information(),
            "graphics": self.get_graphics_information(),
            "storage": self.get_storage_information(),
            "network": self.get_network_information(),
            "battery": self.get_battery_information(),
        }

    def get_system_information(self):
        uptime_seconds = int(
            datetime.now().timestamp() - psutil.boot_time()
        )

        windows_release = platform.release()
        windows_version = platform.version()

        return {
            "computer_name": platform.node() or "Unknown",
            "operating_system": platform.system() or "Unknown",
            "windows_release": windows_release or "Unknown",
            "windows_version": windows_version or "Unknown",
            "architecture": platform.machine() or "Unknown",
            "processor": (
                platform.processor()
                or platform.machine()
                or "Unknown"
            ),
            "uptime": self.format_uptime(uptime_seconds),
            "boot_time": datetime.fromtimestamp(
                psutil.boot_time()
            ).strftime("%Y-%m-%d %I:%M:%S %p"),
        }

    def get_hardware_information(self):
        result = {
            "manufacturer": "Unknown",
            "model": "Unknown",
            "motherboard_manufacturer": "Unknown",
            "motherboard_product": "Unknown",
            "cpu_physical_cores": (
                psutil.cpu_count(logical=False) or 0
            ),
            "cpu_logical_cores": (
                psutil.cpu_count(logical=True) or 0
            ),
        }

        computer_system = self.run_powershell_json(
            """
            Get-CimInstance Win32_ComputerSystem |
            Select-Object Manufacturer, Model |
            ConvertTo-Json -Compress
            """
        )

        if isinstance(computer_system, dict):
            result["manufacturer"] = (
                computer_system.get("Manufacturer")
                or "Unknown"
            )
            result["model"] = (
                computer_system.get("Model")
                or "Unknown"
            )

        motherboard = self.run_powershell_json(
            """
            Get-CimInstance Win32_BaseBoard |
            Select-Object Manufacturer, Product |
            ConvertTo-Json -Compress
            """
        )

        if isinstance(motherboard, dict):
            result["motherboard_manufacturer"] = (
                motherboard.get("Manufacturer")
                or "Unknown"
            )
            result["motherboard_product"] = (
                motherboard.get("Product")
                or "Unknown"
            )

        return result

    def get_bios_information(self):
        result = {
            "manufacturer": "Unknown",
            "version": "Unknown",
            "serial_number": "Unknown",
            "release_date": "Unknown",
        }

        bios = self.run_powershell_json(
            """
            Get-CimInstance Win32_BIOS |
            Select-Object Manufacturer,
                          SMBIOSBIOSVersion,
                          SerialNumber,
                          ReleaseDate |
            ConvertTo-Json -Compress
            """
        )

        if isinstance(bios, dict):
            result["manufacturer"] = (
                bios.get("Manufacturer")
                or "Unknown"
            )
            result["version"] = (
                bios.get("SMBIOSBIOSVersion")
                or "Unknown"
            )
            result["serial_number"] = (
                bios.get("SerialNumber")
                or "Unknown"
            )

            release_date = bios.get("ReleaseDate")

            if release_date:
                result["release_date"] = str(release_date)

        return result

    def get_memory_information(self):
        memory = psutil.virtual_memory()
        swap = psutil.swap_memory()

        memory_modules = self.run_powershell_json(
            """
            Get-CimInstance Win32_PhysicalMemory |
            Select-Object Manufacturer,
                          PartNumber,
                          Capacity,
                          Speed,
                          DeviceLocator |
            ConvertTo-Json -Compress
            """
        )

        if isinstance(memory_modules, dict):
            memory_modules = [memory_modules]

        if not isinstance(memory_modules, list):
            memory_modules = []

        formatted_modules = []

        for module in memory_modules:
            capacity = module.get("Capacity", 0)

            try:
                capacity_text = self.format_bytes(
                    int(capacity)
                )
            except (TypeError, ValueError):
                capacity_text = "Unknown"

            formatted_modules.append(
                {
                    "manufacturer": (
                        module.get("Manufacturer")
                        or "Unknown"
                    ),
                    "part_number": (
                        str(module.get("PartNumber") or "Unknown")
                        .strip()
                    ),
                    "capacity": capacity_text,
                    "speed_mhz": (
                        module.get("Speed")
                        or "Unknown"
                    ),
                    "slot": (
                        module.get("DeviceLocator")
                        or "Unknown"
                    ),
                }
            )

        return {
            "total": self.format_bytes(memory.total),
            "available": self.format_bytes(memory.available),
            "used": self.format_bytes(memory.used),
            "percentage": f"{memory.percent:.1f}%",
            "virtual_memory_total": self.format_bytes(
                swap.total
            ),
            "modules": formatted_modules,
        }

    def get_graphics_information(self):
        graphics = self.run_powershell_json(
            """
            Get-CimInstance Win32_VideoController |
            Select-Object Name,
                          AdapterRAM,
                          DriverVersion,
                          VideoModeDescription |
            ConvertTo-Json -Compress
            """
        )

        if isinstance(graphics, dict):
            graphics = [graphics]

        if not isinstance(graphics, list):
            return []

        adapters = []

        for adapter in graphics:
            ram = adapter.get("AdapterRAM")

            try:
                ram_text = self.format_bytes(int(ram))
            except (TypeError, ValueError):
                ram_text = "Unknown"

            adapters.append(
                {
                    "name": adapter.get("Name") or "Unknown",
                    "memory": ram_text,
                    "driver_version": (
                        adapter.get("DriverVersion")
                        or "Unknown"
                    ),
                    "display_mode": (
                        adapter.get("VideoModeDescription")
                        or "Unknown"
                    ),
                }
            )

        return adapters

    def get_storage_information(self):
        drives = []

        for partition in psutil.disk_partitions(all=False):
            try:
                usage = psutil.disk_usage(
                    partition.mountpoint
                )
            except (PermissionError, OSError):
                continue

            drives.append(
                {
                    "device": partition.device,
                    "mountpoint": partition.mountpoint,
                    "file_system": (
                        partition.fstype or "Unknown"
                    ),
                    "total": self.format_bytes(usage.total),
                    "used": self.format_bytes(usage.used),
                    "free": self.format_bytes(usage.free),
                    "percentage": f"{usage.percent:.1f}%",
                }
            )

        return drives

    def get_network_information(self):
        adapters = []
        statistics = psutil.net_if_stats()
        addresses = psutil.net_if_addrs()

        for adapter_name, adapter_addresses in addresses.items():
            adapter = {
                "name": adapter_name,
                "status": "Unknown",
                "speed_mbps": "Unknown",
                "ipv4": [],
                "ipv6": [],
                "mac": [],
            }

            stats = statistics.get(adapter_name)

            if stats:
                adapter["status"] = (
                    "Connected" if stats.isup else "Disconnected"
                )
                adapter["speed_mbps"] = stats.speed

            for address in adapter_addresses:
                family = address.family

                if family == socket.AF_INET:
                    adapter["ipv4"].append(address.address)
                elif family == socket.AF_INET6:
                    adapter["ipv6"].append(address.address)
                elif str(family) in (
                    "AddressFamily.AF_LINK",
                    "-1",
                ):
                    adapter["mac"].append(address.address)

            adapters.append(adapter)

        return adapters

    def get_battery_information(self):
        battery = psutil.sensors_battery()

        if battery is None:
            return {
                "available": False,
                "status": "No battery detected",
            }

        if battery.power_plugged:
            power_status = "Charging or connected to power"
        else:
            power_status = "Running on battery"

        seconds_left = battery.secsleft

        if seconds_left in (
            psutil.POWER_TIME_UNKNOWN,
            psutil.POWER_TIME_UNLIMITED,
        ):
            remaining = "Unknown"
        else:
            remaining = self.format_uptime(
                max(0, int(seconds_left))
            )

        return {
            "available": True,
            "percentage": f"{battery.percent:.1f}%",
            "power_status": power_status,
            "remaining_time": remaining,
        }

    def run_powershell_json(self, command):
        if os.name != "nt":
            return None

        try:
            completed = subprocess.run(
                [
                    "powershell.exe",
                    "-NoProfile",
                    "-ExecutionPolicy",
                    "Bypass",
                    "-Command",
                    command,
                ],
                capture_output=True,
                text=True,
                timeout=12,
                creationflags=self.creation_flags,
                check=False,
            )
        except (
            FileNotFoundError,
            subprocess.SubprocessError,
            OSError,
        ):
            return None

        if completed.returncode != 0:
            return None

        output = completed.stdout.strip()

        if not output:
            return None

        try:
            return json.loads(output)
        except json.JSONDecodeError:
            return None

    @staticmethod
    def format_bytes(value):
        size = float(value)

        for unit in ("B", "KB", "MB", "GB", "TB", "PB"):
            if size < 1024:
                return f"{size:.1f} {unit}"
            size /= 1024

        return f"{size:.1f} EB"

    @staticmethod
    def format_uptime(seconds):
        days, remainder = divmod(seconds, 86400)
        hours, remainder = divmod(remainder, 3600)
        minutes, _ = divmod(remainder, 60)

        if days:
            return f"{days}d {hours}h {minutes}m"

        if hours:
            return f"{hours}h {minutes}m"

        return f"{minutes}m"
