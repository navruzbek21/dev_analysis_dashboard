import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
COMPARE = ROOT / "scripts" / "compare_parquet_sql.py"
MIGRATE = ROOT / "scripts" / "migrate_parquet_to_sql.py"


class ParquetSqlParityStaticTest(unittest.TestCase):
    def test_parity_script_uses_required_tolerance_and_metrics(self):
        source = COMPARE.read_text(encoding="utf-8")
        self.assertIn("rtol=1e-9", source)
        self.assertIn("atol=1e-9", source)
        self.assertIn('"q_priem_q_liq"', source)
        self.assertIn('"ratio_dob_nagn"', source)

    def test_migration_checks_area_ngdu_uniqueness_and_debit_pair_base(self):
        migrate_source = MIGRATE.read_text(encoding="utf-8")
        normalization_source = (ROOT / "normalization.py").read_text(encoding="utf-8")
        self.assertIn("validate_area_ngdu_uniqueness", migrate_source)
        self.assertIn('dropna(subset=["debit_neft", "debit_liq"])', normalization_source)
