"""Authoritative executable Python representation of reconstructed trading policy."""

import json
from reverse_trade.reconstruction.policy_ast import Policy, Action, TimeExit, ThresholdCondition, AndCondition
from reverse_trade.reconstruction.replay import ReplayEngine, Quote

# Reconstructed AST definition for candidate cand_0000
POLICY_SPEC_JSON = """{
    "name": "t0_hour_utc_>_2.9",
    "entry": {
        "type": "threshold",
        "feature": "hour_utc",
        "operator": ">",
        "threshold": 2.9
    },
    "condition": {
        "type": "threshold",
        "feature": "hour_utc",
        "operator": ">",
        "threshold": 2.9
    },
    "side": "open_buy",
    "volume": 0.01,
    "cooldown_seconds": 0.0,
    "exit_rule": null,
    "metadata": {
        "tier": "T0",
        "feature": "hour_utc",
        "operator": ">",
        "threshold": 2.9
    },
    "complexity": 5,
    "state_transitions": {}
}"""

def get_reconstructed_policy() -> Policy:
    return Policy.from_dict(json.loads(POLICY_SPEC_JSON))

if __name__ == '__main__':
    policy = get_reconstructed_policy()
    print(f'Loaded reconstructed policy: {policy.name}')
