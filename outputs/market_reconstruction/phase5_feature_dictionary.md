# Phase 5 feature dictionary

All market fields are computed from a completed M1 observation: they are shifted one bar before the candidate minute. Higher horizon names denote rolling completed-M1 proxies, not broker-native M5/H1/D1 feeds. The timezone is the prior project UTC+3 proxy convention, not independently verified broker-server time. No field uses current-trade outcome, exit, MFE/MAE, or future bar data.

| feature | tag | family | as_of |
| --- | --- | --- | --- |
| m1_body | MARKET | MARKET_GEOMETRY | candidate minute start; derived from bars ending no later than the prior M1 observation |
| m1_range | MARKET | MARKET_GEOMETRY | candidate minute start; derived from bars ending no later than the prior M1 observation |
| m1_body_to_range | MARKET | MARKET_GEOMETRY | candidate minute start; derived from bars ending no later than the prior M1 observation |
| m1_upper_wick_ratio | MARKET | MARKET_GEOMETRY | candidate minute start; derived from bars ending no later than the prior M1 observation |
| m1_lower_wick_ratio | MARKET | MARKET_GEOMETRY | candidate minute start; derived from bars ending no later than the prior M1 observation |
| gap_proxy | MARKET | MARKET_GEOMETRY | candidate minute start; derived from bars ending no later than the prior M1 observation |
| dist_recent_high | MARKET | MARKET_GEOMETRY | candidate minute start; derived from bars ending no later than the prior M1 observation |
| dist_recent_low | MARKET | MARKET_GEOMETRY | candidate minute start; derived from bars ending no later than the prior M1 observation |
| breakout_distance | MARKET | MARKET_GEOMETRY | candidate minute start; derived from bars ending no later than the prior M1 observation |
| round_price_distance | MARKET | MARKET_GEOMETRY | candidate minute start; derived from bars ending no later than the prior M1 observation |
| m1_return_1 | MARKET | MOMENTUM | candidate minute start; derived from bars ending no later than the prior M1 observation |
| return_3m | MARKET | MOMENTUM | candidate minute start; derived from bars ending no later than the prior M1 observation |
| return_5m | MARKET | MOMENTUM | candidate minute start; derived from bars ending no later than the prior M1 observation |
| return_10m | MARKET | MOMENTUM | candidate minute start; derived from bars ending no later than the prior M1 observation |
| return_15m | MARKET | MOMENTUM | candidate minute start; derived from bars ending no later than the prior M1 observation |
| return_30m | MARKET | MOMENTUM | candidate minute start; derived from bars ending no later than the prior M1 observation |
| return_60m | MARKET | MOMENTUM | candidate minute start; derived from bars ending no later than the prior M1 observation |
| return_240m | MARKET | MOMENTUM | candidate minute start; derived from bars ending no later than the prior M1 observation |
| return_1440m | MARKET | MOMENTUM | candidate minute start; derived from bars ending no later than the prior M1 observation |
| rsi_14 | MARKET | MOMENTUM | candidate minute start; derived from bars ending no later than the prior M1 observation |
| stochastic_14 | MARKET | MOMENTUM | candidate minute start; derived from bars ending no later than the prior M1 observation |
| macd | MARKET | MOMENTUM | candidate minute start; derived from bars ending no later than the prior M1 observation |
| atr_14 | MARKET | VOLATILITY | candidate minute start; derived from bars ending no later than the prior M1 observation |
| volatility_15 | MARKET | VOLATILITY | candidate minute start; derived from bars ending no later than the prior M1 observation |
| volatility_60 | MARKET | VOLATILITY | candidate minute start; derived from bars ending no later than the prior M1 observation |
| range_expansion | MARKET | VOLATILITY | candidate minute start; derived from bars ending no later than the prior M1 observation |
| normalized_range | MARKET | VOLATILITY | candidate minute start; derived from bars ending no later than the prior M1 observation |
| ema20_distance | MARKET | TREND_LOCATION | candidate minute start; derived from bars ending no later than the prior M1 observation |
| ema50_distance | MARKET | TREND_LOCATION | candidate minute start; derived from bars ending no later than the prior M1 observation |
| sma20_distance | MARKET | TREND_LOCATION | candidate minute start; derived from bars ending no later than the prior M1 observation |
| ema_order_12_26 | MARKET | TREND_LOCATION | candidate minute start; derived from bars ending no later than the prior M1 observation |
| ema20_slope | MARKET | TREND_LOCATION | candidate minute start; derived from bars ending no later than the prior M1 observation |
| bollinger_location | MARKET | TREND_LOCATION | candidate minute start; derived from bars ending no later than the prior M1 observation |
| donchian_location | MARKET | TREND_LOCATION | candidate minute start; derived from bars ending no later than the prior M1 observation |
| clock_hour_sin | CLOCK | CLOCK | candidate minute start; derived from bars ending no later than the prior M1 observation |
| clock_hour_cos | CLOCK | CLOCK | candidate minute start; derived from bars ending no later than the prior M1 observation |
| clock_minute_sin | CLOCK | CLOCK | candidate minute start; derived from bars ending no later than the prior M1 observation |
| clock_minute_cos | CLOCK | CLOCK | candidate minute start; derived from bars ending no later than the prior M1 observation |
| m5_phase | CLOCK | CLOCK | candidate minute start; derived from bars ending no later than the prior M1 observation |
| m15_phase | CLOCK | CLOCK | candidate minute start; derived from bars ending no later than the prior M1 observation |
| m30_phase | CLOCK | CLOCK | candidate minute start; derived from bars ending no later than the prior M1 observation |
| h1_phase | CLOCK | CLOCK | candidate minute start; derived from bars ending no later than the prior M1 observation |
| m5_boundary | CLOCK | CLOCK | candidate minute start; derived from bars ending no later than the prior M1 observation |
| m15_boundary | CLOCK | CLOCK | candidate minute start; derived from bars ending no later than the prior M1 observation |
| m30_boundary | CLOCK | CLOCK | candidate minute start; derived from bars ending no later than the prior M1 observation |
| h1_boundary | CLOCK | CLOCK | candidate minute start; derived from bars ending no later than the prior M1 observation |
| session_code | CLOCK | CLOCK | candidate minute start; derived from bars ending no later than the prior M1 observation |
| session_age_minutes | CLOCK | CLOCK | candidate minute start; derived from bars ending no later than the prior M1 observation |
| eligible_observed_capacity | ACCOUNT_STATE | TRADE_HISTORY_STATE | candidate minute start; prior observed entries/exits only (Phase 3 availability convention) |
| active_positions_before_candidate | ACCOUNT_STATE | TRADE_HISTORY_STATE | candidate minute start; prior observed entries/exits only (Phase 3 availability convention) |
| seconds_since_last_exit | ACCOUNT_STATE | TRADE_HISTORY_STATE | candidate minute start; prior observed entries/exits only (Phase 3 availability convention) |
| seconds_since_last_entry | ACCOUNT_STATE | TRADE_HISTORY_STATE | candidate minute start; prior observed entries/exits only (Phase 3 availability convention) |
| prior_win_code | ACCOUNT_STATE | TRADE_HISTORY_STATE | candidate minute start; prior observed entries/exits only (Phase 3 availability convention) |
| prior_direction_code | ACCOUNT_STATE | TRADE_HISTORY_STATE | candidate minute start; prior observed entries/exits only (Phase 3 availability convention) |
| prior_large_code | ACCOUNT_STATE | TRADE_HISTORY_STATE | candidate minute start; prior observed entries/exits only (Phase 3 availability convention) |
| trades_today_before | ACCOUNT_STATE | TRADE_HISTORY_STATE | candidate minute start; prior observed entries/exits only (Phase 3 availability convention) |
| trades_prev_hour | ACCOUNT_STATE | TRADE_HISTORY_STATE | candidate minute start; prior observed entries/exits only (Phase 3 availability convention) |
| trades_session_before | ACCOUNT_STATE | TRADE_HISTORY_STATE | candidate minute start; prior observed entries/exits only (Phase 3 availability convention) |
| win_close_arrival_prev_hour | ACCOUNT_STATE | TRADE_HISTORY_STATE | candidate minute start; prior observed entries/exits only (Phase 3 availability convention) |
| loss_close_arrival_prev_hour | ACCOUNT_STATE | TRADE_HISTORY_STATE | candidate minute start; prior observed entries/exits only (Phase 3 availability convention) |
| seconds_since_last_buy_entry | ACCOUNT_STATE | TRADE_HISTORY_STATE | candidate minute start; prior observed entries/exits only (Phase 3 availability convention) |
| seconds_since_last_sell_entry | ACCOUNT_STATE | TRADE_HISTORY_STATE | candidate minute start; prior observed entries/exits only (Phase 3 availability convention) |
| recent_completed_events_30 | ACCOUNT_STATE | TRADE_HISTORY_STATE | candidate minute start; prior observed entries/exits only (Phase 3 availability convention) |
| recent_m30_boundaries_120 | ACCOUNT_STATE | TRADE_HISTORY_STATE | candidate minute start; prior observed entries/exits only (Phase 3 availability convention) |
