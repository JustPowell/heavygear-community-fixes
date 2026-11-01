import json
import multiprocessing
import sys
import tempfile
import unittest
from multiprocessing.connection import Client
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import win_elevation


@unittest.skipIf(sys.platform == "win32", "uses a Unix socket in place of the Windows pipe")
class ElevationTransportTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.address = str(Path(self.directory.name) / "result.sock")

    def run_with(self, run, before_child=None):
        seen = {}

        def launch(encoded):
            config, address, key = win_elevation.decode_request(encoded)
            seen["config"] = config
            if before_child:
                before_child(address)
            return win_elevation.elevated_entry(encoded, run)

        output = win_elevation.run_elevated({"operation": "x"}, launch, self.address)
        return output, seen

    def test_output_comes_back_and_config_reaches_the_child(self):
        output, seen = self.run_with(lambda config: f"ran {config['operation']}")
        self.assertEqual(output, "ran x")
        self.assertEqual(seen["config"], {"operation": "x"})

    def test_child_error_is_raised_with_its_message(self):
        def fail(_config):
            raise ValueError("clean disc required")

        with self.assertRaisesRegex(RuntimeError, "clean disc required"):
            self.run_with(fail)

    def test_missing_result_is_an_error_not_silent_success(self):
        with self.assertRaisesRegex(RuntimeError, "without reporting a result"):
            win_elevation.run_elevated({}, lambda encoded: 0, self.address)

    def test_failed_child_without_result_reports_exit_code(self):
        with self.assertRaisesRegex(RuntimeError, "exit code 7"):
            win_elevation.run_elevated({}, lambda encoded: 7, self.address)

    def test_a_stranger_without_the_key_cannot_inject_a_result(self):
        def stranger(address):
            with self.assertRaises(multiprocessing.AuthenticationError):
                Client(address, authkey=b"wrong key").send_bytes(
                    json.dumps({"output": "spoofed"}).encode()
                )

        output, _seen = self.run_with(lambda config: "genuine", before_child=stranger)
        self.assertEqual(output, "genuine")

    def test_request_round_trips_through_the_command_line_encoding(self):
        encoded = win_elevation.encode_request({"a": [1, "é"]}, "addr", b"\x01\x02")
        self.assertTrue(encoded.isascii())
        self.assertEqual(win_elevation.decode_request(encoded), ({"a": [1, "é"]}, "addr", b"\x01\x02"))


if __name__ == "__main__":
    unittest.main()
