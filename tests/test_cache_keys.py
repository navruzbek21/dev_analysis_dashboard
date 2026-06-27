import unittest

from cache_backend import build_cache_key, versioned_payload
from config import CODE_CACHE_VERSION
from filter_utils import normalize_filter_values


class CacheKeyTest(unittest.TestCase):
    def test_filter_order_does_not_change_cache_payload(self):
        self.assertEqual(normalize_filter_values(["b", "a", "b"]), ("a", "b"))

    def test_dataset_version_changes_key(self):
        payload_a = versioned_payload("v1", {"selected_ngdu": ("a",)})
        payload_b = versioned_payload("v2", {"selected_ngdu": ("a",)})
        self.assertNotEqual(build_cache_key("data", payload_a), build_cache_key("data", payload_b))

    def test_code_version_is_in_payload(self):
        payload = versioned_payload("v1", {})
        self.assertEqual(payload["code_version"], CODE_CACHE_VERSION)

    def test_period_parameters_change_key(self):
        key_a = build_cache_key("wc_kiz_periods", versioned_payload("v1", {"n_periods": 6, "min_size": 5}))
        key_b = build_cache_key("wc_kiz_periods", versioned_payload("v1", {"n_periods": 5, "min_size": 5}))
        self.assertNotEqual(key_a, key_b)
