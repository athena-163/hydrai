import tempfile
import unittest
from pathlib import Path

from intelligence.config import ConfigError, load_config


class ConfigTests(unittest.TestCase):
    def test_load_example_config(self):
        config_path = Path(__file__).resolve().parents[1] / "Configs" / "config.example.json"
        config = load_config(config_path)
        self.assertEqual(len(config.routes), 6)
        self.assertEqual(config.routes[0].listen, 61201)

    def test_duplicate_port_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "bad.json"
            path.write_text(
                '{"routes":['
                '{"name":"a","type":"chat","adapter":"remote","listen":6101,"model":"m","target":"https://x","limits":{"max_concurrency":1,"timeout_sec":1}},'
                '{"name":"b","type":"chat","adapter":"remote","listen":6101,"model":"m","target":"https://x","limits":{"max_concurrency":1,"timeout_sec":1}}'
                ']}'
            )
            with self.assertRaises(ConfigError):
                load_config(path)

    def test_invalid_type_adapter_combo_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "bad.json"
            path.write_text(
                '{"routes":['
                '{"name":"bad","type":"embedding","adapter":"remote","listen":6101,"model":"m","target":"https://x","limits":{"max_concurrency":1,"timeout_sec":1}}'
                ']}'
            )
            with self.assertRaises(ConfigError):
                load_config(path)


if __name__ == "__main__":
    unittest.main()
