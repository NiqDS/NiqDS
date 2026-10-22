"""Matched-pair randomisation: the method that works on a short list.

Rerandomisation needs room. It draws assignments and keeps the best, so
its quality depends on how much the draws differ -- and at 80 clients over
five covariates every draw looks much like every other. Below roughly two
hundred clients, the better design is to **pair the clients first and
randomise inside each pair** (Greevy et al. 2004, Imai/King/Nall 2009):

    1. put the clients into pairs that are as alike as possible,
    2. inside each pair, flip a coin for which one gets the treatment.

The randomisation is still real -- every client has a 50% chance, and the
pilot can still be analysed as an experiment -- but the worst-case
imbalance is now bounded by how good the pairs are instead of by luck.
Where rerandomisation hopes a good draw exists, pairing constructs one.

Two further gains on the analysis side, both of which matter for ММБ data:

* The comparison becomes paired. A pair difference cancels whatever the
  two clients have in common, which on a heavy-tailed metric like ЧОД is
  most of the variance. `skill/statistics.py` already carries the paired
  tools (`paired_effect`, `sign_test`).
* A pair is auditable. "This client was matched to that one" is a sentence
  a business owner can check, which a Mahalanobis criterion over a
  standardised design is not.

And the honest costs:

* Pairing on many covariates in a short list runs into the same curse of
  dimensionality as everything else -- the pairs get worse, quietly. The
  covariate budget in `splitter.covariate_budget` applies here too, and
  `Pairing.describe()` reports how good the pairs actually came out.
* If a client drops out of the pilot, the paired analysis loses its
  partner as well. On a short list that is a real cost, not a formality.
* It needs an even split. 90/10 cannot be paired, so a pilot that wants an
  uneven allocation keeps the stratified search.
"""
from __future__ import annotations

import math
import random
from dataclasses import dataclass, field


@dataclass
class Pairing:
    """Clients matched into pairs, plus whoever was left over."""

    pairs: list[tuple[str, str]] = field(default_factory=list)
    #: An odd list leaves one client unpaired; they are assigned at random
    #: and named, because a single unpaired client in a 51-client pilot is
    #: a measurable fraction of it.
    unmatched: list[str] = field(default_factory=list)
    #: Distance between partners, in standardised units, across the pairs.
    mean_distance: float = 0.0
    worst_distance: float = 0.0
    #: Mean distance between two clients picked at random, which is what
    #: the pairs have to be judged against. The raw number cannot be read
    #: on its own: in k standardised dimensions two random clients sit
    #: about sqrt(2k) apart, so 1.5σ is poor matching on two covariates and
    #: good matching on eight.
    baseline_distance: float = 0.0

    @property
    def tightness(self) -> float:
        """Partner distance as a share of a random partner's. Lower is
        better; 1.0 means the pairing found nothing."""
        if self.baseline_distance <= 0:
            return 1.0
        return self.mean_distance / self.baseline_distance

    def describe(self) -> str:
        if not self.pairs:
            return "пары не построены"
        if self.mean_distance <= 0:
            closeness = "партнёры совпадают по всем ковариатам"
        else:
            closeness = (
                f"партнёры в среднем в {1 / self.tightness:.1f} раза ближе случайной "
                f"пары ({self.mean_distance:.2f} σ против {self.baseline_distance:.2f} σ)"
            )
        text = (
            f"{len(self.pairs)} пар, {closeness}, "
            f"худшая пара {self.worst_distance:.2f} σ"
        )
        if self.unmatched:
            text += f"; без пары: {', '.join(self.unmatched)}"
        return text

    def quality_warning(self, threshold: float = 0.6) -> str | None:
        """Pairs too far apart to be worth calling pairs.

        Judged against a random partner, not against an absolute distance,
        because the absolute number grows with the number of covariates
        whatever the matching does. When the best available partner is
        almost as far away as a random one, pairing buys nothing and still
        costs the analysis its independence -- which is what happens when
        the covariates outnumber what the list can support.
        """
        if not self.pairs or self.mean_distance <= 0 or self.tightness <= threshold:
            return None
        return (
            f"качество пар низкое: партнёр в среднем всего в "
            f"{1 / self.tightness:.1f} раза ближе случайного клиента. На таком "
            "наборе ковариат список слишком короток, чтобы находить похожих — "
            "сократите число признаков или отключите разбиение по парам "
            "(SplitConfig.pair_small_lists)."
        )


def _cholesky(matrix: list[list[float]]) -> list[list[float]] | None:
    """Lower-triangular L with L @ L.T == matrix, or None if not positive
    definite.

    Used to turn a Mahalanobis distance into a plain Euclidean one: with
    P = L L', the distance d' P d is |L' d|, so the clients can be
    transformed once and then compared with a straight sum of squares.
    That turns an n^2 k^2 problem into n k^2 + n^2 k, which is what makes
    pairing affordable in the standard library.
    """
    size = len(matrix)
    lower = [[0.0] * size for _ in range(size)]
    for i in range(size):
        for j in range(i + 1):
            total = matrix[i][j] - sum(lower[i][k] * lower[j][k] for k in range(j))
            if i == j:
                if total <= 0:
                    return None
                lower[i][j] = math.sqrt(total)
            else:
                lower[i][j] = total / lower[j][j]
    return lower


def _transform(
    matrix: list[list[float]], precision: list[list[float]] | None
) -> list[list[float]]:
    """One row per client, in the space where Euclidean distance is the
    criterion's distance."""
    n_clients = len(matrix[0]) if matrix else 0
    rows = [[column[i] for column in matrix] for i in range(n_clients)]
    if precision is None:
        return rows
    lower = _cholesky(precision)
    if lower is None:
        return rows
    size = len(lower)
    # y = L' x, so |y_a - y_b|^2 == (x_a - x_b)' P (x_a - x_b)
    return [
        [sum(lower[i][j] * row[i] for i in range(j, size)) for j in range(size)]
        for row in rows
    ]


def _distance_between(row_a: list[float], row_b: list[float]) -> float:
    return math.sqrt(sum((x - y) ** 2 for x, y in zip(row_a, row_b)))


def _improve(
    matched: list[tuple[int, int]], rows: list[list[float]], rounds: int = 4
) -> list[tuple[int, int]]:
    """Swap partners between two pairs while it reduces the squared total.

    The objective is the sum of squared gaps, because the coin flips make
    each pair contribute +-(a - b) to the group difference and those add
    in variance. Four passes over every combination of two pairs is
    (n/2)^2 * 4 distance computations -- at 200 clients, forty thousand,
    which is milliseconds, and the gain is in exactly the pairs greedy
    left worst.
    """
    if len(matched) < 2:
        return matched

    def cost(a: int, b: int) -> float:
        return sum((x - y) ** 2 for x, y in zip(rows[a], rows[b]))

    pairs = list(matched)
    for _ in range(rounds):
        improved = False
        for i in range(len(pairs)):
            for j in range(i + 1, len(pairs)):
                a, b = pairs[i]
                c, d = pairs[j]
                current = cost(a, b) + cost(c, d)
                options = (
                    (cost(a, c) + cost(b, d), (a, c), (b, d)),
                    (cost(a, d) + cost(b, c), (a, d), (b, c)),
                )
                best_cost, first, second = min(options, key=lambda item: item[0])
                if best_cost < current - 1e-12:
                    pairs[i], pairs[j] = first, second
                    improved = True
        if not improved:
            break
    return pairs


def pair_clients(
    inn_list: list[str],
    matrix: list[list[float]],
    precision: list[list[float]] | None = None,
    seed: int = 0,
) -> Pairing:
    """Greedy non-bipartite matching on the criterion's own distance.

    Every pair of clients is scored, the closest available pair is taken,
    and so on -- then a swap pass cleans up after it.

    The swap pass is not optional, and the measurement that forced it is
    worth keeping: plain greedy made the money balance at 200 clients
    *worse* than no pairing at all (0.023 against 0.008 standardised).
    Greedy takes the easy pairs first, so the clients with no close
    partner -- the tail, which on ЧОД is exactly where the money is -- are
    matched last, to whatever is left. Each of those pairs contributes its
    full gap to the group difference, and a handful of them outweighs
    everything the easy pairs saved.

    So pairs are then improved two at a time: for pairs (a,b) and (c,d),
    try (a,c)+(b,d) and (a,d)+(b,c), and keep whichever has the smallest
    sum of **squared** distances. Squared because that is the objective
    that matters -- the coin flips make each pair contribute +-(a-b) to
    the group difference, so the variance of that difference is the sum of
    squared gaps. One badly matched pair costs more than several slightly
    loose ones, and squaring is what says so.

    This is a local-search approximation to optimal non-bipartite matching
    (Greevy's `nbpMatching`, an O(n^3) blossom algorithm). The remaining
    gap to optimal is far smaller than the gap between pairing and not
    pairing.
    """
    if len(inn_list) < 2 or not matrix:
        return Pairing(unmatched=list(inn_list))

    rows = _transform(matrix, precision)
    n = len(inn_list)
    candidates: list[tuple[float, int, int]] = []
    for a in range(n):
        row_a = rows[a]
        for b in range(a + 1, n):
            row_b = rows[b]
            distance = math.sqrt(sum((x - y) ** 2 for x, y in zip(row_a, row_b)))
            candidates.append((distance, a, b))
    candidates.sort()

    taken = [False] * n
    matched: list[tuple[int, int]] = []
    for _distance, a, b in candidates:
        if taken[a] or taken[b]:
            continue
        taken[a] = taken[b] = True
        matched.append((a, b))
        if len(matched) * 2 >= n - 1:
            break

    matched = _improve(matched, rows)
    distances = [_distance_between(rows[a], rows[b]) for a, b in matched]
    pairs = [(inn_list[a], inn_list[b]) for a, b in matched]
    leftover = [inn_list[i] for i in range(n) if not taken[i]]
    # Every pairwise distance was computed anyway, so the mean of them is a
    # free and exact answer to "how far apart is a random partner" -- the
    # only yardstick the pair distances can be read against.
    # The pairing itself is seed-independent and reproducible; only the coin
    # flips inside it depend on the seed.
    return Pairing(
        pairs=pairs,
        unmatched=leftover,
        mean_distance=sum(distances) / len(distances) if distances else 0.0,
        worst_distance=max(distances) if distances else 0.0,
        baseline_distance=sum(d for d, _, _ in candidates) / len(candidates),
    )


def assign_pairs(pairing: Pairing, seed: int) -> tuple[list[str], list[str]]:
    """One coin flip per pair: this is the randomisation.

    The leftover client (an odd list) is assigned to whichever group is
    smaller, with the seed breaking the tie, so the groups stay within one
    client of each other.
    """
    rng = random.Random(seed)
    control: list[str] = []
    target: list[str] = []
    for first, second in pairing.pairs:
        if rng.random() < 0.5:
            target.append(first)
            control.append(second)
        else:
            target.append(second)
            control.append(first)
    for inn in pairing.unmatched:
        if len(target) < len(control) or (len(target) == len(control) and rng.random() < 0.5):
            target.append(inn)
        else:
            control.append(inn)
    return control, target
