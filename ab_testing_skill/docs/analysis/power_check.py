"""Rejection RATE over many replications -- the honest version of experiment A."""
import numpy as np
from scipy import stats as sps

RNG = np.random.default_rng(3)
REPS = 2000

print("A fixed imbalance of 0.10 SMD. How often is it flagged, by pilot size?")
print(f"{'n per group':>12} {'z-test flags':>14} {'KS flags':>12} {'either flags':>14}")
for n in (50, 100, 250, 500, 1000, 5000, 50000):
    z_hits = ks_hits = either = 0
    reps = REPS if n <= 5000 else 300
    for _ in range(reps):
        a = RNG.normal(0, 1, n)
        b = RNG.normal(0.10, 1, n)
        z = (a.mean() - b.mean()) / np.sqrt(a.std(ddof=1)**2/n + b.std(ddof=1)**2/n)
        pz = 2 * sps.norm.cdf(-abs(z))
        pk = sps.ks_2samp(a, b).pvalue
        z_hits += pz < 0.05
        ks_hits += pk < 0.05
        either += min(pz, pk) < 0.05
    print(f"{n:>12} {z_hits/reps:>13.1%} {ks_hits/reps:>12.1%} {either/reps:>14.1%}")

print("\nSame question the other way: what imbalance goes UNDETECTED at n=100?")
print(f"{'true SMD':>10} {'z-test flags':>14} {'passes as homogeneous':>24}")
for smd in (0.1, 0.2, 0.3, 0.4, 0.5, 0.8):
    hits = 0
    for _ in range(REPS):
        a, b = RNG.normal(0, 1, 100), RNG.normal(smd, 1, 100)
        z = (a.mean() - b.mean()) / np.sqrt(a.std(ddof=1)**2/100 + b.std(ddof=1)**2/100)
        hits += 2 * sps.norm.cdf(-abs(z)) < 0.05
    print(f"{smd:>10.1f} {hits/REPS:>13.1%} {1-hits/REPS:>23.1%}")
