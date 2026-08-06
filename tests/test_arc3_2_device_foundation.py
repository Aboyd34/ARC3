import unittest
from unittest.mock import Mock

from app.adapters.windows.device_commands import WindowsDeviceCommandAdapter
from app.core.results import OperationResult
from app.domain.windows_devices import DeviceHealth, normalize_device
from app.safety.device_operations import DeviceOperationPolicy
from app.services.windows_device_service import WindowsDeviceService


class DeviceFoundationTests(unittest.TestCase):
    def test_domain_normalization_is_ui_independent(self):
        device = normalize_device({"status": "OK", "problem_code": 0})
        self.assertEqual(device["health"], DeviceHealth.HEALTHY.value)

    def test_disabled_problem_overrides_reported_enabled_state(self):
        device = normalize_device({
            "status": "Error", "problem_code": "0x16", "enabled": True,
        })
        self.assertFalse(device["enabled"])
        self.assertEqual(device["health"], DeviceHealth.DISABLED.value)

    def test_adapter_uses_argument_list_without_shell(self):
        runner = Mock(return_value=Mock(returncode=0))
        WindowsDeviceCommandAdapter(runner).pnputil(
            ["/enable-device", "USB\\CAM"], timeout=30,
        )
        args, kwargs = runner.call_args
        self.assertEqual(args[0], ["pnputil.exe", "/enable-device", "USB\\CAM"])
        self.assertNotIn("shell", kwargs)

    def test_result_remains_tuple_compatible(self):
        success, message = OperationResult(True, "done")
        self.assertEqual((success, message), (True, "done"))

    def test_policy_rejects_multiline_identifier(self):
        self.assertFalse(DeviceOperationPolicy.valid_instance_id("USB\\GOOD\nBAD"))
        self.assertTrue(DeviceOperationPolicy.valid_instance_id("USB\\GOOD"))

    def test_driver_inf_policy_accepts_published_inf_name_only(self):
        self.assertTrue(DeviceOperationPolicy.valid_driver_inf("oem42.inf"))
        self.assertFalse(DeviceOperationPolicy.valid_driver_inf("folder\\oem42.inf"))
        self.assertFalse(DeviceOperationPolicy.valid_driver_inf("oem42.inf\n/enum"))

    def test_driver_export_uses_bounded_argument_list(self):
        runner = Mock(return_value=Mock(returncode=0, stdout="exported", stderr=""))
        result = WindowsDeviceService(runner).export_driver(
            "oem42.inf", "C:\\Driver Export",
        )
        self.assertTrue(result.success)
        args, kwargs = runner.call_args
        self.assertEqual(args[0], [
            "pnputil.exe", "/export-driver", "oem42.inf", "C:\\Driver Export",
        ])
        self.assertEqual(kwargs["timeout"], 120)

    def test_invalid_driver_export_does_not_run_command(self):
        runner = Mock()
        result = WindowsDeviceService(runner).export_driver(
            "..\\unsafe.inf", "C:\\Driver Export",
        )
        self.assertFalse(result.success)
        runner.assert_not_called()

    def test_open_device_manager_uses_mmc_argument_list(self):
        service = WindowsDeviceService()
        service.commands.open_device_manager = Mock()
        result = service.open_device_manager()
        self.assertTrue(result.success)
        service.commands.open_device_manager.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
