"""`output.resolve` maps a stored device name to the current PortAudio index.

Names are stored because PortAudio renumbers devices on every hotplug; an
input-only device must never be picked even if its name matches.
"""

import unittest

from addictune_cli.src.audio import output

_TABLE = [
    {"name": "External Monitor", "max_output_channels": 2},
    {"name": "Built-in Microphone", "max_output_channels": 0},
    {"name": "Built-in Speakers", "max_output_channels": 2},
]


class ResolveTests(unittest.TestCase):
    def test_none_means_system_default(self) -> None:
        self.assertIsNone(output.resolve(None, _TABLE))

    def test_named_device_resolves_to_its_current_index(self) -> None:
        self.assertEqual(output.resolve("Built-in Speakers", _TABLE), 2)

    def test_missing_device_is_none(self) -> None:
        self.assertIsNone(output.resolve("Unplugged DAC", _TABLE))

    def test_input_only_device_is_none(self) -> None:
        self.assertIsNone(output.resolve("Built-in Microphone", _TABLE))

    def test_output_names_skip_input_only_devices(self) -> None:
        self.assertEqual(
            output.output_names(_TABLE), ["External Monitor", "Built-in Speakers"]
        )


class SignatureTests(unittest.TestCase):
    def test_signature_is_hashable_and_stable(self) -> None:
        first = output.signature()
        hash(first)
        self.assertEqual(first, output.signature())


class ConfigTests(unittest.TestCase):
    def test_defaults_follow_system(self) -> None:
        cfg = output.OutputConfig()
        self.assertIsNone(cfg.device_name)
        self.assertIsNone(cfg.sample_rate)
        self.assertEqual(cfg.latency, "high")

    def test_round_trips_json(self) -> None:
        cfg = output.OutputConfig(device_name="DAC", sample_rate=48000, latency="low")
        self.assertEqual(
            output.OutputConfig.model_validate_json(cfg.model_dump_json()), cfg
        )


if __name__ == "__main__":
    unittest.main()
