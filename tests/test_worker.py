import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from apuf import fpga_worker


class WorkerTests(unittest.TestCase):
    def setUp(self):
        self.args = SimpleNamespace(
            log_file=None,
            device="CMOD_S7-TEST123",
            chunk_size=1,
            serial_port="/dev/uart",
            baud=1_000_000,
        )

    @patch("apuf.fpga_worker.setup_worker_logger")
    @patch("apuf.fpga_worker.serial.Serial", side_effect=OSError("serial unavailable"))
    @patch("apuf.fpga_worker.get_args")
    def test_serial_failure_returns_nonzero(self, get_args, _serial, setup_logger):
        get_args.return_value = self.args
        logger = MagicMock()
        setup_logger.return_value = logger

        self.assertEqual(fpga_worker.run_worker(), 1)
        logger.exception.assert_called_once()

    @patch("apuf.fpga_worker.get_challenges", side_effect=ValueError("bad input"))
    @patch("apuf.fpga_worker.setup_worker_logger")
    @patch("apuf.fpga_worker.serial.Serial")
    @patch("apuf.fpga_worker.get_args")
    def test_failure_after_connect_closes_serial(
        self, get_args, serial_class, setup_logger, _get_challenges
    ):
        get_args.return_value = self.args
        setup_logger.return_value = MagicMock()
        serial_port = serial_class.return_value

        self.assertEqual(fpga_worker.run_worker(), 1)
        serial_port.close.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
