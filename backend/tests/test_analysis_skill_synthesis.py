import importlib.util
from pathlib import Path
import math
import unittest

source = Path(__file__).resolve().parents[2] / '.agents' / 'skills' / 'alpha-signal-synthesis' / 'scripts' / 'aggregate_signals.py'
spec = importlib.util.spec_from_file_location('aggregate_signals', source)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def row(name, score, weight=1, confidence='High', **extra):
    return dict(name=name, score=score, weight=weight, confidence=confidence,
                asset='EXAMPLE', horizon='positional', direction_mapped=True, **extra)


def doc(*rows, **extra):
    return dict(asset='EXAMPLE', horizon='positional', inputs=list(rows), **extra)


class AggregateTests(unittest.TestCase):
    def test_weighted_missing_coverage_conflict(self):
        result = module.aggregate(doc(row('fundamental', 1.2, 18),
                                      row('technical', -0.5, 13, 'Medium'), row('rest', None, 69)))
        self.assertAlmostEqual(result['raw_score'], (18*1.2-13*.65*.5)/(18+13*.65))
        self.assertAlmostEqual(result['coverage'], .31)
        self.assertEqual(len(result['conflicts']), 1)
        self.assertAlmostEqual(sum(x['normalized_effective_weight'] for x in result['inputs']), 1)

    def test_weight_rescaling_invariance(self):
        a = module.aggregate(doc(row('a', 1.7, 18), row('b', -1.1, 13)))
        b = module.aggregate(doc(row('a', 1.7, .18), row('b', -1.1, .13)))
        self.assertAlmostEqual(a['raw_score'], b['raw_score'])

    def test_unavailable_is_not_neutral(self):
        result = module.aggregate(doc(row('a', None)))
        self.assertIsNone(result['raw_score'])
        self.assertEqual(result['status'], 'unavailable')

    def test_confidence_is_not_probability(self):
        result = module.aggregate(doc(row('a', 2, confidence='Low')))
        self.assertEqual(result['raw_score'], 2)
        self.assertEqual(result['available_input_confidence_multiplier'], .35)

    def test_cap_after_bonus(self):
        result = module.aggregate(doc(row('a', 2), adjustments=[{'reason':'scenario', 'delta':.5}], upper_cap=-1))
        self.assertEqual(result['adjusted_unclipped_score'], 2.5)
        self.assertEqual(result['final_score'], -1)

    def test_mixed_assets_horizons_or_unmapped(self):
        for key, value in [('asset', 'OTHER'), ('horizon', 'tactical'), ('direction_mapped', False)]:
            a = row('a', 1)
            a[key] = value
            with self.assertRaises(ValueError):
                module.aggregate(doc(a))

    def test_nonfinite_bool_and_out_of_range(self):
        for value in [math.nan, math.inf, True, 2.1, -2.1]:
            with self.assertRaises(ValueError):
                module.aggregate(doc(row('a', value)))

    def test_invalid_weights_and_duplicate_channels(self):
        for value in [-1, 0, math.inf, True]:
            with self.assertRaises(ValueError):
                module.aggregate(doc(row('a', 1, value)))
        with self.assertRaises(ValueError):
            module.aggregate(doc(row('a', 1), row('a', -1)))

    def test_no_manufactured_score_from_adjustment(self):
        with self.assertRaises(ValueError):
            module.aggregate(doc(row('a', None), adjustments=[{'reason':'scenario','delta':1}]))

    def test_strict_conflict_boundary(self):
        result = module.aggregate(doc(row('a', 1), row('b', -.5)))
        self.assertEqual(result['conflicts'], [])


if __name__ == '__main__':
    unittest.main()
