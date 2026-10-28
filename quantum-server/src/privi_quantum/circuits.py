# Copyright (c) 2026 Privi World Co. All rights reserved.
# Privi Quantum - https://priviflow.us - dariocanoy@priviflow.us
"""Bring your own circuit: read OpenQASM 2.0 or 3.0 (what Qiskit's qasm2.dumps / qasm3.dumps write) and
rewrite it into the four gates every Privi backend runs: h, rz, rx and cx.

Every standard-library gate Qiskit emits for ordinary circuits is supported (id, x, y, z, h, s, sdg, t, tdg, sx,
sxdg, rx, ry, rz, p, u1, u2, u3, u, U, cx/CX/cnot, cy, cz, ch, swap, crx, cry, crz, cp/cu1, ccx, rxx, ryy, rzz).
Rewrites are exact up to a global phase, which no measurement can see. All qubits are measured at the end;
mid-circuit measurement, reset, classical control and custom `gate` definitions are refused with a hint
(in Qiskit: `transpile(circuit, basis_gates=["h", "rz", "rx", "cx"])` removes custom gates).
"""
from __future__ import annotations

import ast
import hashlib
import math
import operator
import re

MAX_QUBITS = 32          # providers enforce their own limits; the local simulator stops at LOCAL_MAX_QUBITS
LOCAL_MAX_QUBITS = 20
MAX_GATES = 20000
MAX_SOURCE = 400_000

PI = math.pi


class CircuitError(ValueError):
    pass


# ---------------------------------------------------------------- angle expressions

_OPS = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul, ast.Div: operator.truediv,
        ast.Pow: operator.pow, ast.USub: operator.neg, ast.UAdd: operator.pos}
_FUNCS = {"sin": math.sin, "cos": math.cos, "tan": math.tan, "exp": math.exp, "ln": math.log, "sqrt": math.sqrt,
          "asin": math.asin, "acos": math.acos, "atan": math.atan}
_NAMES = {"pi": PI, "π": PI, "tau": 2 * PI, "τ": 2 * PI, "e": math.e, "euler": math.e}


def angle(expr: str) -> float:
    """Evaluate a QASM angle like `pi/2`, `-3*pi/4`, `0.25`, `1.5e-3`, `2*π` safely (no names besides constants)."""
    src = expr.strip().replace("π", "pi").replace("τ", "tau")
    try:
        tree = ast.parse(src, mode="eval")
    except SyntaxError:
        raise CircuitError(f"cannot read angle {expr!r}")

    def ev(n):
        if isinstance(n, ast.Expression):
            return ev(n.body)
        if isinstance(n, ast.Constant) and isinstance(n.value, (int, float)) and not isinstance(n.value, bool):
            return float(n.value)
        if isinstance(n, ast.Name) and n.id in _NAMES:
            return _NAMES[n.id]
        if isinstance(n, ast.BinOp) and type(n.op) in _OPS:
            return _OPS[type(n.op)](ev(n.left), ev(n.right))
        if isinstance(n, ast.UnaryOp) and type(n.op) in _OPS:
            return _OPS[type(n.op)](ev(n.operand))
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id in _FUNCS and len(n.args) == 1:
            return _FUNCS[n.func.id](ev(n.args[0]))
        raise CircuitError(f"cannot read angle {expr!r}")
    v = ev(tree)
    if not math.isfinite(v):
        raise CircuitError(f"angle {expr!r} is not a finite number")
    return v


# ---------------------------------------------------------------- gate library -> h, rz, rx, cx

def _ry(t, q):
    return [("rz", q, -PI / 2), ("rx", q, t), ("rz", q, PI / 2)]


def _u3(th, ph, la, q):
    return [("rz", q, la)] + _ry(th, q) + [("rz", q, ph)]


def _cx(c, t):
    return [("cx", c, t)]


def _crz(th, c, t):
    return [("rz", t, th / 2), ("cx", c, t), ("rz", t, -th / 2), ("cx", c, t)]


def _cp(la, c, t):
    return [("rz", c, la / 2), ("cx", c, t), ("rz", t, -la / 2), ("cx", c, t), ("rz", t, la / 2)]


def _ccx(a, b, t):
    T, Td = (lambda q: ("rz", q, PI / 4)), (lambda q: ("rz", q, -PI / 4))
    return [("h", t), ("cx", b, t), Td(t), ("cx", a, t), T(t), ("cx", b, t), Td(t), ("cx", a, t),
            T(b), T(t), ("h", t), ("cx", a, b), T(a), Td(b), ("cx", a, b)]


def _rzz(th, a, b):
    return [("cx", a, b), ("rz", b, th), ("cx", a, b)]


def _rxx(th, a, b):
    return [("h", a), ("h", b)] + _rzz(th, a, b) + [("h", a), ("h", b)]


def _ryy(th, a, b):
    return [("rx", a, PI / 2), ("rx", b, PI / 2)] + _rzz(th, a, b) + [("rx", a, -PI / 2), ("rx", b, -PI / 2)]


# name -> (number of angle params, number of qubits, expansion(params..., qubits...))
GATES = {
    "id": (0, 1, lambda q: []), "i": (0, 1, lambda q: []),
    "x": (0, 1, lambda q: [("rx", q, PI)]),
    "y": (0, 1, lambda q: [("rz", q, PI), ("rx", q, PI)]),
    "z": (0, 1, lambda q: [("rz", q, PI)]),
    "h": (0, 1, lambda q: [("h", q)]),
    "s": (0, 1, lambda q: [("rz", q, PI / 2)]), "sdg": (0, 1, lambda q: [("rz", q, -PI / 2)]),
    "t": (0, 1, lambda q: [("rz", q, PI / 4)]), "tdg": (0, 1, lambda q: [("rz", q, -PI / 4)]),
    "sx": (0, 1, lambda q: [("rx", q, PI / 2)]), "sxdg": (0, 1, lambda q: [("rx", q, -PI / 2)]),
    "rx": (1, 1, lambda t, q: [("rx", q, t)]), "ry": (1, 1, _ry), "rz": (1, 1, lambda t, q: [("rz", q, t)]),
    "p": (1, 1, lambda t, q: [("rz", q, t)]), "u1": (1, 1, lambda t, q: [("rz", q, t)]),
    "phase": (1, 1, lambda t, q: [("rz", q, t)]),
    "u2": (2, 1, lambda ph, la, q: _u3(PI / 2, ph, la, q)),
    "u3": (3, 1, _u3), "u": (3, 1, _u3), "U": (3, 1, _u3),
    "cx": (0, 2, _cx), "CX": (0, 2, _cx), "cnot": (0, 2, _cx),
    "cz": (0, 2, lambda c, t: [("h", t), ("cx", c, t), ("h", t)]),
    "cy": (0, 2, lambda c, t: [("rz", t, -PI / 2), ("cx", c, t), ("rz", t, PI / 2)]),
    "ch": (0, 2, lambda c, t: _ry(PI / 4, t) + [("cx", c, t)] + _ry(-PI / 4, t)),
    "swap": (0, 2, lambda a, b: [("cx", a, b), ("cx", b, a), ("cx", a, b)]),
    "crz": (1, 2, _crz),
    "crx": (1, 2, lambda th, c, t: [("h", t)] + _crz(th, c, t) + [("h", t)]),
    "cry": (1, 2, lambda th, c, t: _ry(th / 2, t) + [("cx", c, t)] + _ry(-th / 2, t) + [("cx", c, t)]),
    "cp": (1, 2, _cp), "cu1": (1, 2, _cp), "cphase": (1, 2, _cp),
    "ccx": (0, 3, _ccx), "toffoli": (0, 3, _ccx),
    "rzz": (1, 2, _rzz), "rxx": (1, 2, _rxx), "ryy": (1, 2, _ryy),
}

_IGNORE = ("OPENQASM", "include", "barrier", "gphase", "//")
_REFUSE = {"reset": "reset is not supported (all qubits start in |0>)",
           "if": "classical control (if) is not supported",
           "gate": "custom gate definitions are not supported: in Qiskit, transpile(circuit, basis_gates=['h','rz','rx','cx']) first",
           "opaque": "opaque gates are not supported", "def": "subroutines are not supported",
           "for": "loops are not supported", "while": "loops are not supported", "input": "input parameters are not supported",
           "delay": None, "box": "box is not supported"}


def _strip_comments(src: str) -> str:
    src = re.sub(r"/\*.*?\*/", " ", src, flags=re.S)
    return "\n".join(line.split("//", 1)[0] for line in src.splitlines())


def _split_args(s: str) -> list[str]:
    out, depth, cur = [], 0, ""
    for ch in s:
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
        if ch == "," and depth == 0:
            out.append(cur)
            cur = ""
        else:
            cur += ch
    if cur.strip():
        out.append(cur)
    return [x.strip() for x in out]


def parse(source: str) -> dict:
    """OpenQASM 2.0 / 3.0 -> {"qubits": n, "gates": [...basis...], "source_gates": k, "version": "2.0"|"3.0", "registers": {...}}."""
    if not isinstance(source, str) or not source.strip():
        raise CircuitError("send the circuit as OpenQASM text (Qiskit: qasm2.dumps(circuit) or qasm3.dumps(circuit))")
    if len(source) > MAX_SOURCE:
        raise CircuitError(f"circuit text is over {MAX_SOURCE // 1000} KB")
    text = _strip_comments(source)
    m = re.search(r"OPENQASM\s+([0-9.]+)\s*;", text)
    version = m.group(1) if m else "2.0"
    if not version.startswith(("2", "3")):
        raise CircuitError(f"OpenQASM {version} is not supported (use 2.0 or 3.0)")
    regs: dict[str, tuple[int, int]] = {}            # name -> (offset, size)
    total = 0
    gates: list[tuple] = []
    source_gates = 0

    def qubits_of(tok: str) -> list[int]:
        tok = tok.strip()
        mm = re.fullmatch(r"([A-Za-z_]\w*)\s*\[\s*(\d+)\s*\]", tok)
        if mm:
            name, i = mm.group(1), int(mm.group(2))
            if name not in regs:
                raise CircuitError(f"unknown qubit register {name}")
            off, size = regs[name]
            if i >= size:
                raise CircuitError(f"{tok} is outside register {name}[{size}]")
            return [off + i]
        if re.fullmatch(r"[A-Za-z_]\w*", tok):
            if tok not in regs:
                raise CircuitError(f"unknown qubit register {tok}")
            off, size = regs[tok]
            return list(range(off, off + size))
        raise CircuitError(f"cannot read qubit {tok!r}")

    for stmt in (s.strip() for s in text.replace("\n", " ").split(";")):
        if not stmt:
            continue
        if stmt.startswith(_IGNORE):
            continue
        head = re.match(r"[A-Za-z_]\w*", stmt)
        word = head.group(0) if head else ""
        if word in _REFUSE:
            if _REFUSE[word] is None:
                continue
            raise CircuitError(_REFUSE[word])
        # declarations
        mm = re.fullmatch(r"qreg\s+([A-Za-z_]\w*)\s*\[\s*(\d+)\s*\]", stmt) or \
            re.fullmatch(r"qubit\s*\[\s*(\d+)\s*\]\s*([A-Za-z_]\w*)", stmt)
        if mm:
            name, size = (mm.group(1), int(mm.group(2))) if stmt.startswith("qreg") else (mm.group(2), int(mm.group(1)))
            if name in regs:
                raise CircuitError(f"register {name} declared twice")
            regs[name] = (total, size)
            total += size
            if total > MAX_QUBITS:
                raise CircuitError(f"more than {MAX_QUBITS} qubits")
            continue
        mm = re.fullmatch(r"qubit\s+([A-Za-z_]\w*)", stmt)
        if mm:
            regs[mm.group(1)] = (total, 1)
            total += 1
            continue
        if re.match(r"(creg|bit)\b", stmt):
            continue
        # measurement (all qubits are measured at the end; final measurements are fine)
        if "measure" in stmt:
            if re.fullmatch(r"(?:[A-Za-z_]\w*(?:\s*\[\s*\d+\s*\])?\s*=\s*)?measure\s+[^=]+?(?:->\s*\S+)?", stmt):
                continue
            raise CircuitError(f"cannot read measurement {stmt[:60]!r}")
        # gate application: name(params)? args
        mm = re.fullmatch(r"([A-Za-z_]\w*)\s*(?:\((.*)\))?\s+(.+)", stmt)
        if not mm:
            raise CircuitError(f"cannot read {stmt[:80]!r}")
        name, params, args = mm.group(1), mm.group(2), mm.group(3)
        if name.startswith(("ctrl", "inv", "pow", "negctrl")) or "@" in stmt:
            raise CircuitError("gate modifiers (ctrl@, inv@, pow@) are not supported; transpile to basis gates first")
        if name not in GATES:
            raise CircuitError(f"gate {name} is not supported; in Qiskit, transpile(circuit, basis_gates=['h','rz','rx','cx']) first")
        n_par, n_q, expand = GATES[name]
        vals = [angle(p) for p in _split_args(params)] if params else []
        if len(vals) != n_par:
            raise CircuitError(f"{name} takes {n_par} angle(s), got {len(vals)}")
        qargs = [qubits_of(a) for a in _split_args(args)]
        if len(qargs) != n_q:
            raise CircuitError(f"{name} acts on {n_q} qubit(s), got {len(qargs)}")
        width = max(len(q) for q in qargs)
        if any(len(q) not in (1, width) for q in qargs):
            raise CircuitError(f"register sizes do not match in {stmt[:60]!r}")
        for k in range(width):
            qs = [q[0] if len(q) == 1 else q[k] for q in qargs]
            if len(set(qs)) != len(qs):
                raise CircuitError(f"{name} uses the same qubit twice")
            gates.extend(expand(*vals, *qs))
            source_gates += 1
        if len(gates) > MAX_GATES:
            raise CircuitError(f"more than {MAX_GATES} basic gates after rewriting")
    if not total:
        raise CircuitError("the circuit declares no qubits (qreg q[n]; or qubit[n] q;)")
    return {"qubits": total, "gates": gates, "source_gates": source_gates, "version": version,
            "registers": {k: v[1] for k, v in regs.items()},
            "source_sha256": hashlib.sha256(source.encode()).hexdigest()}


def to_basis_qasm(n: int, gates: list[tuple]) -> str:
    """The rewritten circuit as the OpenQASM 2.0 Privi backends take (h, rz, rx, cx, then measure all)."""
    L = ["OPENQASM 2.0;", 'include "qelib1.inc";', f"qreg q[{n}];", f"creg c[{n}];"]
    for g in gates:
        if g[0] == "h":
            L.append(f"h q[{g[1]}];")
        elif g[0] == "cx":
            L.append(f"cx q[{g[1]}],q[{g[2]}];")
        else:
            L.append(f"{g[0]}({g[2]!r}) q[{g[1]}];")
    L += [f"measure q[{i}] -> c[{i}];" for i in range(n)]
    return "\n".join(L) + "\n"


def bitstring(k: int, n: int) -> str:
    """Qiskit's order: classical bit n-1 on the left, bit 0 (qubit 0) on the right."""
    return format(k, f"0{n}b")
