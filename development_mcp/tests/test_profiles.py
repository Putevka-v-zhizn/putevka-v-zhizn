import json
import os
import subprocess
import sys
import unittest


class ProfileTests(unittest.TestCase):
    def profile(self, value):
        environment = dict(os.environ, MCP_PROGRAMS=value)
        return subprocess.run([sys.executable, '-c',
            'import json; from development_mcp.schema import TABLES, PROGRAMS; print(json.dumps({"tables":list(TABLES),"programs":list(PROGRAMS)}))'],
            env=environment, capture_output=True, text=True)

    def test_production_profile_has_no_nto_tables(self):
        result = self.profile('main,family_income')
        self.assertEqual(result.returncode, 0)
        data = json.loads(result.stdout)
        self.assertEqual(set(data['programs']), {'main', 'family_income'})
        self.assertFalse(any(table.startswith('nto_travel_') for table in data['tables']))

    def test_main_only_profile_prunes_other_directions(self):
        result = self.profile('main')
        self.assertEqual(result.returncode, 0)
        data = json.loads(result.stdout)
        self.assertEqual(data['programs'], ['main'])
        self.assertFalse(any(table.startswith(('nto_travel_', 'family_income_')) for table in data['tables']))

    def test_unknown_profile_is_rejected(self):
        self.assertNotEqual(self.profile('main,unknown').returncode, 0)
