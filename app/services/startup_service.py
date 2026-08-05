from __future__ import annotations

import hashlib
import ctypes
import json
import os
import re
import subprocess
from pathlib import Path
from typing import Any

import winreg


class StartupService:
    """Discover and safely manage common Windows startup entries."""

    DISABLED_KEY = r"Software\ARC3\DisabledStartup"
    DISABLED_FOLDER = ".arc3_disabled"
    REGISTRY_LOCATIONS = (
        (r"Software\Microsoft\Windows\CurrentVersion\Run", "Run"),
        (r"Software\Microsoft\Windows\CurrentVersion\RunOnce", "Run Once"),
        (
            r"Software\Microsoft\Windows\CurrentVersion"
            r"\Policies\Explorer\Run",
            "Policy Run",
        ),
    )
    HIVES = (
        (winreg.HKEY_CURRENT_USER, "HKCU", "Current User"),
        (winreg.HKEY_LOCAL_MACHINE, "HKLM", "All Users"),
    )
    VIEWS = (
        (winreg.KEY_WOW64_64KEY, "64-bit"),
        (winreg.KEY_WOW64_32KEY, "32-bit"),
    )

    def collect_entries(self) -> list[dict[str, Any]]:
        entries: list[dict[str, Any]] = []
        entries.extend(self._collect_registry_entries())
        entries.extend(self._collect_disabled_registry_entries())
        entries.extend(self._collect_startup_folders())

        executable_paths = {
            entry["file_path"]
            for entry in entries
            if entry["file_path"] and entry["file_exists"]
        }
        file_details = self._inspect_files(executable_paths)

        for entry in entries:
            details = file_details.get(
                os.path.normcase(entry["file_path"]),
                {},
            )
            entry["publisher"] = details.get("publisher", "Unknown")
            entry["signature_status"] = details.get(
                "signature_status",
                "File not found" if not entry["file_exists"] else "Unknown",
            )
            entry["startup_impact"] = self._estimate_impact(entry)

        entries.sort(
            key=lambda item: (
                not item["enabled"],
                item["name"].casefold(),
                item["location"].casefold(),
            )
        )
        return entries

    def _collect_registry_entries(self) -> list[dict[str, Any]]:
        entries = []
        seen = set()

        for hive, hive_name, scope in self.HIVES:
            views = (
                self.VIEWS
                if hive == winreg.HKEY_LOCAL_MACHINE
                else self.VIEWS[:1]
            )
            for view_flag, view_name in views:
                for key_path, launch_type in self.REGISTRY_LOCATIONS:
                    identity = (hive_name, view_name, key_path)
                    if identity in seen:
                        continue
                    seen.add(identity)

                    try:
                        key = winreg.OpenKey(
                            hive,
                            key_path,
                            0,
                            winreg.KEY_READ | view_flag,
                        )
                    except OSError:
                        continue

                    with key:
                        index = 0
                        while True:
                            try:
                                name, command, value_type = winreg.EnumValue(
                                    key,
                                    index,
                                )
                            except OSError:
                                break
                            index += 1

                            command_text = self._value_to_text(command)
                            file_path = self.extract_file_path(command_text)
                            entries.append(
                                self._entry(
                                    name=name or "(Default)",
                                    command=command_text,
                                    location=f"{scope} Registry ({view_name})",
                                    source=f"{hive_name}\\{key_path}",
                                    enabled=True,
                                    file_path=file_path,
                                    launch_type=launch_type,
                                    source_type="registry",
                                    hive=hive_name,
                                    registry_path=key_path,
                                    registry_view=view_name,
                                    value_type=value_type,
                                    registry_value_name=name,
                                )
                            )

        return entries

    def _collect_disabled_registry_entries(
        self,
    ) -> list[dict[str, Any]]:
        entries = []
        seen_tokens = set()

        for hive, hive_name, scope in self.HIVES:
            views = (
                self.VIEWS
                if hive == winreg.HKEY_LOCAL_MACHINE
                else self.VIEWS[:1]
            )
            for view_flag, view_name in views:
                try:
                    key = winreg.OpenKey(
                        hive,
                        self.DISABLED_KEY,
                        0,
                        winreg.KEY_READ | view_flag,
                    )
                except OSError:
                    continue

                with key:
                    index = 0
                    while True:
                        try:
                            token, raw_payload, _ = winreg.EnumValue(
                                key,
                                index,
                            )
                        except OSError:
                            break
                        index += 1

                        if token in seen_tokens:
                            continue
                        seen_tokens.add(token)

                        try:
                            payload = json.loads(raw_payload)
                        except (TypeError, json.JSONDecodeError):
                            continue

                        command = self._value_to_text(payload.get("data", ""))
                        file_path = self.extract_file_path(command)
                        entries.append(
                            self._entry(
                                name=payload.get("name") or "(Default)",
                                command=command,
                                location=(
                                    f"{scope} Registry "
                                    f"({payload.get('view', view_name)})"
                                ),
                                source=(
                                    f"{hive_name}\\"
                                    f"{payload.get('path', '')}"
                                ),
                                enabled=False,
                                file_path=file_path,
                                launch_type=payload.get(
                                    "launch_type",
                                    "Run",
                                ),
                                source_type="registry",
                                hive=hive_name,
                                registry_path=payload.get("path", ""),
                                registry_view=payload.get("view", view_name),
                                value_type=payload.get(
                                    "value_type",
                                    winreg.REG_SZ,
                                ),
                                registry_value_name=payload.get(
                                    "registry_value_name",
                                    payload.get("name", ""),
                                ),
                                disabled_token=token,
                            )
                        )

        return entries

    def _collect_startup_folders(self) -> list[dict[str, Any]]:
        entries = []
        appdata = os.environ.get("APPDATA", "")
        programdata = os.environ.get("PROGRAMDATA", "")
        locations = (
            (
                Path(appdata)
                / "Microsoft/Windows/Start Menu/Programs/Startup",
                "Current User Startup Folder",
            ),
            (
                Path(programdata)
                / "Microsoft/Windows/Start Menu/Programs/Startup",
                "All Users Startup Folder",
            ),
        )

        for folder, label in locations:
            if not str(folder) or not folder.exists():
                continue

            for path in folder.iterdir():
                if (
                    path.name == self.DISABLED_FOLDER
                    or path.name.casefold() == "desktop.ini"
                    or not path.is_file()
                ):
                    continue
                entries.append(self._folder_entry(path, folder, label, True))

            disabled_folder = folder / self.DISABLED_FOLDER
            if disabled_folder.exists():
                for path in disabled_folder.iterdir():
                    if path.is_file():
                        entries.append(
                            self._folder_entry(
                                path,
                                folder,
                                label,
                                False,
                            )
                        )

        return entries

    def _folder_entry(
        self,
        path: Path,
        startup_folder: Path,
        label: str,
        enabled: bool,
    ) -> dict[str, Any]:
        file_path = str(path)
        return self._entry(
            name=path.stem,
            command=file_path,
            location=label,
            source=str(startup_folder),
            enabled=enabled,
            file_path=file_path,
            launch_type="Startup Folder",
            source_type="folder",
            original_folder=str(startup_folder),
            stored_path=str(path),
        )

    @staticmethod
    def _entry(**values: Any) -> dict[str, Any]:
        entry = {
            "name": "",
            "publisher": "Unknown",
            "command": "",
            "location": "",
            "source": "",
            "enabled": True,
            "file_path": "",
            "file_exists": False,
            "signature_status": "Unknown",
            "launch_type": "",
            "startup_impact": "Low",
            "source_type": "",
        }
        entry.update(values)
        entry["file_exists"] = bool(
            entry["file_path"] and Path(entry["file_path"]).exists()
        )
        return entry

    @staticmethod
    def _value_to_text(value: Any) -> str:
        if isinstance(value, (list, tuple)):
            return " ".join(str(item) for item in value)
        return str(value)

    @staticmethod
    def extract_file_path(command: str) -> str:
        expanded = os.path.expandvars(command.strip())
        if not expanded:
            return ""

        if expanded.startswith('"'):
            match = re.match(r'^"([^"]+)"', expanded)
            candidate = match.group(1) if match else expanded.strip('"')
        else:
            match = re.match(
                r"(.+?\.(?:exe|com|bat|cmd|ps1|vbs|js|lnk))"
                r"(?:\s|$)",
                expanded,
                re.IGNORECASE,
            )
            candidate = match.group(1) if match else expanded.split()[0]

        return os.path.normpath(candidate.strip().strip('"'))

    def _inspect_files(
        self,
        paths: set[str],
    ) -> dict[str, dict[str, str]]:
        if not paths:
            return {}

        script = (
            "$paths=[Console]::In.ReadToEnd()|ConvertFrom-Json;"
            "$items=@($paths|ForEach-Object{"
            "$p=[string]$_;$item=Get-Item -LiteralPath $p -ErrorAction SilentlyContinue;"
            "$sig=Get-AuthenticodeSignature -LiteralPath $p -ErrorAction SilentlyContinue;"
            "$publisher='Unknown';"
            "if($item.VersionInfo.CompanyName){$publisher=$item.VersionInfo.CompanyName}"
            "elseif($sig.SignerCertificate.Subject -match 'CN=([^,]+)')"
            "{$publisher=$Matches[1]};"
            "[pscustomobject]@{path=$p;publisher=$publisher;"
            "signature_status=if($sig){[string]$sig.Status}else{'Unknown'}}"
            "});$items|ConvertTo-Json -Compress"
        )

        try:
            result = subprocess.run(
                [
                    "powershell.exe",
                    "-NoProfile",
                    "-NonInteractive",
                    "-Command",
                    script,
                ],
                input=json.dumps(sorted(paths)),
                text=True,
                capture_output=True,
                timeout=40,
                creationflags=subprocess.CREATE_NO_WINDOW,
                check=False,
            )
            payload = json.loads(result.stdout or "[]")
        except (
            OSError,
            subprocess.TimeoutExpired,
            json.JSONDecodeError,
        ):
            return {}

        if isinstance(payload, dict):
            payload = [payload]

        return {
            os.path.normcase(item.get("path", "")): {
                "publisher": item.get("publisher") or "Unknown",
                "signature_status": item.get("signature_status") or "Unknown",
            }
            for item in payload
        }

    @staticmethod
    def _estimate_impact(entry: dict[str, Any]) -> str:
        command = entry["command"].casefold()
        if not entry["enabled"]:
            return "Disabled"
        if any(
            token in command
            for token in ("updater", "update.exe", "helper", "tray")
        ):
            return "Medium"
        if entry["launch_type"] in ("Policy Run", "Run Once"):
            return "Medium"
        if any(token in command for token in ("powershell", "wscript", "cscript")):
            return "High"
        return "Low"

    def set_enabled(
        self,
        entry: dict[str, Any],
        enabled: bool,
    ) -> tuple[bool, str]:
        if entry["enabled"] == enabled:
            return True, "The startup item is already in the requested state."

        try:
            if entry["source_type"] == "registry":
                if enabled:
                    self._enable_registry_entry(entry)
                else:
                    self._disable_registry_entry(entry)
            elif entry["source_type"] == "folder":
                self._set_folder_entry_enabled(entry, enabled)
            else:
                return False, "This startup source cannot be changed."
        except PermissionError:
            return (
                False,
                "Access was denied. Run ARC3 as administrator for "
                "all-users startup entries.",
            )
        except OSError as error:
            return False, str(error)

        state = "enabled" if enabled else "disabled"
        return True, f"{entry['name']} was {state} successfully."

    def _disable_registry_entry(self, entry: dict[str, Any]) -> None:
        hive = self._hive_from_name(entry["hive"])
        view_flag = self._view_flag(entry["registry_view"])
        token_source = (
            f"{entry['hive']}|{entry['registry_view']}|"
            f"{entry['registry_path']}|{entry['name']}"
        )
        token = hashlib.sha256(token_source.encode("utf-8")).hexdigest()
        payload = json.dumps(
            {
                "name": entry["name"],
                "registry_value_name": entry.get(
                    "registry_value_name",
                    entry["name"],
                ),
                "data": entry["command"],
                "value_type": entry.get("value_type", winreg.REG_SZ),
                "path": entry["registry_path"],
                "view": entry["registry_view"],
                "launch_type": entry["launch_type"],
            }
        )

        with winreg.CreateKeyEx(
            hive,
            self.DISABLED_KEY,
            0,
            winreg.KEY_WRITE | view_flag,
        ) as backup_key:
            winreg.SetValueEx(
                backup_key,
                token,
                0,
                winreg.REG_SZ,
                payload,
            )

        try:
            with winreg.OpenKey(
                hive,
                entry["registry_path"],
                0,
                winreg.KEY_SET_VALUE | view_flag,
            ) as source_key:
                winreg.DeleteValue(
                    source_key,
                    entry.get("registry_value_name", entry["name"]),
                )
        except OSError:
            with winreg.OpenKey(
                hive,
                self.DISABLED_KEY,
                0,
                winreg.KEY_SET_VALUE | view_flag,
            ) as backup_key:
                winreg.DeleteValue(backup_key, token)
            raise

    def _enable_registry_entry(self, entry: dict[str, Any]) -> None:
        hive = self._hive_from_name(entry["hive"])
        view_flag = self._view_flag(entry["registry_view"])

        with winreg.CreateKeyEx(
            hive,
            entry["registry_path"],
            0,
            winreg.KEY_SET_VALUE | view_flag,
        ) as source_key:
            winreg.SetValueEx(
                source_key,
                entry.get("registry_value_name", entry["name"]),
                0,
                entry.get("value_type", winreg.REG_SZ),
                entry["command"],
            )

        try:
            with winreg.OpenKey(
                hive,
                self.DISABLED_KEY,
                0,
                winreg.KEY_SET_VALUE | view_flag,
            ) as backup_key:
                winreg.DeleteValue(
                    backup_key,
                    entry["disabled_token"],
                )
        except OSError:
            try:
                with winreg.OpenKey(
                    hive,
                    entry["registry_path"],
                    0,
                    winreg.KEY_SET_VALUE | view_flag,
                ) as source_key:
                    winreg.DeleteValue(
                        source_key,
                        entry.get("registry_value_name", entry["name"]),
                    )
            except OSError:
                pass
            raise

    def _set_folder_entry_enabled(
        self,
        entry: dict[str, Any],
        enabled: bool,
    ) -> None:
        source = Path(entry["stored_path"])
        original_folder = Path(entry["original_folder"])

        if enabled:
            destination = original_folder / source.name
        else:
            disabled_folder = original_folder / self.DISABLED_FOLDER
            disabled_folder.mkdir(exist_ok=True)
            try:
                disabled_folder.chmod(0o700)
            except OSError:
                pass
            destination = disabled_folder / source.name

        if destination.exists():
            raise FileExistsError(
                f"A startup entry named {destination.name} already exists."
            )
        source.replace(destination)

    @staticmethod
    def _hive_from_name(name: str):
        if name == "HKCU":
            return winreg.HKEY_CURRENT_USER
        if name == "HKLM":
            return winreg.HKEY_LOCAL_MACHINE
        raise ValueError(f"Unsupported registry hive: {name}")

    @staticmethod
    def _view_flag(view: str) -> int:
        return (
            winreg.KEY_WOW64_32KEY
            if view == "32-bit"
            else winreg.KEY_WOW64_64KEY
        )

    @staticmethod
    def open_containing_folder(path: str) -> tuple[bool, str]:
        target = Path(path)
        if not target.exists():
            return False, "The startup file no longer exists."
        try:
            subprocess.Popen(["explorer.exe", f"/select,{target}"])
        except OSError as error:
            return False, str(error)
        return True, ""

    @staticmethod
    def open_registry_location(registry_path: str) -> tuple[bool, str]:
        if not registry_path:
            return False, "This item does not have a registry location."
        registry_path = registry_path.replace(
            "HKCU\\",
            "Computer\\HKEY_CURRENT_USER\\",
            1,
        ).replace(
            "HKLM\\",
            "Computer\\HKEY_LOCAL_MACHINE\\",
            1,
        )
        try:
            with winreg.CreateKey(
                winreg.HKEY_CURRENT_USER,
                r"Software\Microsoft\Windows\CurrentVersion"
                r"\Applets\Regedit",
            ) as key:
                winreg.SetValueEx(
                    key,
                    "LastKey",
                    0,
                    winreg.REG_SZ,
                    registry_path,
                )
            # Registry Editor is an elevated Windows application on some
            # systems. ShellExecute lets Windows display the normal UAC prompt
            # instead of surfacing WinError 740 to ARC3.
            launch_result = ctypes.windll.shell32.ShellExecuteW(
                None, "open", "regedit.exe", "/m", None, 1,
            )
            if launch_result <= 32:
                raise OSError(
                    f"Windows could not open Registry Editor (code {launch_result})."
                )
        except OSError as error:
            return False, str(error)
        return True, ""
