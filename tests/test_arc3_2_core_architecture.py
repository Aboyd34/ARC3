import unittest
from unittest.mock import Mock, patch

from app.core.results import OperationResult
from app.safety.process_operations import ProcessOperationPolicy
from app.services.process_service import ProcessService


class ProcessArchitectureTests(unittest.TestCase):
    def test_policy_protects_arc3_system_pids_and_names(self):
        self.assertTrue(ProcessOperationPolicy.is_protected(123, "worker.exe", 123))
        self.assertTrue(ProcessOperationPolicy.is_protected(4, "System", 123))
        self.assertTrue(ProcessOperationPolicy.is_protected(999, " LSASS.EXE ", 123))
        self.assertFalse(ProcessOperationPolicy.is_protected(999, "notepad.exe", 123))

    @patch("app.services.process_service.psutil.Process")
    def test_protected_process_is_not_terminated(self, process_factory):
        process = Mock()
        process.name.return_value = "lsass.exe"
        process_factory.return_value = process
        service = ProcessService()

        result = service.terminate_process(999)

        self.assertIsInstance(result, OperationResult)
        self.assertFalse(result.success)
        process.terminate.assert_not_called()

    @patch("app.services.process_service.psutil.Process")
    def test_termination_result_preserves_tuple_contract(self, process_factory):
        process = Mock()
        process.name.return_value = "notepad.exe"
        process_factory.return_value = process
        service = ProcessService()

        result = service.terminate_process(999)
        successful, message = result

        self.assertTrue(successful)
        self.assertIn("notepad.exe", message)
        process.terminate.assert_called_once_with()
        process.wait.assert_called_once_with(timeout=4)


if __name__ == "__main__":
    unittest.main()
