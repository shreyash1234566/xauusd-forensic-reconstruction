import pandas as pd
import numpy as np
from pathlib import Path
from datetime import datetime
import json

ROOT = Path(".")
M1_PATH = ROOT / "data" / "market" / "normalized" / "xauusd_m1.csv"
TRADES_PATH = ROOT / "outputs" / "market_reconstruction" / "phase7c_trade_reconciliation.csv"

print("Loading data...")
m1 = pd.read_csv(M1_PATH)
m1['dt'] = pd.to_datetime(m1['timestamp'])
trades = pd.read_csv(TRADES_PATH)
trades['open_utc_dt'] = pd.to_datetime(trades['open_time_utc'])
trades['open_m1_bar'] = trades['open_utc_dt'].dt.floor('min')

print(f"Loaded {len(m1)} M1 bars and {len(trades)} trades.")

# 1. Feature Engineering across Timeframes
def compute_indicators(df):
    c = df['close']
    h = df['high']
    l = df['low']
    o = df['open']
    v = df['volume']

    feat = pd.DataFrame(index=df.index)
    feat['dt'] = df['dt']
    feat['close'] = c

    # Moving averages
    for p in [8, 14, 21, 50, 100, 200]:
        feat[f'ema_{p}'] = c.ewm(span=p, adjust=False).mean()
        feat[f'dist_ema_{p}'] = (c - feat[f'ema_{p}']) / feat[f'ema_{p}'] * 10000.0

    feat['ema_8_21_cross'] = feat['ema_8'] - feat['ema_21']
    feat['ema_21_50_cross'] = feat['ema_21'] - feat['ema_50']

    # RSI
    for p in [7, 14, 21]:
        delta = c.diff()
        gain = (delta.where(delta > 0, 0)).rolling(p).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(p).mean()
        rs = gain / (loss + 1e-9)
        feat[f'rsi_{p}'] = 100.0 - (100.0 / (1.0 + rs))

    # ATR
    for p in [7, 14]:
        tr1 = h - l
        tr2 = (h - c.shift(1)).abs()
        tr3 = (l - c.shift(1)).abs()
        tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
        feat[f'atr_{p}'] = tr.rolling(p).mean()
        feat[f'atr_pct_{p}'] = feat[f'atr_{p}'] / c * 100.0

    # Bollinger Bands
    sma20 = c.rolling(20).mean()
    std20 = c.rolling(20).std()
    feat['bb_upper'] = sma20 + 2.0 * std20
    feat['bb_lower'] = sma20 - 2.0 * std20
    feat['bb_pct_b'] = (c - feat['bb_lower']) / (feat['bb_upper'] - feat['bb_lower'] + 1e-9)
    feat['bb_bandwidth'] = (feat['bb_upper'] - feat['bb_lower']) / sma20 * 100.0

    # MACD
    ema12 = c.ewm(span=12, adjust=False).mean()
    ema26 = c.ewm(span=26, adjust=False).mean()
    feat['macd'] = ema12 - ema26
    feat['macd_signal'] = feat['macd'].ewm(span=9, adjust=False).mean()
    feat['macd_hist'] = feat['macd'] - feat['macd_signal']

    # Stochastic
    low14 = l.rolling(14).min()
    high14 = h.rolling(14).max()
    feat['stoch_k'] = 100.0 * (c - low14) / (high14 - low14 + 1e-9)
    feat['stoch_d'] = feat['stoch_k'].rolling(3).mean()

    # Candlestick geometry
    body = (c - o).abs()
    rng = (h - l) + 1e-9
    feat['candle_body_ratio'] = body / rng
    feat['candle_dir'] = np.sign(c - o)
    feat['upper_wick_ratio'] = (h - np.maximum(o, c)) / rng
    feat['lower_wick_ratio'] = (np.minimum(o, c) - l) / rng
    feat['is_pinbar_bull'] = (feat['lower_wick_ratio'] > 0.6) & (feat['candle_body_ratio'] < 0.25)
    feat['is_pinbar_bear'] = (feat['upper_wick_ratio'] > 0.6) & (feat['candle_body_ratio'] < 0.25)

    # Donchian Breakouts
    feat['donchian_high_20'] = h.shift(1).rolling(20).max()
    feat['donchian_low_20'] = l.shift(1).rolling(20).min()
    feat['is_breakout_high_20'] = c > feat['donchian_high_20']
    feat['is_breakout_low_20'] = c < feat['donchian_low_20']

    # Returns
    for r in [1, 3, 5, 10, 15, 30]:
        feat[f'return_{r}'] = (c / c.shift(r) - 1.0) * 10000.0

    return feat

print("Computing M1 features...")
m1_feat = compute_indicators(m1)

# Time features
m1_feat['utc_hour'] = m1['dt'].dt.hour
m1_feat['utc_minute'] = m1['dt'].dt.minute
m1_feat['dow'] = m1['dt'].dt.dayofweek

# Resample M5, M15, H1
print("Building multi-timeframe aggregations...")
m5 = m1.set_index('dt').resample('5min').agg({'open': 'first', 'high': 'max', 'low': 'min', 'close': 'last', 'volume': 'sum'}).dropna().reset_index()
m15 = m1.set_index('dt').resample('15min').agg({'open': 'first', 'high': 'max', 'low': 'min', 'close': 'last', 'volume': 'sum'}).dropna().reset_index()
h1 = m1.set_index('dt').resample('1h').agg({'open': 'first', 'high': 'max', 'low': 'min', 'close': 'last', 'volume': 'sum'}).dropna().reset_index()

m5_feat = compute_indicators(m5)
m15_feat = compute_indicators(m15)
h1_feat = compute_indicators(h1)

# Merge MTF features using merge_asof (strictly completed bars t-1 to avoid lookahead)
print("Aligning multi-timeframe features (Zero lookahead)...")
m5_feat_shift = m5_feat.copy()
m5_feat_shift['dt'] = m5_feat_shift['dt'] + pd.Timedelta(minutes=5)
m5_feat_shift = m5_feat_shift.add_prefix('m5_')
m5_feat_shift.rename(columns={'m5_dt': 'dt'}, inplace=True)

m15_feat_shift = m15_feat.copy()
m15_feat_shift['dt'] = m15_feat_shift['dt'] + pd.Timedelta(minutes=15)
m15_feat_shift = m15_feat_shift.add_prefix('m15_')
m15_feat_shift.rename(columns={'m15_dt': 'dt'}, inplace=True)

h1_feat_shift = h1_feat.copy()
h1_feat_shift['dt'] = h1_feat_shift['dt'] + pd.Timedelta(hours=1)
h1_feat_shift = h1_feat_shift.add_prefix('h1_')
h1_feat_shift.rename(columns={'h1_dt': 'dt'}, inplace=True)

panel = pd.merge_asof(m1_feat.sort_values('dt'), m5_feat_shift.sort_values('dt'), on='dt', direction='backward')
panel = pd.merge_asof(panel, m15_feat_shift.sort_values('dt'), on='dt', direction='backward')
panel = pd.merge_asof(panel, h1_feat_shift.sort_values('dt'), on='dt', direction='backward')

# Label trades
trade_map = {}
dir_map = {}
for idx, r in trades.iterrows():
    b = r['open_m1_bar']
    trade_map[b] = 1
    dir_map[b] = 1 if r['side'] == 'Buy' else 0

panel['is_trade'] = panel['dt'].map(trade_map).fillna(0).astype(int)
panel['trade_dir'] = panel['dt'].map(dir_map)

print(f"Total panel bars: {len(panel)}, Trade bars: {panel['is_trade'].sum()}")

# Drop initial warmup bars (first 250 bars where 200 EMA is NaN)
clean_panel = panel.iloc[250:].copy()

# Feature Analysis on Trades vs Non-Trades
trade_bars = clean_panel[clean_panel['is_trade'] == 1]
non_trade_bars = clean_panel[clean_panel['is_trade'] == 0]

print(f"\nAnalyzing {len(trade_bars)} trade bars vs {len(non_trade_bars)} counterfactual non-trade bars...")

features_to_test = [
    'rsi_14', 'm5_rsi_14', 'm15_rsi_14', 'h1_rsi_14',
    'bb_pct_b', 'm5_bb_pct_b', 'm15_bb_pct_b', 'h1_bb_pct_b',
    'macd_hist', 'm5_macd_hist', 'm15_macd_hist', 'h1_macd_hist',
    'stoch_k', 'stoch_d', 'm5_stoch_k', 'm15_stoch_k',
    'dist_ema_8', 'dist_ema_21', 'dist_ema_50', 'dist_ema_200',
    'm5_dist_ema_21', 'm15_dist_ema_21', 'h1_dist_ema_21',
    'atr_pct_14', 'm5_atr_pct_14', 'h1_atr_pct_14',
    'return_1', 'return_5', 'return_15', 'return_30',
    'candle_body_ratio', 'upper_wick_ratio', 'lower_wick_ratio',
    'utc_hour', 'utc_minute'
]

results = []
for f in features_to_test:
    if f in clean_panel.columns:
        t_mean = trade_bars[f].mean()
        t_std = trade_bars[f].std()
        nt_mean = non_trade_bars[f].mean()
        nt_std = non_trade_bars[f].std()
        # Cohen's d
        pooled_std = np.sqrt(((len(trade_bars)-1)*t_std**2 + (len(non_trade_bars)-1)*nt_std**2) / (len(clean_panel)-2))
        d = (t_mean - nt_mean) / (pooled_std + 1e-9)
        results.append({'feature': f, 'trade_mean': t_mean, 'non_trade_mean': nt_mean, 'cohens_d': d})

res_df = pd.DataFrame(results).sort_values(by='cohens_d', key=abs, ascending=False)
print("\nTop Features Separating Trade vs Non-Trade Bars (by Effect Size |d|):")
print(res_df.head(15).to_string(index=False))

# Direction Analysis: Buy vs Sell Trades
buys = trade_bars[trade_bars['trade_dir'] == 1]
sells = trade_bars[trade_bars['trade_dir'] == 0]
print(f"\nAnalyzing Direction: {len(buys)} Buys vs {len(sells)} Sells...")

dir_results = []
for f in features_to_test:
    if f in clean_panel.columns:
        b_mean = buys[f].mean()
        s_mean = sells[f].mean()
        b_std = buys[f].std()
        s_std = sells[f].std()
        pooled_std = np.sqrt(((len(buys)-1)*b_std**2 + (len(sells)-1)*s_std**2) / (len(trade_bars)-2))
        d = (b_mean - s_mean) / (pooled_std + 1e-9)
        dir_results.append({'feature': f, 'buy_mean': b_mean, 'sell_mean': s_mean, 'cohens_d': d})

dir_df = pd.DataFrame(dir_results).sort_values(by='cohens_d', key=abs, ascending=False)
print("\nTop Features Separating Buy vs Sell (by Effect Size |d|):")
print(dir_df.head(15).to_string(index=False))

# Save analysis outputs
clean_panel[['dt', 'is_trade', 'trade_dir'] + [f for f in features_to_test if f in clean_panel.columns]].to_parquet('data/processed/decision_panel.parquet')
print("\nSaved decision_panel.parquet")
