import json
import hashlib
import pandas as pd
from pathlib import Path

def test_canonical_invariants_and_hashes():
    raw_path = Path('data/raw/trades_raw.tsv')
    assert raw_path.exists(), "Raw trades dataset must exist"

    raw_bytes = raw_path.read_bytes()
    expected_hash = "3B22B24C5F7BEB2118FFEC613640A9AB1472C3D04E4503229D00771277E4B6BD"
    assert hashlib.sha256(raw_bytes).hexdigest().upper() == expected_hash

    df = pd.read_csv(raw_path, sep='\t', header=None,
                     names=['ticket', 'side', 'open_time', 'close_time', 'symbol', 'volume', 'close_price', 'pnl'],
                     dtype={'ticket': str, 'volume': str, 'close_price': str, 'pnl': str})

    assert len(df) == 423
    assert (df['side'] == 'Buy').sum() == 214
    assert (df['side'] == 'Sell').sum() == 209
    assert (df['symbol'] == 'XAUUSD.f').all()
    assert (df['volume'] == '0.01').sum() == 401
    assert (df['volume'] == '0.02').sum() == 21
    assert (df['volume'] == '0.03').sum() == 1
    assert round(df['pnl'].astype(float).sum(), 2) == 1451.22

def test_multidimensional_fingerprints_integrity():
    fp_path = Path('outputs/public_source_verification/source_evidence/multidimensional_fingerprints.json')
    assert fp_path.exists(), "Multidimensional fingerprints JSON must exist"

    data = json.loads(fp_path.read_text(encoding='utf-8'))
    expected_clusters = [
        'CLUSTER_EARLY_01',
        'CLUSTER_VOL_ANOMALY_02',
        'CLUSTER_HIGH_PRICE_03',
        'CLUSTER_ASYMMETRIC_LOSS_04',
        'CLUSTER_TERMINAL_05'
    ]
    for cid in expected_clusters:
        assert cid in data
        assert len(data[cid]['trades']) == 5
        for trade in data[cid]['trades']:
            assert 'canonical_ticket' in trade
            assert 'timezone_variants' in trade
            assert 'UTC+0_GMT' in trade['timezone_variants']
            assert 'UTC+3_Broker' in trade['timezone_variants']

def test_search_results_audit():
    csv_path = Path('outputs/public_source_verification/multidimensional_search_results.csv')
    assert csv_path.exists(), "Search results CSV must exist"

    df_res = pd.read_csv(csv_path)
    assert len(df_res) >= 15
    assert (df_res['candidate_matches_found'] == 0).all()
    assert (df_res['exact_tuple_matches'] == 0).all()
    assert (df_res['evaluation_verdict'] == 'REJECTED').all()
