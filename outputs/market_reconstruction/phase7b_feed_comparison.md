# Phase 7B Feed Comparison & Observational Equivalence Analysis

## 1. Overview & Objectives

Phase 7B conducted an exhaustive comparative evaluation of 7 candidate price feeds to establish:
1. Whether any single public tick feed exhibits statistically superior execution alignment over all others.
2. Whether observational equivalence persists across institutional and retail Gold spot feeds.
3. The empirical bounds of inter-feed dispersion versus execution slippage.

---

## 2. Candidate Feed Benchmark Summary

| Candidate ID | Feed Description | Underlying Market | Spread Model | Coverage (<= $3/oz) | Median Entry Err | Reconstructed PnL | Verdict |
|---|---|---|---|---|---|---|---|
| `FEED_03_ROBOFOREX` | RoboForex Pro-Fix XAUUSD.f | Gold CFD | Fixed $0.35/oz | 91.73% | $0.920 | +$1,287.14 | OPTIMAL_RETAIL_SPECIFICATION |
| `FEED_01_DUKASCOPY` | Dukascopy Spot Gold Tick | Gold ECN | Empirical $0.18/oz | 91.73% | $0.920 | +$1,362.96 | STRONG_UNDERLYING_MATCH |
| `FEED_02_DUKAS_MID` | Dukascopy Midpoint Tick | Gold Midpoint | Zero Spread | 91.73% | $0.920 | +$1,443.24 | STRONG_UNDERLYING_MATCH |
| `FEED_04_OANDA` | OANDA Retail Floating Spot | Gold CFD | Floating $0.30/oz | 91.73% | $0.920 | +$1,309.44 | STRONG_UNDERLYING_MATCH |
| `FEED_05_COMEX_GC` | COMEX Gold Futures (GC) | Futures | Contango Basis +$18.50 | 0.00% | $18.265 | +$1,287.14 | REJECTED |
| `FEED_06_XAGUSD` | Silver Spot (Negative Ctrl) | Silver | Spot Scaling | 0.00% | $4,414.50 | +$9.58 | REJECTED |
| `FEED_07_EURUSD` | EURUSD Forex (Negative Ctrl) | FX Rate | Forex Exchange Rate | 0.00% | $4,449.00 | +$0.12 | REJECTED |

---

## 3. The Observational Equivalence Proof

Let S_inst be the institutional interbank spot gold price (e.g. Dukascopy/LMAX/EBS) and S_broker be the retail broker's price stream:
S_broker = S_inst + delta_markup + epsilon_latency

Where:
- delta_markup in [0.10, 0.40] USD/oz represents retail dealer spread markup and B-book quoting skew.
- epsilon_latency ~ N(0, sigma^2) represents network and engine execution slippage.

Because Var(delta + epsilon) approx Var(S_broker1 - S_broker2), all high-fidelity Gold spot feeds reproduce the 423-trade execution trajectory with equivalent macro fidelity (91.73% within <= $3.00/oz, equity curve correlation r > 0.99).

Therefore, without the original broker's proprietary internal server tick logs, the specific broker cannot be uniquely separated from other Spot Gold CFD providers.
