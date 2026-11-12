"""The impact walk.

A function is affected if it is in S0, or calls an affected function whose model changed. Propagation continues
through a function only if its own model changed.
"""
import collections


def walk(s0, graph, model_changed, max_depth=8, max_fanout=200, seeds=()):
    """{fid: {"depth", "reasons", "boundary", "truncated"}}. A reason is ("changed",) for S0, ("calls", callee fid)
    for a caller of a model-changed callee, or ("model",) for a seed: a function whose derived model changed although
    none of its lines did (a header macro, an inline function or a type it uses changed). Seeds are walked after S0,
    and only those S0's walk did not reach."""
    affected = {}
    queue = collections.deque((fid, 0, ("changed",)) for fid in s0)
    pending = list(seeds)
    while queue or pending:
        if not queue:
            fid = pending.pop(0)
            if fid not in affected:
                queue.append((fid, 0, ("model",)))
            continue
        fid, depth, reason = queue.popleft()
        if fid in affected:
            if reason not in affected[fid]["reasons"]:
                affected[fid]["reasons"].append(reason)
            continue
        info = affected[fid] = {"depth": depth, "reasons": [reason], "boundary": False, "truncated": False,
                                "address_taken": sorted(graph.address_taken.get(fid, ()))}
        if not model_changed(fid):
            info["boundary"] = True
            continue
        callers = sorted(graph.callers.get(fid, ()))
        if depth >= max_depth or len(callers) > max_fanout:
            info["truncated"] = True
            continue
        for c in callers:
            queue.append((c, depth + 1, ("calls", fid)))
    return affected
