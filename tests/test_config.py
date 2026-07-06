import sys
import types
import unittest

from freecad_plm_addon import config


class FakeParams:
    def __init__(self):
        self.strings = {}
        self.ints = {}

    def GetString(self, name, default):
        return self.strings.get(name, default)

    def SetString(self, name, value):
        self.strings[name] = value

    def GetInt(self, name, default):
        return self.ints.get(name, default)

    def SetInt(self, name, value):
        self.ints[name] = value


class ConfigTests(unittest.TestCase):
    def setUp(self):
        self.params = FakeParams()
        sys.modules["FreeCAD"] = types.SimpleNamespace(ParamGet=lambda _path: self.params)

    def tearDown(self):
        sys.modules.pop("FreeCAD", None)

    def test_cache_defaults_are_minimums(self):
        self.assertEqual(config.get_cache_max_fcstd_files(), 20)
        self.assertEqual(config.get_cache_max_projects(), 5)
        self.assertEqual(config.get_cache_max_revisions_per_project(), 5)

    def test_cache_values_below_minimum_are_clamped(self):
        self.params.ints["cache_max_fcstd_files"] = 1
        self.params.ints["cache_max_projects"] = 1
        self.params.ints["cache_max_revisions_per_project"] = 1

        self.assertEqual(config.get_cache_max_fcstd_files(), 20)
        self.assertEqual(config.get_cache_max_projects(), 5)
        self.assertEqual(config.get_cache_max_revisions_per_project(), 5)

    def test_cache_setters_clamp_to_minimum(self):
        config.set_cache_max_fcstd_files(1)
        config.set_cache_max_projects(1)
        config.set_cache_max_revisions_per_project(1)

        self.assertEqual(self.params.ints["cache_max_fcstd_files"], 20)
        self.assertEqual(self.params.ints["cache_max_projects"], 5)
        self.assertEqual(self.params.ints["cache_max_revisions_per_project"], 5)


if __name__ == "__main__":
    unittest.main()
