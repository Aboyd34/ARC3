import unittest

from app.services.android_device_service import AndroidDeviceService


class AndroidDeviceServiceTests(unittest.TestCase):
    def test_parse_adb_devices(self):
        output = """List of devices attached
R58M1234567 device product:a03s model:SM_A037U1 device:a03su transport_id:1
emulator-5554 unauthorized transport_id:2
"""
        devices = AndroidDeviceService.parse_adb_devices(output)
        self.assertEqual(len(devices), 2)
        self.assertEqual(devices[0]["serial"], "R58M1234567")
        self.assertEqual(devices[0]["model"], "SM A037U1")
        self.assertEqual(devices[1]["state"], "unauthorized")

    def test_parse_fastboot_devices(self):
        devices = AndroidDeviceService.parse_fastboot_devices("ZY22ABC123\tfastboot\n")
        self.assertEqual(devices[0]["serial"], "ZY22ABC123")
        self.assertEqual(devices[0]["mode"], "Fastboot")

    def test_parse_adb_ignores_daemon_messages(self):
        output = "* daemon started successfully\nList of devices attached\n"
        self.assertEqual(AndroidDeviceService.parse_adb_devices(output), [])


if __name__ == "__main__":
    unittest.main()
