"""Check the conventional launch without installing the application."""
import os
from pathlib import Path
import subprocess
import sys
import unittest

ROOT = Path(__file__).resolve().parent.parent


class LaunchTests(unittest.TestCase):
    def run_cli(self, *args):
        env = os.environ.copy()
        env.pop('PYTHONPATH', None)
        env['PYTHONDONTWRITEBYTECODE'] = '1'
        return subprocess.run([sys.executable, '-m', 'liminal_desk_cli', *args],
                              cwd=ROOT, env=env, text=True, capture_output=True, timeout=10)

    def test_root_launch_and_default_examples(self):
        result = self.run_cli('--check')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('36 machine + 2644 sensor messages; duration 66.000s', result.stdout)

    def test_help_without_network(self):
        result = self.run_cli('--help')
        self.assertEqual(result.returncode, 0, result.stderr)
        for option in ('--dry-run', '--host', '--check'):
            self.assertIn(option, result.stdout)

    def test_explicit_paths_and_invalid_inputs(self):
        files = [str(ROOT/'examples/shop_floor'/name) for name in
                 ('machine_events.json', 'sensor_events.json')]
        self.assertEqual(self.run_cli(*files, '--check').returncode, 0)
        self.assertEqual(self.run_cli('missing.json', '--check').returncode, 1)

    def test_engine_import_does_not_load_ui_or_mqtt(self):
        code = ('import sys; import liminal_desk_cli.replay.engine; '
                'assert "curses" not in sys.modules; '
                'assert "paho.mqtt.client" not in sys.modules; '
                'assert "liminal_desk_cli.ui.app" not in sys.modules')
        result = subprocess.run([sys.executable, '-B', '-c', code], cwd=ROOT,
                                text=True, capture_output=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
