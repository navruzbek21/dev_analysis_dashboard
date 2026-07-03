import ast
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "app.py"
CSS = ROOT / "operator_tatneft_style.css"
ASSET_CSS = ROOT / "assets" / "operator_tatneft_style.css"


EXPECTED_PRIMARY_OUTPUTS = ["g01", "g02", "g03", "g16", "g20", "g11"]
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
    "g_disp_pirverdyan",
    "g_disp_wor",
    "g_disp_kambarov",
    "g_disp_sazonov",
    "g_disp_maximov",
]


class MigratedStaticContractTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = APP.read_text(encoding="utf-8")
        cls.tree = ast.parse(cls.source)

    def test_assets_css_is_identical_to_source_css(self):
        self.assertEqual(ASSET_CSS.read_bytes(), CSS.read_bytes())
        self.assertIn("overflow: visible", ASSET_CSS.read_text(encoding="utf-8"))

    def test_app_exports_server_and_keeps_dynamic_scenario_content(self):
        self.assertIn("server = app.server", self.source)
        self.assertIn('html.Div(id="scenario-content")', self.source)
        self.assertIn("suppress_callback_exceptions=True", self.source)
        self.assertIn('assets_folder="assets"', self.source)

    def test_update_asset_callback_order_is_preserved(self):
        for graph_id in EXPECTED_PRIMARY_OUTPUTS:
            self.assertIn(f'Output("{graph_id}", "figure")', self.source)
        self.assertIn('Output("additional-metrics-container", "style")', self.source)
        self.assertIn('*[Output(spec[0], "figure") for spec in ADDITIONAL_ANALYSIS_SPECS]', self.source)
        self.assertIn('graph_card("1. Динамика основных технологических показателей разработки", "g01"', self.source)

        analysis_order = []
        for node in self.tree.body:
            if isinstance(node, ast.Assign):
                if any(isinstance(target, ast.Name) and target.id == "ANALYSIS_SPECS" for target in node.targets):
                    analysis_order = [spec[0] for spec in ast.literal_eval(node.value)]
        self.assertEqual(analysis_order, EXPECTED_ANALYSIS_ORDER)

    def test_single_update_asset_and_render_tab_remain(self):
        function_names = [node.name for node in self.tree.body if isinstance(node, ast.FunctionDef)]
        self.assertEqual(function_names.count("update_asset"), 1)
        self.assertIn("render_tab", function_names)

    def test_visible_bar_labels_are_preformatted_in_trace_text(self):
        self.assertIn("def format_visible_pct_label", self.source)
        self.assertGreaterEqual(self.source.count('texttemplate="%{text}"'), 3)
        self.assertNotIn('texttemplate="%{y:+.1f}%"', self.source)

    def test_update_asset_uses_shared_period_result_for_g16_and_g20(self):
        self.assertIn("period_result = periods_service.get_wc_kiz_periods", self.source)
        self.assertIn("segmented_wc_kiz(d, period_result=period_result)", self.source)
        self.assertIn("ratio_vs_q_by_wc_kiz_periods(d, period_result=period_result)", self.source)

    def test_global_filters_include_all_options_and_mest(self):
        self.assertIn('id="mest-filter"', self.source)
        self.assertIn("Все НГДУ", self.source)
        self.assertIn("Все площади", self.source)
        self.assertIn("Все месторождения", self.source)
