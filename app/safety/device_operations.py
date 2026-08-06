class DeviceOperationPolicy:
    """Validation and warnings for reversible device state changes."""

    @staticmethod
    def valid_instance_id(instance_id: str) -> bool:
        return bool(
            instance_id and instance_id.strip() == instance_id
            and "\n" not in instance_id and "\r" not in instance_id
            and len(instance_id) <= 4096
        )

    @staticmethod
    def confirmation_message(device_name: str, enabled: bool) -> str:
        verb = "Enable" if enabled else "Disable"
        return (
            f"{verb} {device_name}?\n\nWindows may require administrator access. "
            "Disabling essential hardware can interrupt the system."
        )

    @staticmethod
    def valid_driver_inf(driver_inf: str) -> bool:
        value = driver_inf.strip()
        return bool(
            value and value == driver_inf and len(value) <= 260
            and value.casefold().endswith(".inf")
            and all(character not in value for character in "\r\n/\\")
        )
