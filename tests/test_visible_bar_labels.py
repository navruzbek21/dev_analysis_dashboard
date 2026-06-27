import importlib
import unittest

import pandas as pd


class VisibleBarLabelsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            import cache_backend

            cache_backend.redis_client = None
            cls.app = importlib.import_module("app")
        except ImportError as exc:
            raise unittest.SkipTest(f"Dash/Pandas runtime is not installed: {exc}") from exc

    def test_main_change_trace_text_contains_preformatted_percent_labels(self):
        d = pd.DataFrame(
            [
                {"ngdu": "A", "kod_ploshchadi": "P1", "year": 2024, "dobycha_nefti": 100.0, "wc": 40.0, "debit_neft": 3.0},
                {"ngdu": "A", "kod_ploshchadi": "P1", "year": 2025, "dobycha_nefti": 112.345, "wc": 42.0, "debit_neft": 3.2},
                {"ngdu": "A", "kod_ploshchadi": "P2", "year": 2024, "dobycha_nefti": 100.0, "wc": 35.0, "debit_neft": 4.0},
                {"ngdu": "A", "kod_ploshchadi": "P2", "year": 2025, "dobycha_nefti": 95.2, "wc": 37.0, "debit_neft": 3.8},
            ]
        )
        fig = self.app.change_bar(d, "dobycha_nefti", "prev")
        trace_text = []
        for trace in fig.to_plotly_json()["data"]:
            trace_text.extend(list(trace.get("text", [])))
        self.assertIn("+12.3%", trace_text)
        self.assertIn("-4.8%", trace_text)

    def test_g01_yoy_trace_text_contains_preformatted_percent_labels(self):
        yearly_agg = pd.DataFrame(
            [
                {"year": 2023, "dobycha_liq": 130.0, "dobycha_nefti": 100.0, "zakachka": 90.0, "dob_fond": 10.0, "nagn_fond": 5.0, "wc": 30.0, "debit_liq_plot": 6.0, "debit_neft": 4.0},
                {"year": 2024, "dobycha_liq": 150.0, "dobycha_nefti": 112.3, "zakachka": 100.0, "dob_fond": 11.0, "nagn_fond": 5.5, "wc": 35.0, "debit_liq_plot": 6.5, "debit_neft": 4.4},
                {"year": 2025, "dobycha_liq": 140.0, "dobycha_nefti": 106.684, "zakachka": 105.0, "dob_fond": 12.0, "nagn_fond": 6.0, "wc": 40.0, "debit_liq_plot": 6.2, "debit_neft": 4.1},
            ]
        )
        fig = self.app.tech_dynamics(pd.DataFrame([{"year": 2025}]), yearly_agg=yearly_agg)
        yoy_trace = next(trace for trace in fig.to_plotly_json()["data"] if trace.get("name") == "Δ нефти YoY")
        self.assertEqual(list(yoy_trace["text"]), ["+12.3%", "-5.0%"])
        self.assertEqual(yoy_trace["texttemplate"], "%{text}")
