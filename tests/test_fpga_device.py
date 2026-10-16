import sys
import unittest
from unittest.mock import patch

from apuf.fpga_device import FPGADevice


class FPGADeviceTests(unittest.TestCase):
    def setUp(self):
        self.device = FPGADevice(
            serial="TEST123",
            jtag_path="/dev/jtag",
            uart_path="/dev/uart",
            family_prefix="CMOD_S7",
            board_type="cmod_s7",
        )

    def test_worker_uses_current_python_module(self):
        params = {
            "baud": 1_000_000,
            "db_dir": "data/test",
            "challenges_file": "data/challenges.npy",
        }

        cmd = self.device.build_worker_cmd(
            "study", params, 64, "LEFT-LOWER-0", "data/logs/device.log"
        )

        self.assertEqual(cmd[:3], [sys.executable, "-m", "apuf.fpga_worker"])
        self.assertNotIn("worker_script", cmd)

    @patch("apuf.fpga_device.subprocess.run")
    def test_missing_bitstream_does_not_invoke_loader(self, run):
        self.assertFalse(self.device.program("missing/top.bit"))
        run.assert_not_called()


if __name__ == "__main__":
    unittest.main()
