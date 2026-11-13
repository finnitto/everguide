import csv, tempfile, unittest
from pathlib import Path
from build_registers import build

class PilotRegisterTests(unittest.TestCase):
    def test_expected_thurrock_register_counts_and_pending_defaults(self):
        with tempfile.TemporaryDirectory() as tmp:
            out=Path(tmp)
            total, branches, providers=build(Path(__file__).with_name('candidate_quality_review.csv'),out)
            self.assertEqual((total,branches,providers),(16,13,9))
            with (out/'provider_verification_register.csv').open(encoding='utf-8-sig',newline='') as f:
                ps=list(csv.DictReader(f))
            with (out/'branch_verification_register.csv').open(encoding='utf-8-sig',newline='') as f:
                bs=list(csv.DictReader(f))
            self.assertTrue(all(x['provider_decision']=='pending' for x in ps))
            self.assertTrue(all(x['branch_decision']=='pending' for x in bs))
            self.assertIn('PG005',{x['provider_group_id'] for x in ps})
            self.assertTrue(any(x['postcode']=='G73 2AW' for x in bs))

if __name__=='__main__': unittest.main()
