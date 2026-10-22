"""Two more checks on the photographed homogeneity code.

A. p-values answer the wrong question: the same imbalance passes or fails
   depending only on how many clients are in the pilot.
B. 18 tests at alpha=0.05 with no correction: how often does a correctly
   randomised split get called non-homogeneous?
C. Rerandomisation done properly (criterion over numeric AND categorical).
"""
import numpy as np
import pandas as pd
from scipy import stats as sps

RNG = np.random.default_rng(11)


# --- A. the same imbalance, different n ------------------------------------
print("=" * 78)
print("A. A FIXED imbalance of 0.10 SMD, tested at different pilot sizes")
print("=" * 78)
print(f"  {'n per group':>12} {'true SMD':>10} {'z-test p':>12} {'KS p':>12} {'verdict at 0.05':>18}")
for n in (50, 100, 250, 1000, 5000, 50000):
    a = RNG.normal(0, 1, n)
    b = RNG.normal(0.10, 1, n)          # exactly 0.10 SMD apart by construction
    z = (a.mean() - b.mean()) / np.sqrt(a.std(ddof=1) ** 2 / n + b.std(ddof=1) ** 2 / n)
    p_z = 2 * sps.norm.cdf(-abs(z))
    p_ks = sps.ks_2samp(a, b).pvalue
    verdict = "homogeneous" if min(p_z, p_ks) > 0.05 else "NOT homogeneous"
    print(f"  {n:>12} {0.10:>10.2f} {p_z:>12.4f} {p_ks:>12.4f} {verdict:>18}")
print("\n  The imbalance is identical in every row. Only n changes.")
print("  A p-value measures evidence against equality, not the size of the gap.")

# the mirror image: a REAL imbalance that passes because the pilot is small
print(f"\n  {'n per group':>12} {'true SMD':>10} {'z-test p':>12} {'verdict':>18}")
for n, true_smd in ((60, 0.35), (60, 0.50), (120, 0.25)):
    a = RNG.normal(0, 1, n)
    b = RNG.normal(true_smd, 1, n)
    z = (a.mean() - b.mean()) / np.sqrt(a.std(ddof=1) ** 2 / n + b.std(ddof=1) ** 2 / n)
    p_z = 2 * sps.norm.cdf(-abs(z))
    print(f"  {n:>12} {true_smd:>10.2f} {p_z:>12.4f} "
          f"{'PASSES as homogeneous' if p_z > 0.05 else 'flagged':>18}")


# --- B. 18 uncorrected tests under a perfect null --------------------------
print("\n" + "=" * 78)
print("B. 1000 correctly randomised splits, 18 tests each, alpha = 0.05")
print("=" * 78)
flagged = 0
n_tests = 18
for _ in range(1000):
    ps = []
    for _ in range(6):                       # 6 numeric covariates, 2 tests each
        a, b = RNG.normal(0, 1, 300), RNG.normal(0, 1, 300)
        z = (a.mean() - b.mean()) / np.sqrt(a.std(ddof=1) ** 2 / 300 + b.std(ddof=1) ** 2 / 300)
        ps.append(2 * sps.norm.cdf(-abs(z)))
        ps.append(sps.ks_2samp(a, b).pvalue)
    for _ in range(6):                       # 6 categorical covariates
        table = RNG.multinomial(300, [0.4, 0.35, 0.25], size=2)
        ps.append(sps.chi2_contingency(table)[1])
    if min(ps) < 0.05:
        flagged += 1
print(f"  splits where at least one of the {n_tests} tests fired : {flagged / 10:.1f}%")
print(f"  expected by chance alone (1 - 0.95^{n_tests})            : "
      f"{(1 - 0.95 ** n_tests) * 100:.1f}%")
print("\n  Every one of these splits was correctly randomised. Re-drawing the seed")
print("  until all 18 tests pass selects for luck, not for balance.")


# --- C. rerandomisation with a criterion over ALL covariates ---------------
print("\n" + "=" * 78)
print("C. Rerandomisation: criterion must cover categorical covariates too")
print("=" * 78)


def make_population(n):
    frame = pd.DataFrame({
        "tb": RNG.choice([f"ТБ{i}" for i in range(12)], n),
        "ind": RNG.choice([f"I{i}" for i in range(20)], n),
        "chod": RNG.lognormal(10, 1.8, n) * RNG.choice([1, -1], n, p=[0.93, 0.07]),
        "sdo": RNG.lognormal(12, 1.5, n),
        "age": RNG.gamma(2, 900, n),
        "prod": RNG.poisson(3, n).astype(float),
    })
    return frame


def design_matrix(frame, numeric, categorical):
    """Numeric standardised + one-hot categorical: what balance is judged on."""
    blocks = [frame[numeric].to_numpy(float)]
    for col in categorical:
        blocks.append(pd.get_dummies(frame[col]).to_numpy(float))
    X = np.hstack(blocks)
    sd = X.std(0)
    return (X - X.mean(0)) / np.where(sd == 0, 1, sd)


def worst_smd(X, a, b):
    pooled = np.sqrt((X[a].var(0, ddof=1) + X[b].var(0, ddof=1)) / 2)
    diff = np.abs(X[a].mean(0) - X[b].mean(0))
    return float(np.max(np.where(pooled > 0, diff / np.where(pooled > 0, pooled, 1), 0.0)))


for n in (200, 2000):
    frame = make_population(n)
    X = design_matrix(frame, ["chod", "sdo", "age", "prod"], ["tb", "ind"])
    rng = np.random.default_rng(42)

    idx = rng.permutation(n)
    plain = worst_smd(X, idx[: n // 2], idx[n // 2:])

    results = {}
    for draws in (100, 1000, 10000):
        best, best_score = None, np.inf
        r = np.random.default_rng(42)
        for _ in range(draws):
            p = r.permutation(n)
            a, b = p[: n // 2], p[n // 2:]
            d = X[a].mean(0) - X[b].mean(0)
            score = float(d @ d)
            if score < best_score:
                best_score, best = score, (a, b)
        results[draws] = worst_smd(X, *best)

    print(f"\n  N = {n}")
    print(f"    plain random 50/50                 worst SMD = {plain:.4f}")
    for draws, value in results.items():
        print(f"    rerandomisation, {draws:>5} draws      worst SMD = {value:.4f}"
              f"   ({'within' if value <= 0.1 else 'outside'} the 0.1 threshold)")
