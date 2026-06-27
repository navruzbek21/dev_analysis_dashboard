import ast
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
LEGACY_APP = ROOT / "legacy" / "app_tatneft_g17_g20_diag.py"
LEGACY_CSS = ROOT / "legacy" / "operator_tatneft_style.css"
SOURCE_APP = ROOT / "app_tatneft_g17_g20_diag.py"
SOURCE_CSS = ROOT / "operator_tatneft_style.css"


REQUIRED_IDS = {
    "ngdu-filter",
    "area-filter",
    "reset-filters",
    "scenario-tabs",
    "dataset-badge",
    "executive-kpi",
    "scenario-content",
    "main-metric",
    "change-period",
    "main-bar",
    "main-line",
    "main-change",
    "main-cross",
    "g01",
    "g02",
    "g03",
    "g04",
    "g05",
    "g06",
    "g07",
    "g08",
    "g09",
    "g10",
    "g11",
    "g12",
    "g13",
    "g14",
    "g15",
    "g16",
    "g17",
    "g18",
    "g19",
    "g20",
    "g21",
    "g22",
}


EXPECTED_ANALYSIS_ORDER = [
    "g04",
    "g05",
    "g06",
    "g07",
    "g08",
    "g09",
    "g10",
    "g12",
    "g13",
    "g14",
    "g15",
    "g16",
    "g17",
    "g18",
    "g19",
    "g20",
    "g21",
    "g22",
]


def _source() -> str:
    return LEGACY_APP.read_text(encoding="utf-8")


def _tree() -> ast.Module:
    return ast.parse(_source())


def _function_names(tree: ast.Module) -> set[str]:
    return {node.name for node in tree.body if isinstance(node, ast.FunctionDef)}


def _analysis_specs_order(tree: ast.Module) -> list[str]:
    for node in tree.body:
        if isinstance(node, ast.Assign):
            if any(isinstance(target, ast.Name) and target.id == "ANALYSIS_SPECS" for target in node.targets):
                specs = ast.literal_eval(node.value)
                return [spec[0] for spec in specs]
    raise AssertionError("ANALYSIS_SPECS not found in legacy app")


class LegacyBaselineContractTest(unittest.TestCase):
    def test_legacy_copies_exist_and_match_source_files(self):
        self.assertTrue(LEGACY_APP.exists())
        self.assertTrue(LEGACY_CSS.exists())
        self.assertEqual(LEGACY_APP.read_bytes(), SOURCE_APP.read_bytes())
        self.assertEqual(LEGACY_CSS.read_bytes(), SOURCE_CSS.read_bytes())

    def test_legacy_dash_ids_are_present(self):
        source = _source()
        missing = [component_id for component_id in sorted(REQUIRED_IDS) if f'"{component_id}"' not in source]
        self.assertEqual(missing, [])

    def test_legacy_keeps_dynamic_scenario_content_and_single_update_asset(self):
        tree = _tree()
        function_names = _function_names(tree)
        self.assertIn("render_tab", function_names)
        self.assertIn("update_asset", function_names)
        self.assertEqual([name for name in function_names if name == "update_asset"], ["update_asset"])
        self.assertIn('html.Div(id="scenario-content")', _source())
        self.assertIn("suppress_callback_exceptions=True", _source())

    def test_legacy_analysis_specs_order_is_baseline_contract(self):
        self.assertEqual(_analysis_specs_order(_tree()), EXPECTED_ANALYSIS_ORDER)

    def test_legacy_special_graph_functions_are_kept(self):
        function_names = _function_names(_tree())
        self.assertTrue({"segmented_wc_kiz", "niz_otbor_vs_wc_identity", "ratio_vs_q_by_wc_kiz_periods"}.issubset(function_names))
