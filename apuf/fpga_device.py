import glob
import json
import logging
import re
import subprocess
import sys
from pathlib import Path

logger = logging.getLogger("fpga_worker")


OPENFPGA_PATH = "/opt/openFPGALoader/build/openFPGALoader"


class FPGADevice:
    """
    Attributes:
        serial: Alphanumeric ID of the device (i.e. 210376B853A9)
        jtag_path:
        uart_path:
        family_prefix: Identifier to prefix the serial id, based on the type of device (i.e. "CMOD_S7" or "ARTYX_A7")
        board_type: The flag for openFPGALoader (e.g., 'cmod_s7')
        device_id: Consistent global ID used in the DB. Composed as "{family_prefix}-{serial}"
    """

    def __init__(
        self,
        serial: str,
        jtag_path: str,
        uart_path: str,
        family_prefix: str,
        board_type: str,
        openfpga_bin: str = OPENFPGA_PATH,
    ):
        self.serial = serial
        self.jtag_path = jtag_path
        self.uart_path = uart_path
        self.family_prefix = family_prefix
        self.board_type = board_type
        self.device_id = f"{self.family_prefix}-{self.serial}"
        self.openfpga_bin = openfpga_bin

    def program(self, bitstream_path: str) -> bool:
        """Programs the FPGA and returns True if successful."""
        if not Path(bitstream_path).is_file():
            logger.error(f"[{self.device_id}] Bitstream not found: {bitstream_path}")
            return False

        logger.info(
            f"[{self.device_id}] Loading bitstream {bitstream_path} via JTAG ({self.board_type})..."
        )
        cmd = [
            self.openfpga_bin,
            "-b",
            self.board_type,
            "--ftdi-serial",
            self.serial,
            "--ftdi-channel",
            "0",
            "-m",
            bitstream_path,
        ]
        try:
            result = subprocess.run(cmd, capture_output=True, text=True)
        except OSError as exc:
            logger.error(f"[{self.device_id}] Could not run openFPGALoader: {exc}")
            return False

        if result.returncode != 0:
            logger.error(f"[{self.device_id}] Programming FAILED:\n{result.stderr}")
            return False
        return True

    def build_worker_cmd(
        self,
        command: str,
        params: dict,
        stages: int,
        slice_loc: str,
        log_path: str,
    ) -> list:

        cmd = [
            sys.executable,
            "-m",
            "apuf.fpga_worker",
            "--log_file",
            str(log_path),
            "--serial_port",
            str(self.uart_path),
            "--device",
            str(self.device_id),
            "--baud",
            str(params["baud"]),
            "--stages",
            str(stages),
            "--slice_loc",
            str(slice_loc),
            "--placement_variant",
            str(params.get("placement_variant", "lr_abcd")),
            "--placement_gap",
            str(params.get("placement_gap", 1)),
            "--placement_offset",
            str(params.get("placement_offset", 0)),
            command,
        ]

        cmd.extend(["--db_dir", str(params["db_dir"])])
        if "samples" in params:
            cmd.extend(["--samples", str(params["samples"])])
        if "chunk_size" in params:
            cmd.extend(["--chunk_size", str(params["chunk_size"])])
        cmd.extend(["--challenges_file", str(params["challenges_file"])])
        if params.get("take_lsb"):
            cmd.append("--take_lsb")

        return cmd

    def read_sensors(self):
        """Reads the XADC sensors. Returns None if failed."""
        cmd = [
            self.openfpga_bin,
            "-b",
            self.board_type,
            "--ftdi-serial",
            self.serial,
            "-X",
        ]
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=5)
            sensors_str = "".join(result.stdout.splitlines()[1:])
            return json.loads(sensors_str)
        except Exception as e:
            logger.warning(f"[{self.device_id}] XADC read failed: {e}")
        return None


def discover_hardware(families_config):
    """
    Scans connected devices and assigns them to their respective hardware profile.
    Returns a list of `FPGADevice`
    """
    all_serial_paths = glob.glob("/dev/serial/by-id/*")
    discovered = []

    compiled_rules = {
        name: re.compile(cfg["match_pattern"]) for name, cfg in families_config.items()
    }

    # Group raw system paths by physical device serial
    device_groups = {}

    for path in all_serial_paths:
        filename = path.split("/")[-1]

        for fam_name, regex in compiled_rules.items():
            match = regex.match(filename)
            if match:
                serial_num = match.group(1)
                iface_num = match.group(2)

                if serial_num not in device_groups:
                    device_groups[serial_num] = {"family": fam_name, "paths": {}}

                device_groups[serial_num]["paths"][iface_num] = path
                break  # Matched this path, move to next file

    for serial_num, info in device_groups.items():
        cfg = families_config[info["family"]]
        jtag_idx = cfg["jtag_interface"]
        uart_idx = cfg["uart_interface"]

        if jtag_idx in info["paths"] and uart_idx in info["paths"]:
            discovered.append(
                FPGADevice(
                    serial_num,
                    info["paths"][jtag_idx],
                    info["paths"][uart_idx],
                    cfg["prefix"],
                    info["family"],
                )
            )

    return discovered
