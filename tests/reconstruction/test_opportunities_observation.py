import pandas as pd

from reverse_trade.reconstruction.acquisition import acquisition_plan_from_coverage
from reverse_trade.reconstruction.observation import ObservationScenario
from reverse_trade.reconstruction.opportunities import build_opportunities, label_observed_epochs


def test_opportunities_mark_unknown_without_turning_it_into_negative() -> None:
    coverage = pd.DataFrame({
        "intended_hour_utc": pd.to_datetime(["2026-01-01T00:00:00Z"], utc=True),
        "support_status": ["observed"], "status": ["ok"],
        "first_tick_utc": pd.to_datetime(["2026-01-01T00:00:00Z"], utc=True),
        "last_tick_utc": pd.to_datetime(["2026-01-01T00:59:59Z"], utc=True),
        "largest_interquote_gap_seconds": [5.0],
    })
    times = pd.to_datetime(["2026-01-01T00:00:10Z", "2026-01-01T01:00:10Z"], utc=True)
    opportunities = build_opportunities(times, coverage, lookback=pd.Timedelta(0))
    assert opportunities["support_status"].tolist() == ["observed", "unknown"]
    epochs = pd.DataFrame({"epoch_id": [1], "decision_time_utc": [times[0]]})
    labelled = label_observed_epochs(opportunities, epochs)
    assert labelled["is_observed_epoch"].tolist() == [True, False]
    assert labelled.loc[1, "support_status"] == "unknown"


def test_acquisition_plan_is_only_a_plan_and_observation_is_bounded() -> None:
    coverage = pd.DataFrame({
        "intended_hour_utc": pd.to_datetime(["2026-01-01T00:00:00Z"], utc=True),
        "support_status": ["unknown"], "status": ["invalid"],
    })
    plan = acquisition_plan_from_coverage(coverage, provider_id="public-source")
    assert plan.loc[0, "request_status"] == "planned"
    assert plan.loc[0, "label_independent"]
    assert ObservationScenario("test", market_order_delay=pd.Timedelta(seconds=1)).to_dict()["market_order_delay_seconds"] == 1.0
