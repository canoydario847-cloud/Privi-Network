# Copyright (c) 2026 Privi World Co. All rights reserved.
# Privi Quantum - https://priviflow.us - dariocanoy@priviflow.us
"""CVaR-QAOA: the Quantum Approximate Optimization Algorithm for factory decisions.

Pipeline
  1. A business problem (balance two lines, pick lots to inspect, split conflicting
     jobs) becomes a QUBO: minimize x^T Q x + c over binary x.
  2. The QUBO becomes an Ising Hamiltonian (x = (1 - z) / 2).
  3. QAOA (Farhi, Goldstone, Gutmann 2014) alternates a cost layer exp(-i g C) and a
     mixer layer exp(-i b sum X) p times, starting from |+>^n.
  4. Angles are trained on the CVaR objective (Barkoutsos et al., Quantum 2020): the
     mean of the best alpha fraction of outcomes, which tracks the best answer a
     sampled quantum computer returns better than the plain expectation.
  5. Deeper circuits start from the INTERP schedule (Zhou et al., PRX 2020), which
     interpolates the trained p-layer angles to p+1 layers.
  6. The trained circuit is exported as OpenQASM 2.0 to run on real quantum hardware
     (IBM Quantum, Amazon Braket, Azure Quantum), and the exact optimum is computed
     classically so every answer comes with a provable quality score.

Runs on an exact statevector simulator up to MAX_QUBITS. Honest note: at these sizes
classical solvers are as good or better; this is a production-ready path to quantum
hardware, not a claim of quantum advantage today.
"""
from __future__ import annotations

import math
import time
from dataclasses import dataclass

import numpy as np
from scipy.optimize import minimize

MAX_QUBITS = 16
MAX_LAYERS = 4
MAX_ABS = 1e9


class ProblemError(ValueError):
    pass


# ----------------------------------------------------------------------------- QUBO

@dataclass
class Qubo:
    Q: np.ndarray            # n x n, cost = x^T Q x + offset
    offset: float = 0.0
    names: list[str] | None = None

    def __post_init__(self):
        self.Q = np.asarray(self.Q, dtype=float)
        n = self.Q.shape[0] if self.Q.ndim == 2 else 0
        if self.Q.ndim != 2 or self.Q.shape != (n, n) or n == 0:
            raise ProblemError("Q must be a non-empty square matrix")
        if n > MAX_QUBITS:
            raise ProblemError(f"{n} variables; this service simulates up to {MAX_QUBITS} qubits")
        if not np.all(np.isfinite(self.Q)) or np.max(np.abs(self.Q)) > MAX_ABS:
            raise ProblemError("Q entries must be finite and below 1e9 in magnitude")
        self.names = self.names or [f"x{i}" for i in range(n)]
        if len(self.names) != n:
            raise ProblemError("names must match the number of variables")

    @property
    def n(self) -> int:
        return self.Q.shape[0]

    def bits(self) -> np.ndarray:
        """Row k = binary assignment of basis state k (bit i = variable i)."""
        k = np.arange(2 ** self.n)[:, None]
        return ((k >> np.arange(self.n)) & 1).astype(float)

    def all_costs(self) -> np.ndarray:
        X = self.bits()
        return np.einsum("ki,ij,kj->k", X, self.Q, X) + self.offset

    def cost(self, x) -> float:
        x = np.asarray(x, dtype=float)
        return float(x @ self.Q @ x + self.offset)

    def ising(self) -> tuple[np.ndarray, dict[tuple[int, int], float], float]:
        """h, J, constant with cost = sum h_i z_i + sum J_ij z_i z_j + const, z = 1 - 2x."""
        S = (self.Q + self.Q.T) / 2
        n = self.n
        h = np.zeros(n)
        J: dict[tuple[int, int], float] = {}
        const = self.offset
        for i in range(n):
            h[i] -= S[i, i] / 2
            const += S[i, i] / 2
            for j in range(i + 1, n):
                if S[i, j]:
                    J[(i, j)] = S[i, j] / 2
                    h[i] -= S[i, j] / 2
                    h[j] -= S[i, j] / 2
                    const += S[i, j] / 2
        return h, J, const


# ------------------------------------------------------------------- QAOA simulator

def _mix(psi: np.ndarray, beta: float, n: int) -> np.ndarray:
    c, s = math.cos(beta), -1j * math.sin(beta)
    t = psi.reshape([2] * n)
    for ax in range(n):  # exp(-i beta X) on each qubit; they commute
        t = c * t + s * np.flip(t, axis=ax)
    return t.reshape(-1)


def qaoa_state(cn: np.ndarray, gammas, betas, n: int) -> np.ndarray:
    psi = np.full(2 ** n, 2 ** (-n / 2), dtype=complex)
    for g, b in zip(gammas, betas):
        psi = psi * np.exp(-1j * g * cn)
        psi = _mix(psi, b, n)
    return psi


def _cvar(probs: np.ndarray, cn_sorted: np.ndarray, order: np.ndarray, alpha: float) -> float:
    p = probs[order]
    cum = np.cumsum(p)
    k = int(np.searchsorted(cum, alpha))
    k = min(k, len(p) - 1)
    head = float(np.dot(p[:k], cn_sorted[:k]))
    rest = alpha - (cum[k - 1] if k else 0.0)
    return (head + rest * cn_sorted[k]) / alpha


def _interp(params: np.ndarray) -> np.ndarray:
    """INTERP: p trained angles -> p+1 starting angles."""
    p = len(params)
    ext = np.concatenate([[0.0], params, [0.0]])
    return np.array([(i / p) * ext[i] + ((p - i) / p) * ext[i + 1] for i in range(p + 1)])


def solve(qubo: Qubo, layers: int = 2, shots: int = 1024, alpha: float = 0.2,
          seed: int | None = None, deadline_s: float = 20.0) -> dict:
    if not 1 <= layers <= MAX_LAYERS:
        raise ProblemError(f"layers must be 1-{MAX_LAYERS}")
    if not 1 <= shots <= 100_000:
        raise ProblemError("shots must be 1-100000")
    t0 = time.monotonic()
    n = qubo.n
    costs = qubo.all_costs()
    cmin, cmax = float(costs.min()), float(costs.max())
    span = cmax - cmin
    if span <= 0:
        raise ProblemError("every assignment has the same cost; nothing to optimize")
    cn = (costs - cmin) / span
    order = np.argsort(cn, kind="stable")
    cn_sorted = cn[order]
    evals = 0

    def objective(theta):
        nonlocal evals
        evals += 1
        p = len(theta) // 2
        probs = np.abs(qaoa_state(cn, theta[:p], theta[p:], n)) ** 2
        return _cvar(probs, cn_sorted, order, alpha)

    # p = 1: coarse grid, then local refinement
    best_val, best = math.inf, None
    for g in np.linspace(0.2, 2 * math.pi, 14):
        for b in np.linspace(0.1, math.pi / 2, 8):
            v = objective(np.array([g, b]))
            if v < best_val:
                best_val, best = v, np.array([g, b])
    gam, bet = best[:1], best[1:]
    for p in range(1, layers + 1):
        if p > 1:
            gam, bet = _interp(gam), _interp(bet)
        budget = 0 if time.monotonic() - t0 > deadline_s else 60 + 40 * p
        if budget:
            r = minimize(objective, np.concatenate([gam, bet]), method="COBYLA",
                         options={"maxiter": budget, "rhobeg": 0.3})
            gam, bet = r.x[:p], r.x[p:]

    psi = qaoa_state(cn, gam, bet, n)
    probs = np.abs(psi) ** 2
    probs /= probs.sum()
    rng = np.random.default_rng(seed)
    samples = rng.choice(len(probs), size=shots, p=probs)
    uniq, counts = np.unique(samples, return_counts=True)
    best_k = int(uniq[np.argmin(costs[uniq])])
    tol = 1e-9 * max(1.0, abs(cmin))
    opt_mask = costs <= cmin + tol
    exact_k = int(np.argmin(costs))
    random_mean = float(costs.mean())
    top = sorted(zip(uniq.tolist(), counts.tolist()), key=lambda kv: -kv[1])[:5]

    def bits_of(k):
        return [int((k >> i) & 1) for i in range(n)]

    return {
        "algorithm": f"CVaR-QAOA (alpha={alpha}), p={layers} layers, INTERP init, COBYLA",
        "qubits": n,
        "solution": bits_of(best_k),
        "cost": float(costs[best_k]),
        "found_optimum": bool(opt_mask[best_k]),
        "approximation_ratio": round((cmax - float(costs[best_k])) / span, 6),
        "probability_of_optimum": round(float(probs[opt_mask].sum()), 6),
        "random_guess_probability_of_optimum": round(float(opt_mask.sum()) / len(costs), 6),
        "amplification": round(float(probs[opt_mask].sum()) / (float(opt_mask.sum()) / len(costs)), 2),
        "exact": {"solution": bits_of(exact_k), "cost": cmin,
                  "method": f"classical exhaustive search over {2 ** n} assignments"},
        "random_assignment_mean_cost": random_mean,
        "top_samples": [{"bits": bits_of(k), "count": c, "cost": float(costs[k])} for k, c in top],
        "shots": shots,
        "angles": {"gamma": [round(float(g), 6) for g in gam], "beta": [round(float(b), 6) for b in bet]},
        "cost_normalization": {"min": cmin, "span": span},
        "objective_evaluations": evals,
        "runtime_ms": round((time.monotonic() - t0) * 1000),
    }


def to_qasm(qubo: Qubo, gammas, betas, cmin: float, span: float) -> str:
    """OpenQASM 2.0 for the trained circuit. Bit i of the result = variable i."""
    h, J, _ = qubo.ising()
    n = qubo.n
    L = ["OPENQASM 2.0;", 'include "qelib1.inc";', f"qreg q[{n}];", f"creg c[{n}];"]
    L += [f"h q[{i}];" for i in range(n)]
    for g, b in zip(gammas, betas):
        for i in range(n):
            if h[i]:
                L.append(f"rz({float(2 * g * h[i] / span)!r}) q[{i}];")
        for (i, j), w in J.items():
            L += [f"cx q[{i}],q[{j}];", f"rz({float(2 * g * w / span)!r}) q[{j}];", f"cx q[{i}],q[{j}];"]
        L += [f"rx({float(2 * b)!r}) q[{i}];" for i in range(n)]
    L += [f"measure q[{i}] -> c[{i}];" for i in range(n)]
    return "\n".join(L) + "\n"


# ------------------------------------------------------------ manufacturing templates

def _num(v, what) -> float:
    try:
        f = float(v)
    except (TypeError, ValueError):
        raise ProblemError(f"{what} must be a number")
    if not math.isfinite(f) or abs(f) > MAX_ABS:
        raise ProblemError(f"{what} must be finite and below 1e9")
    return f


def _names(items, key="name") -> list[str]:
    out = []
    for i, it in enumerate(items):
        nm = str(it.get(key, f"item{i + 1}")) if isinstance(it, dict) else str(it)
        out.append(nm[:80])
    if len(set(out)) != len(out):
        raise ProblemError("names must be unique")
    return out


def balance_lines(data: dict) -> tuple[Qubo, callable]:
    """Split jobs across two production lines so the loads are as equal as possible."""
    jobs = data.get("jobs") or []
    if not 2 <= len(jobs) <= MAX_QUBITS:
        raise ProblemError(f"give 2-{MAX_QUBITS} jobs as [{{name, minutes}}]")
    names = _names(jobs)
    w = np.array([_num(j.get("minutes") if isinstance(j, dict) else j, "minutes") for j in jobs])
    if np.any(w <= 0):
        raise ProblemError("minutes must be positive")
    W = w.sum()
    Q = 4 * np.outer(w, w)
    np.fill_diagonal(Q, 4 * w * w - 4 * W * w)
    qubo = Qubo(Q, float(W * W), names)
    la, lb = data.get("line_a", "Line A"), data.get("line_b", "Line B")

    def decode(x):
        a = [names[i] for i in range(len(x)) if not x[i]]
        b = [names[i] for i in range(len(x)) if x[i]]
        A = float(sum(w[i] for i in range(len(x)) if not x[i]))
        return {"assignment": {la: a, lb: b}, "load_minutes": {la: A, lb: float(W - A)},
                "imbalance_minutes": float(abs(2 * A - W))}
    return qubo, decode


def select_lots(data: dict) -> tuple[Qubo, callable]:
    """Pick exactly k lots to inspect: maximize total risk, avoid picking linked lots together."""
    lots = data.get("lots") or []
    n = len(lots)
    if not 2 <= n <= MAX_QUBITS:
        raise ProblemError(f"give 2-{MAX_QUBITS} lots as [{{name, risk}}]")
    names = _names(lots)
    r = np.array([_num(l.get("risk") if isinstance(l, dict) else l, "risk") for l in lots])
    k = int(_num(data.get("k", max(1, n // 3)), "k"))
    if not 1 <= k < n:
        raise ProblemError("k must be at least 1 and less than the number of lots")
    lam = _num(data.get("link_penalty", float(np.mean(np.abs(r))) or 1.0), "link_penalty")
    A = 1.0 + float(np.sum(np.abs(r))) + lam * n
    Q = np.zeros((n, n))
    np.fill_diagonal(Q, -r + A * (1 - 2 * k))
    Q += A * (np.ones((n, n)) - np.eye(n))
    idx = {nm: i for i, nm in enumerate(names)}
    links = []
    for pair in data.get("linked", []) or []:
        if not (isinstance(pair, (list, tuple)) and len(pair) == 2) or pair[0] not in idx or pair[1] not in idx:
            raise ProblemError("linked must be a list of [lot_name, lot_name] pairs")
        i, j = idx[pair[0]], idx[pair[1]]
        if i != j:
            Q[i, j] += lam / 2; Q[j, i] += lam / 2
            links.append((i, j))
    qubo = Qubo(Q, A * k * k, names)

    def decode(x):
        chosen = [names[i] for i in range(n) if x[i]]
        return {"inspect": chosen, "count": len(chosen), "k": k, "meets_k": len(chosen) == k,
                "total_risk": float(sum(r[i] for i in range(n) if x[i])),
                "linked_pairs_both_chosen": [[names[i], names[j]] for i, j in links if x[i] and x[j]]}
    return qubo, decode


def split_conflicts(data: dict) -> tuple[Qubo, callable]:
    """Two groups (shifts, trucks, cells) so conflicting pairs end up apart (weighted Max-Cut)."""
    items = data.get("items") or []
    n = len(items)
    if not 2 <= n <= MAX_QUBITS:
        raise ProblemError(f"give 2-{MAX_QUBITS} items")
    names = _names(items)
    idx = {nm: i for i, nm in enumerate(names)}
    Q = np.zeros((n, n))
    edges = []
    for c in data.get("conflicts") or []:
        a, b = (c.get("a"), c.get("b")) if isinstance(c, dict) else (c[0], c[1])
        if a not in idx or b not in idx or a == b:
            raise ProblemError("each conflict needs two different item names: {a, b, weight}")
        wt = _num(c.get("weight", 1) if isinstance(c, dict) else (c[2] if len(c) > 2 else 1), "weight")
        i, j = idx[a], idx[b]
        Q[i, i] -= wt; Q[j, j] -= wt; Q[i, j] += wt; Q[j, i] += wt
        edges.append((i, j, wt))
    if not edges:
        raise ProblemError("give at least one conflict")
    qubo = Qubo(Q, 0.0, names)
    ga, gb = data.get("group_a", "Group A"), data.get("group_b", "Group B")

    def decode(x):
        kept = [[names[i], names[j]] for i, j, _ in edges if x[i] == x[j]]
        return {"groups": {ga: [names[i] for i in range(n) if not x[i]], gb: [names[i] for i in range(n) if x[i]]},
                "separated_weight": float(sum(w for i, j, w in edges if x[i] != x[j])),
                "total_conflict_weight": float(sum(w for *_, w in edges)),
                "conflicts_left_together": kept}
    return qubo, decode


def raw_qubo(data: dict) -> tuple[Qubo, callable]:
    Q = data.get("Q")
    if not isinstance(Q, list):
        raise ProblemError("give Q as a square list of lists")
    try:
        arr = np.array(Q, dtype=float)
    except (TypeError, ValueError):
        raise ProblemError("Q must contain only numbers")
    qubo = Qubo(arr, _num(data.get("offset", 0), "offset"), data.get("names"))
    return qubo, lambda x: {"assignment": dict(zip(qubo.names, x))}


TEMPLATES = {
    "balance_lines": (balance_lines, "Split jobs across two lines to equalize load. data: {jobs: [{name, minutes}], line_a?, line_b?}"),
    "select_lots": (select_lots, "Choose exactly k lots to inspect, maximizing risk and avoiding linked pairs. data: {lots: [{name, risk}], k, linked?: [[a, b]], link_penalty?}"),
    "split_conflicts": (split_conflicts, "Two groups so conflicting items are separated (weighted Max-Cut). data: {items: [names], conflicts: [{a, b, weight}], group_a?, group_b?}"),
    "qubo": (raw_qubo, "Any binary optimization: minimize x^T Q x + offset. data: {Q: [[...]], offset?, names?}"),
}


def build(problem: str, data: dict) -> tuple[Qubo, callable]:
    if problem not in TEMPLATES:
        raise ProblemError(f"problem must be one of: {', '.join(TEMPLATES)}")
    if not isinstance(data, dict):
        raise ProblemError("data must be an object")
    return TEMPLATES[problem][0](data)
