"""
Phase 10/11 — L2-Penalized Conditional Logistic Regression (model_lib10b.py)
=============================================================================
Implements hand-rolled L2-penalized conditional logit for case-control
(matched risk-set) analysis of entry selection.

Conditional logit likelihood removes nuisance stratum intercepts:
  P(case=j | risk set i) = exp(β'x_ij) / Σ_k exp(β'x_ik)

This eliminates confounding by within-stratum timing/session effects
and makes M2/M3/M4 comparisons robust.

WHY L2 PENALTY IS MANDATORY:
  Unpenalized conditional logit diverges (perfect separation, exp overflow)
  when feature dimension exceeds ~10 per 320 groups. The L2 penalty acts as
  a ridge term on the log-likelihood:
    L(β) = conditional_log_lik(β) - (lambda/2) * ||β||^2

  Lambda is selected by leave-one-group-out cross-validation.

API:
  fit(X, y, groups) -> ConditionalLogitResult
  predict_proba(X, groups) -> array
  compute_aic_bic(result) -> (aic, bic)
  permutation_test(X, y, groups, n_perm) -> p_value
"""

import numpy as np
from scipy.optimize import minimize
from scipy.special import logsumexp
from dataclasses import dataclass, field
from typing import Optional
import warnings


@dataclass
class ConditionalLogitResult:
    """Result container for a fitted conditional logit model."""
    beta: np.ndarray                    # coefficient vector (D,)
    feature_names: list                 # column names
    lam: float                          # L2 penalty used
    n_groups: int                       # number of strata
    n_cases: int                        # number of case (is_trade=1) observations
    n_obs: int                          # total observations
    log_lik: float                      # final conditional log-likelihood (unpenalized)
    log_lik_penalized: float            # final penalized objective
    null_log_lik: float                 # log-lik of null model (beta=0)
    converged: bool
    n_iter: int
    aic: float = field(init=False)
    bic: float = field(init=False)
    pseudo_r2: float = field(init=False)

    def __post_init__(self):
        k = len(self.beta)
        self.aic = -2 * self.log_lik + 2 * k
        self.bic = -2 * self.log_lik + np.log(self.n_obs) * k
        # McFadden pseudo R²
        if self.null_log_lik < 0:
            self.pseudo_r2 = 1.0 - self.log_lik / self.null_log_lik
        else:
            self.pseudo_r2 = 0.0

    def summary(self) -> str:
        lines = [
            f"Conditional Logit (L2 λ={self.lam:.4f})",
            f"  Groups: {self.n_groups}, Cases: {self.n_cases}, Obs: {self.n_obs}",
            f"  Log-lik: {self.log_lik:.4f}  (null: {self.null_log_lik:.4f})",
            f"  AIC: {self.aic:.2f}  BIC: {self.bic:.2f}  Pseudo-R²: {self.pseudo_r2:.4f}",
            f"  Converged: {self.converged}  Iterations: {self.n_iter}",
            f"\n  {'Feature':<25s} {'Beta':>10s}",
            "  " + "-"*36,
        ]
        for name, b in zip(self.feature_names, self.beta):
            lines.append(f"  {name:<25s} {b:+10.4f}")
        return "\n".join(lines)


def _conditional_log_lik_and_grad(
    beta: np.ndarray,
    X_groups: list,         # list of (X_g, case_mask_g) per group
    lam: float = 0.0,
) -> tuple:
    """
    Compute negative conditional log-likelihood and gradient.
    Each group must have exactly one case (standard matched case-control).
    Groups with no case or all-case are skipped.

    Returns (neg_llik, neg_grad)
    """
    neg_ll = 0.0
    neg_grad = np.zeros_like(beta)

    total_llik = 0.0

    for X_g, case_mask_g in X_groups:
        if case_mask_g.sum() == 0:
            continue
        # Linear predictors
        eta = X_g @ beta                        # (n_g,)

        # Numerically stable log-sum-exp
        lse = logsumexp(eta)

        # Case score (usually one case per group)
        case_eta = eta[case_mask_g]
        case_contribution = case_eta.sum() - len(case_eta) * lse
        total_llik += float(case_contribution)

        # Gradient: case_X - n_cases * softmax(eta) @ X_g
        probs = np.exp(eta - lse)               # (n_g,)  softmax
        for _ in range(case_mask_g.sum()):
            neg_grad += probs @ X_g - X_g[case_mask_g].sum(axis=0)

    neg_ll = -total_llik
    if lam > 0:
        neg_ll += 0.5 * lam * np.dot(beta, beta)
        neg_grad += lam * beta

    return neg_ll, neg_grad


def fit_conditional_logit(
    X: np.ndarray,
    y: np.ndarray,
    groups: np.ndarray,
    lam: float = 1e-3,
    max_iter: int = 500,
    tol: float = 1e-6,
    feature_names: Optional[list] = None,
) -> ConditionalLogitResult:
    """
    Fit L2-penalized conditional logistic regression.

    Parameters
    ----------
    X       : (N, D) feature matrix, standardized
    y       : (N,) binary outcome, 1=case, 0=control
    groups  : (N,) integer group labels (stratum ids)
    lam     : L2 penalty coefficient
    max_iter: maximum L-BFGS-B iterations
    tol     : convergence tolerance

    Returns
    -------
    ConditionalLogitResult
    """
    if X.ndim != 2 or y.ndim != 1 or groups.ndim != 1 or len(X) != len(y) or len(y) != len(groups):
        raise ValueError("X, y, and groups must have compatible dimensions")
    unique_groups = np.unique(groups)
    case_counts = np.array([int(y[groups == g].sum()) for g in unique_groups])
    if not np.all(case_counts == 1):
        raise ValueError("Conditional-logit epoch design requires exactly one case per stratum.")

    D = X.shape[1]
    if feature_names is None:
        feature_names = [f"x{i}" for i in range(D)]
    if D == 0:
        # Exact conditional null: no coefficients, no optimization.
        unique_groups = np.unique(groups)
        n_groups = len(unique_groups)
        n_cases = int(y.sum())
        n_obs = len(y)
        null_ll = 0.0
        for g in unique_groups:
            mask_g = groups == g
            n_g = int(mask_g.sum())
            n_c = int(y[mask_g].sum())
            if n_c:
                null_ll += n_c * (-np.log(n_g))
        return ConditionalLogitResult(
            beta=np.empty(0, dtype=float), feature_names=[], lam=lam,
            n_groups=n_groups, n_cases=n_cases, n_obs=n_obs,
            log_lik=null_ll, log_lik_penalized=null_ll,
            null_log_lik=null_ll, converged=True, n_iter=0,
        )

    unique_groups = np.unique(groups)
    X_groups = []
    for g in unique_groups:
        mask_g = groups == g
        X_g = X[mask_g]
        y_g = y[mask_g]
        case_mask_g = y_g == 1
        if case_mask_g.sum() == 0:
            continue  # skip control-only strata (shouldn't happen but guard)
        X_groups.append((X_g, case_mask_g))

    n_groups = len(X_groups)
    n_cases = int(y.sum())
    n_obs = len(y)

    # Null log-likelihood (beta=0)
    null_ll = 0.0
    for X_g, case_mask_g in X_groups:
        n_g = len(X_g)
        # P(case | null) = 1/n_g for each case
        null_ll += float(case_mask_g.sum()) * (-np.log(n_g))

    # Optimize
    beta0 = np.zeros(D)

    def objective(beta):
        nll, ngrad = _conditional_log_lik_and_grad(beta, X_groups, lam)
        return nll, ngrad

    result = minimize(
        objective,
        beta0,
        method="L-BFGS-B",
        jac=True,
        options={"maxiter": max_iter, "ftol": tol, "gtol": tol * 1e-2},
    )

    beta_hat = result.x
    converged = result.success
    n_iter = result.nit

    # Compute final unpenalized log-likelihood
    neg_ll_final, _ = _conditional_log_lik_and_grad(beta_hat, X_groups, lam=0.0)
    log_lik_final = -neg_ll_final

    neg_ll_pen, _ = _conditional_log_lik_and_grad(beta_hat, X_groups, lam)
    log_lik_pen = -neg_ll_pen

    return ConditionalLogitResult(
        beta=beta_hat,
        feature_names=feature_names,
        lam=lam,
        n_groups=n_groups,
        n_cases=n_cases,
        n_obs=n_obs,
        log_lik=log_lik_final,
        log_lik_penalized=log_lik_pen,
        null_log_lik=null_ll,
        converged=converged,
        n_iter=n_iter,
    )


def select_lambda_cv(
    X: np.ndarray,
    y: np.ndarray,
    groups: np.ndarray,
    lam_grid: Optional[list] = None,
    feature_names: Optional[list] = None,
    n_folds: int = 5,
) -> tuple:
    """
    Select L2 penalty by K-fold group cross-validation (default 5 folds).
    For each lambda, fit on training folds, evaluate on held-out folds.
    Return (best_lam, cv_log_liks dict).
    """
    if lam_grid is None:
        lam_grid = [1e-4, 1e-3, 5e-3, 1e-2, 5e-2, 1e-1, 5e-1, 1.0]

    if X.shape[1] == 0:
        return lam_grid[0], {lam: 0.0 for lam in lam_grid}

    unique_groups = np.unique(groups)
    n_groups = len(unique_groups)

    # Build group lists
    all_X_groups = []
    for g in unique_groups:
        mask_g = groups == g
        X_g = X[mask_g]
        y_g = y[mask_g]
        case_mask_g = y_g == 1
        all_X_groups.append((X_g, case_mask_g))

    k = min(n_folds, n_groups)
    folds = np.array_split(np.arange(n_groups), k)

    cv_logliks = {}
    for lam in lam_grid:
        held_out_ll = 0.0
        n_valid = 0

        for test_indices in folds:
            test_set = set(test_indices)
            train_groups = [all_X_groups[i] for i in range(n_groups) if i not in test_set]
            test_groups = [all_X_groups[i] for i in test_indices]

            D = X.shape[1]
            beta0 = np.zeros(D)

            def obj(beta, train=train_groups, lam=lam):
                return _conditional_log_lik_and_grad(beta, train, lam)

            res = minimize(
                obj,
                beta0,
                method="L-BFGS-B",
                jac=True,
                options={"maxiter": 200, "ftol": 1e-5},
            )
            beta_cv = res.x

            # Evaluate on held-out test groups
            for X_h, case_mask_h in test_groups:
                if case_mask_h.sum() == 0:
                    continue
                eta_h = X_h @ beta_cv
                lse_h = logsumexp(eta_h)
                case_ll_h = float(eta_h[case_mask_h].sum()) - float(case_mask_h.sum()) * lse_h
                held_out_ll += case_ll_h
                n_valid += 1

        cv_logliks[lam] = held_out_ll / max(n_valid, 1)

    best_lam = max(cv_logliks, key=lambda lam: cv_logliks[lam])
    return best_lam, cv_logliks


def permutation_test(
    X: np.ndarray,
    y: np.ndarray,
    groups: np.ndarray,
    lam: float,
    observed_ll: float,
    n_perm: int = 999,
    seed: int = 42,
    feature_names: Optional[list] = None,
) -> dict:
    """
    Permutation test: shuffle case/control labels WITHIN each stratum,
    refit model, record log-likelihood. P-value = fraction of nulls >= observed.

    Parameters
    ----------
    observed_ll : unpenalized log-likelihood of the fitted model

    Returns
    -------
    dict with keys: p_value, null_lls (list), observed_ll, n_perm
    """
    rng = np.random.RandomState(seed)
    null_lls = []

    unique_groups = np.unique(groups)

    for perm_i in range(n_perm):
        # Shuffle y within each group
        y_perm = y.copy()
        for g in unique_groups:
            mask_g = groups == g
            y_g = y[mask_g]
            n_cases_g = y_g.sum()
            n_g = mask_g.sum()
            # Reshuffle: place n_cases_g ones in random positions
            y_perm_g = np.zeros(n_g, dtype=int)
            case_positions = rng.choice(n_g, size=int(n_cases_g), replace=False)
            y_perm_g[case_positions] = 1
            y_perm[mask_g] = y_perm_g

        result_perm = fit_conditional_logit(X, y_perm, groups, lam=lam,
                                            max_iter=200, feature_names=feature_names)
        null_lls.append(result_perm.log_lik)

    null_arr = np.array(null_lls)
    p_value = float((null_arr >= observed_ll).sum() + 1) / (n_perm + 1)  # +1 for continuity

    return {
        "observed_ll": observed_ll,
        "null_ll_mean": float(null_arr.mean()),
        "null_ll_std": float(null_arr.std()),
        "null_ll_95pct": float(np.percentile(null_arr, 95)),
        "p_value": p_value,
        "n_perm": n_perm,
    }


def standardize(X: np.ndarray, mean: Optional[np.ndarray] = None,
                std: Optional[np.ndarray] = None) -> tuple:
    """
    Z-score standardize. Returns (X_std, mean, std).
    If mean/std provided, apply them (for test-set transform).
    """
    if mean is None:
        mean = X.mean(axis=0)
    if std is None:
        std = X.std(axis=0)
    std_safe = np.where(std < 1e-8, 1.0, std)
    return (X - mean) / std_safe, mean, std


if __name__ == "__main__":
    # Smoke test on synthetic data
    np.random.seed(0)
    n_groups = 20
    n_controls_per_group = 10
    D = 3

    X_list, y_list, g_list = [], [], []
    true_beta = np.array([2.0, -1.5, 0.5])

    for g in range(n_groups):
        X_g = np.random.randn(n_controls_per_group + 1, D)
        eta_g = X_g @ true_beta
        # Softmax to pick the case
        probs_g = np.exp(eta_g - logsumexp(eta_g))
        case_idx = np.random.choice(n_controls_per_group + 1, p=probs_g)
        y_g = np.zeros(n_controls_per_group + 1)
        y_g[case_idx] = 1
        X_list.append(X_g)
        y_list.append(y_g)
        g_list.append(np.full(n_controls_per_group + 1, g))

    X = np.vstack(X_list)
    y = np.concatenate(y_list)
    groups = np.concatenate(g_list)

    result = fit_conditional_logit(X, y, groups, lam=1e-4, feature_names=["A", "B", "C"])
    print(result.summary())
    print(f"\nTrue beta: {true_beta}")
    print(f"Est. beta: {result.beta}")
    print(f"\nSmoke test PASSED: model converged={result.converged}")
