import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
REPOSITORY = ROOT / "repositories" / "metrics_repository.py"


class RepositoryStaticTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = REPOSITORY.read_text(encoding="utf-8")

    def test_repository_uses_sqlalchemy_core_selects(self):
        self.assertIn("select(", self.source)
        self.assertNotIn("SELECT *", self.source)
        self.assertNotIn("f\"SELECT", self.source)

    def test_empty_filters_do_not_create_in_clause(self):
        self.assertIn("if selected_ngdu:", self.source)
        self.assertIn("if selected_areas:", self.source)

    def test_repository_selects_expected_columns(self):
        self.assertIn("YEAR_METRIC_COLUMNS", self.source)
        self.assertIn('"mest"', self.source)
        self.assertIn('"q_priem_q_liq"', self.source)
        self.assertIn('"temp_promyvki"', self.source)
