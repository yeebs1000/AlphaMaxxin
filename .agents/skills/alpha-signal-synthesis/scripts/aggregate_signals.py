"""Aggregate supplied, direction-mapped research scores; no market-data access."""
import argparse
import json
import math
from pathlib import Path
import sys

CONFIDENCE = {'High': 1.0, 'Medium': 0.65, 'Low': 0.35}
HORIZONS = {'tactical', 'positional', 'thematic'}


def number(value, label):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError(f'{label} must be a finite number')
    return float(value)


def aggregate(document):
    if not isinstance(document, dict):
        raise ValueError('Input must be a JSON object')
    asset = document.get('asset')
    horizon = document.get('horizon')
    if not isinstance(asset, str) or not asset.strip():
        raise ValueError('asset must be a nonempty identifier')
    if horizon not in HORIZONS:
        raise ValueError('horizon must be tactical, positional, or thematic')
    rows = document.get('inputs')
    if not isinstance(rows, list) or not rows:
        raise ValueError('inputs must be a nonempty list including unavailable eligible channels')
    total_weight = 0.0
    available_weight = 0.0
    used = []
    excluded = []
    names = set()
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError('Each input must be an object')
        name = row.get('name')
        if not isinstance(name, str) or not name.strip() or name in names:
            raise ValueError('Input names must be nonempty and unique')
        names.add(name)
        if row.get('asset') != asset or row.get('horizon') != horizon:
            raise ValueError(f'{name}: asset and horizon must match the aggregation target')
        weight = number(row.get('weight'), f'{name}.weight')
        if weight < 0:
            raise ValueError(f'{name}: negative weights are unsupported')
        total_weight += weight
        if 'score' not in row:
            raise ValueError(f'{name}: provide score, using null for unavailable evidence')
        if row['score'] is None:
            excluded.append({'name': name, 'reason': 'unavailable', 'weight': weight})
            continue
        score = number(row['score'], f'{name}.score')
        if not -2 <= score <= 2:
            raise ValueError(f'{name}: score outside [-2, 2]')
        if row.get('direction_mapped') is not True:
            raise ValueError(f'{name}: explicitly confirm asset-specific bullish/bearish direction mapping')
        confidence = row.get('confidence')
        if confidence not in CONFIDENCE:
            raise ValueError(f'{name}: confidence must be High, Medium, or Low')
        if weight == 0:
            excluded.append({'name': name, 'reason': 'zero weight', 'weight': weight})
            continue
        available_weight += weight
        used.append({'name': name, 'weight': weight, 'score': score,
                     'confidence': confidence, 'confidence_multiplier': CONFIDENCE[confidence],
                     'effective_weight': weight * CONFIDENCE[confidence]})
    if not math.isfinite(total_weight) or total_weight <= 0:
        raise ValueError('Eligible weights must have a finite positive sum')
    denominator = sum(row['effective_weight'] for row in used)
    if not math.isfinite(denominator):
        raise ValueError('Effective weights exceed finite calculation range')
    raw = sum(row['effective_weight'] * row['score'] for row in used) / denominator if denominator else None
    conflicts = []
    for i, left in enumerate(used):
        left['normalized_effective_weight'] = left['effective_weight'] / denominator
        for right in used[i+1:]:
            difference = abs(left['score'] - right['score'])
            if difference > 1.5:
                conflicts.append({'left': left['name'], 'right': right['name'], 'difference': difference})
    adjustments = document.get('adjustments', [])
    if not isinstance(adjustments, list):
        raise ValueError('adjustments must be a list')
    log = []
    adjusted = raw
    for adjustment in adjustments:
        if raw is None:
            raise ValueError('Cannot apply adjustments without usable evidence')
        if not isinstance(adjustment, dict) or not isinstance(adjustment.get('reason'), str) or not adjustment['reason'].strip():
            raise ValueError('Each adjustment requires a nonempty reason')
        delta = number(adjustment.get('delta'), 'adjustment.delta')
        before = adjusted
        adjusted += delta
        if not math.isfinite(adjusted):
            raise ValueError('Adjusted score exceeds finite calculation range')
        log.append({'reason': adjustment['reason'], 'delta': delta, 'before': before, 'after': adjusted})
    final = max(-2.0, min(2.0, adjusted)) if adjusted is not None else None
    cap = document.get('upper_cap')
    if cap is not None:
        cap = number(cap, 'upper_cap')
        if not -2 <= cap <= 2:
            raise ValueError('upper_cap outside [-2, 2]')
        if final is not None:
            before = final
            final = min(final, cap)
            log.append({'reason': 'Explicit upper cap applied after all adjustments and clipping',
                        'before': before, 'after': final, 'upper_cap': cap})
    return {'asset': asset, 'horizon': horizon,
            'status': 'calculated' if raw is not None else 'unavailable',
            'raw_score': raw, 'adjusted_unclipped_score': adjusted, 'final_score': final,
            'eligible_weight': total_weight, 'available_weight': available_weight,
            'coverage': available_weight / total_weight,
            'available_input_confidence_multiplier': denominator / available_weight if available_weight else None,
            'effective_weight_sum': denominator, 'inputs': used, 'excluded': excluded,
            'conflicts': conflicts, 'adjustments': log,
            'note': 'Arithmetic of supplied inputs only; evidence quality, independence and model validity are not certified.'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('input_json', type=Path, help='JSON with asset, horizon and weighted inputs; see the skill reference')
    args = parser.parse_args()
    try:
        result = aggregate(json.loads(args.input_json.read_text(encoding='utf-8-sig')))
        print(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False))
    except (ValueError, OSError, TypeError) as exc:
        print(f'Invalid input: {exc}', file=sys.stderr)
        return 2
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
