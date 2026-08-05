import unittest
from unittest.mock import MagicMock, patch

from app.services.startup_service import StartupService


class StartupActionTests(unittest.TestCase):
    @patch("app.services.startup_service.ctypes.windll.shell32.ShellExecuteW")
    @patch("app.services.startup_service.winreg.SetValueEx")
    @patch("app.services.startup_service.winreg.CreateKey")
    def test_registry_launcher_uses_windows_shell_for_elevation(
        self, create_key, set_value, shell_execute,
    ):
        create_key.return_value.__enter__ = MagicMock(return_value=object())
        create_key.return_value.__exit__ = MagicMock(return_value=False)
        shell_execute.return_value = 42

        success, message = StartupService.open_registry_location(
            r"HKCU\Software\Microsoft\Windows\CurrentVersion\Run"
        )

        self.assertTrue(success)
        self.assertEqual(message, "")
        shell_execute.assert_called_once_with(
            None, "open", "regedit.exe", "/m", None, 1,
        )
        self.assertIn("Computer\\HKEY_CURRENT_USER", set_value.call_args.args[-1])

    @patch("app.services.startup_service.ctypes.windll.shell32.ShellExecuteW")
    @patch("app.services.startup_service.winreg.SetValueEx")
    @patch("app.services.startup_service.winreg.CreateKey")
    def test_registry_launcher_returns_a_controlled_windows_error(
        self, create_key, _set_value, shell_execute,
    ):
        create_key.return_value.__enter__ = MagicMock(return_value=object())
        create_key.return_value.__exit__ = MagicMock(return_value=False)
        shell_execute.return_value = 5

        success, message = StartupService.open_registry_location(
            r"HKLM\Software\Microsoft\Windows\CurrentVersion\Run"
        )

        self.assertFalse(success)
        self.assertIn("code 5", message)


if __name__ == "__main__":
    unittest.main()
