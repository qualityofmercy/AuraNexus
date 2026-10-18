"""Dependency graph utilities shared by the Build Sequencer, Test Sequencer and Cutover monitor."""

from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass, field


@dataclass
class GraphResult:
    waves: list[list[str]] = field(default_factory=list)
    critical_path: list[str] = field(default_factory=list)
    critical_length: float = 0.0
    cycles: list[list[str]] = field(default_factory=list)
    missing_prerequisites: list[tuple[str, str]] = field(default_factory=list)  # (node, missing prereq)

    def as_dict(self) -> dict:
        return {
            "waves": self.waves,
            "critical_path": self.critical_path,
            "critical_length": self.critical_length,
            "cycles": self.cycles,
            "missing_prerequisites": [list(x) for x in self.missing_prerequisites],
        }


def analyse(
    nodes: list[str],
    edges: list[tuple[str, str]],
    durations: dict[str, float] | None = None,
) -> GraphResult:
    """Edges are (prerequisite, dependent). Returns parallel waves, the critical path and defects.

    Nodes in a cycle are excluded from waves and reported, so a human decides how to break it.
    """
    durations = durations or {}
    node_set = set(nodes)
    res = GraphResult()
    preds: dict[str, set[str]] = defaultdict(set)
    succs: dict[str, set[str]] = defaultdict(set)
    for a, b in edges:
        if b not in node_set:
            continue
        if a not in node_set:
            res.missing_prerequisites.append((b, a))
            continue
        if a == b:
            res.cycles.append([a])
            continue
        preds[b].add(a)
        succs[a].add(b)

    indeg = {n: len(preds[n]) for n in node_set}
    ready = deque(sorted(n for n, d in indeg.items() if d == 0))
    finish: dict[str, float] = {}
    best_pred: dict[str, str | None] = {}
    placed: set[str] = set()
    while ready:
        wave = list(ready)
        ready.clear()
        res.waves.append(wave)
        nxt = []
        for n in wave:
            placed.add(n)
            start, bp = 0.0, None
            for p in preds[n]:
                if finish[p] > start:
                    start, bp = finish[p], p
            finish[n] = start + durations.get(n, 1.0)
            best_pred[n] = bp
            for s in sorted(succs[n]):
                indeg[s] -= 1
                if indeg[s] == 0:
                    nxt.append(s)
        ready.extend(sorted(nxt))

    leftover = sorted(node_set - placed)
    if leftover:
        res.cycles.extend(_cycles(leftover, succs))
    if finish:
        end = max(finish, key=lambda n: (finish[n], n))
        res.critical_length = finish[end]
        path: list[str] = []
        cur: str | None = end
        while cur is not None:
            path.append(cur)
            cur = best_pred.get(cur)
        res.critical_path = list(reversed(path))
    return res


def _cycles(nodes: list[str], succs: dict[str, set[str]]) -> list[list[str]]:
    """Report each strongly connected component of size > 1 (iterative Tarjan)."""
    nodeset, index, low, onstack, stack, out = set(nodes), {}, {}, set(), [], []
    counter = 0
    for root in nodes:
        if root in index:
            continue
        work = [(root, iter(sorted(succs[root] & nodeset)))]
        index[root] = low[root] = counter
        counter += 1
        stack.append(root)
        onstack.add(root)
        while work:
            v, it = work[-1]
            advanced = False
            for w in it:
                if w not in index:
                    index[w] = low[w] = counter
                    counter += 1
                    stack.append(w)
                    onstack.add(w)
                    work.append((w, iter(sorted(succs[w] & nodeset))))
                    advanced = True
                    break
                if w in onstack:
                    low[v] = min(low[v], index[w])
            if advanced:
                continue
            work.pop()
            if work:
                low[work[-1][0]] = min(low[work[-1][0]], low[v])
            if low[v] == index[v]:
                comp = []
                while True:
                    w = stack.pop()
                    onstack.discard(w)
                    comp.append(w)
                    if w == v:
                        break
                if len(comp) > 1:
                    out.append(sorted(comp))
    return out


def downstream(start: str, edges: list[tuple[str, str]]) -> set[str]:
    """All nodes reachable from ``start`` (used for blocked-script and change-impact fan-out)."""
    succs: dict[str, list[str]] = defaultdict(list)
    for a, b in edges:
        succs[a].append(b)
    seen, q = set(), deque([start])
    while q:
        for n in succs[q.popleft()]:
            if n not in seen:
                seen.add(n)
                q.append(n)
    return seen
