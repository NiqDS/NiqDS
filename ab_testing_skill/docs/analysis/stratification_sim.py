"""Does the stratification in the notebook actually stratify?

Reimplements the pipeline from the photographed cells exactly as written,
on a synthetic ММБ-like population, and measures:

  1. how many distinct strata the 12-variable composite key produces
  2. what share of clients ends up in the `rare_strats` bucket, where the
     assignment is plain 50/50 randomisation with no stratification at all
  3. the balance actually achieved, against three alternatives

Run:  python3 -I stratification_sim.py
"""
import numpy as np
import pandas as pd
from scipy import stats as sps
from sklearn.model_selection import train_test_split

RNG = np.random.default_rng(20261022)

CAT_COLS = ["tb_name", "opf", "mon_sdo", "industry", "avg_chod", "avg_chep"]
NUM_COLS = ["age_days", "products_num", "guarantee_successful_deals_num",
            "guarantee_mean_sum", "nkd", "in_transactions"]
N_INTERVALS = {"age_days": 3, "products_num": 3, "guarantee_successful_deals_num": 3,
               "guarantee_mean_sum": 3, "nkd": 3, "in_transactions": 4}


def population(n, money_pre_bucketed):
    """Synthetic ММБ clients. Cardinalities chosen to be conservative:
    12 ТБ, 20 industries -- the real tables have more."""
    tb = RNG.choice([f"ТБ-{i}" for i in range(12)], n, p=np.r_[0.25, 0.15, 0.1, np.full(9, 0.5 / 9)])
    industry = RNG.choice([f"IND{i}" for i in range(20)], n)
    opf = RNG.choice([1.0, 0.0, np.nan], n, p=[0.7, 0.28, 0.02])

    # money: lognormal, ЧОД can go negative (loss-making clients)
    chod = RNG.lognormal(10, 1.8, n) * RNG.choice([1, -1], n, p=[0.93, 0.07])
    chep = chod * RNG.uniform(0.3, 0.9, n) + RNG.normal(0, 5000, n)
    sdo = RNG.lognormal(12, 1.5, n)

    if money_pre_bucketed:
        # charitable reading: these arrive already bucketed into 3 labels
        to_band = lambda v: pd.qcut(v, 3, labels=["low", "mid", "high"]).astype(object)
        chod, chep, sdo = to_band(chod), to_band(chep), to_band(sdo)

    frame = pd.DataFrame({
        "inn": [f"{7000000000 + i}" for i in range(n)],
        "tb_name": tb, "opf": opf, "mon_sdo": sdo, "industry": industry,
        "avg_chod": chod, "avg_chep": chep,
        "age_days": RNG.gamma(2, 900, n),
        "products_num": RNG.poisson(3, n).astype(float),
        "guarantee_successful_deals_num": RNG.poisson(0.6, n).astype(float),
        "guarantee_mean_sum": RNG.lognormal(11, 2, n),
        "nkd": RNG.lognormal(8, 2, n),
        "in_transactions": RNG.poisson(40, n).astype(float),
    })
    # realistic missingness
    for col in ("guarantee_mean_sum", "nkd"):
        frame.loc[RNG.random(n) < 0.25, col] = np.nan
    return frame


def their_pipeline(features):
    """The photographed cells, verbatim in behaviour."""
    data = features.copy()
    for col in NUM_COLS:
        ok = ~data[col].isna()
        quantiles = np.quantile(data[ok][col], np.linspace(0, 1, N_INTERVALS[col] + 1)[1:-1])
        data.loc[ok, col] = np.searchsorted(quantiles, data[ok][col])
        data[col] = data[col].astype("object")
    data = data.fillna("miss_category")

    data["group"] = data.apply(
        lambda x: "|".join([str(x[col]) for col in (CAT_COLS + NUM_COLS)]), axis=1
    )
    counts = data["group"].value_counts(dropna=False)
    rare = list(counts[counts < 2].index)
    data.loc[data["group"].isin(rare), "group"] = "rare_strats"

    control, treatment = train_test_split(
        features, test_size=0.5, random_state=42, stratify=data["group"]
    )
    return control, treatment, data["group"]


# --- balance measurement ---------------------------------------------------

def smd(a, b):
    a, b = np.asarray(a, float), np.asarray(b, float)
    a, b = a[~np.isnan(a)], b[~np.isnan(b)]
    if len(a) < 2 or len(b) < 2:
        return np.nan
    pooled = np.sqrt((a.var(ddof=1) + b.var(ddof=1)) / 2)
    return 0.0 if pooled == 0 else abs(a.mean() - b.mean()) / pooled


def balance(control, treatment, numeric_cols, categorical_cols):
    """Worst standardized imbalance across every covariate."""
    worst_num = max(smd(control[c], treatment[c]) for c in numeric_cols)
    worst_cat = 0.0
    for col in categorical_cols:
        levels = set(control[col].dropna()) | set(treatment[col].dropna())
        for level in levels:
            pc = (control[col] == level).mean()
            pt = (treatment[col] == level).mean()
            pooled = np.sqrt((pc * (1 - pc) + pt * (1 - pt)) / 2)
            if pooled > 0:
                worst_cat = max(worst_cat, abs(pc - pt) / pooled)
    return worst_num, worst_cat


def rerandomise(features, numeric_cols, draws=500):
    """Morgan & Rubin: draw many assignments, keep the most balanced."""
    n = len(features)
    X = features[numeric_cols].to_numpy(float)
    X = np.where(np.isnan(X), np.nanmean(X, axis=0), X)
    X = (X - X.mean(0)) / np.where(X.std(0) == 0, 1, X.std(0))
    best, best_score = None, np.inf
    rng = np.random.default_rng(42)
    for _ in range(draws):
        idx = rng.permutation(n)
        a, b = idx[: n // 2], idx[n // 2:]
        diff = X[a].mean(0) - X[b].mean(0)
        score = float(diff @ diff)          # Mahalanobis on standardised means
        if score < best_score:
            best_score, best = score, (a, b)
    return features.iloc[best[0]], features.iloc[best[1]]


def pairwise_blocks(features, key_col):
    """Rank on the dominant covariate, randomise within consecutive pairs."""
    order = features[key_col].rank(method="first", na_option="bottom").to_numpy()
    ordered = features.iloc[np.argsort(order)]
    rng = np.random.default_rng(42)
    left, right = [], []
    rows = list(range(len(ordered)))
    for i in range(0, len(rows) - 1, 2):
        pair = [rows[i], rows[i + 1]]
        rng.shuffle(pair)
        left.append(pair[0])
        right.append(pair[1])
    if len(rows) % 2:
        left.append(rows[-1])
    return ordered.iloc[left], ordered.iloc[right]


def run(n, money_pre_bucketed):
    features = population(n, money_pre_bucketed)
    control, treatment, groups = their_pipeline(features)

    n_strata = groups.nunique()
    rare_share = (groups == "rare_strats").mean()

    cat_for_balance = ["tb_name", "industry"] + (
        ["mon_sdo", "avg_chod", "avg_chep"] if money_pre_bucketed else []
    )
    num_for_balance = NUM_COLS + ([] if money_pre_bucketed else ["mon_sdo", "avg_chod", "avg_chep"])

    label = "money pre-bucketed" if money_pre_bucketed else "money continuous"
    print(f"\n{'=' * 78}\nN = {n:>6}   ({label})\n{'=' * 78}")
    print(f"  distinct strata (incl. rare_strats) : {n_strata}")
    print(f"  clients in rare_strats              : {rare_share:.1%}  "
          f"<- no stratification applied to these")

    rng = np.random.default_rng(7)
    idx = rng.permutation(n)
    plain_c, plain_t = features.iloc[idx[: n // 2]], features.iloc[idx[n // 2:]]
    rer_c, rer_t = rerandomise(features, num_for_balance)
    blk_c, blk_t = pairwise_blocks(features, "avg_chod" if not money_pre_bucketed else "nkd")

    print(f"\n  {'method':<34} {'worst SMD (num)':>16} {'worst SMD (cat)':>16}")
    for name, (c, t) in [
        ("their stratified split", (control, treatment)),
        ("plain random 50/50", (plain_c, plain_t)),
        ("rerandomisation (500 draws)", (rer_c, rer_t)),
        ("pairwise blocking on the key var", (blk_c, blk_t)),
    ]:
        wn, wc = balance(c, t, num_for_balance, cat_for_balance)
        print(f"  {name:<34} {wn:>16.4f} {wc:>16.4f}")


if __name__ == "__main__":
    for pre_bucketed in (False, True):
        for n in (200, 2000, 20000):
            run(n, pre_bucketed)
