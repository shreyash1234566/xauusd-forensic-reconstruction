# Phase 5 observable information boundary

## Inverse problem

For observed executions D={(t_i,a_i,p_i,v_i,t_i^out,p_i^out)} and the limited pre-decision proxy X_t=(X_t^market,X_t^clock,X_t^state), the compatible class is H_D={h : h(X_ti)=a_i for every observed i}. A finite dataset does not uniquely identify the original policy without additional assumptions. Computable programs are countable, but infinitely many distinct computable policies can agree with a finite observation set and differ elsewhere; therefore training fit cannot establish strategy identity.

## Intrabar temporal aggregation / partial observation

M1 OHLC does not retain intrabar ordering, exact seconds, Bid/Ask, spread, tick sequence, pending orders or broker execution state. Multiple second-level paths can map to the same M1 bar. Exact second-level and spread-gated triggers therefore cannot be uniquely recovered from M1 OHLC alone. This is an aggregation/partial-observation limitation, not a Shannon-Nyquist claim.

## Boundary

Observable space contains completed external M1-derived rolling M5/M15/M30/H1/D1 proxies, clock features, and prior ledger state. It excludes broker-native ticks, Bid/Ask, spread, orders, rejected/cancelled orders, modifications, server timing and hidden EA state. Hidden microstructure is unresolved information outside the dataset; it is not asserted to be the cause. SINDy is not applicable to this partial decision-policy reconstruction, and IRL is not identifiable without observed non-actions and hidden transitions.
