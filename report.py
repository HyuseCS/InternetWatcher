def classify(results):
    def ok(t):
        return t in results and bool(results[t][0])

    def failed(t):
        return t in results and not results[t][0]

    down = set()
    if failed("router"):
        down.add("local")
    if ok("router") and failed("direct") and failed("web"):
        down.add("internet")
    if ok("direct") and failed("dns"):
        down.add("dns")
    if (ok("direct") or ok("web")) and ok("dns") and (failed("github_https") or failed("github_ssh")):
        down.add("github")
    return down


TARGETS = {
    "local": ("router",),
    "internet": ("direct", "web"),
    "dns": ("dns",),
    "github": ("github_https", "github_ssh"),
}


def find_outages(rounds, now):
    outages, blips, gaps = [], [], []
    runs = {}

    def close(kind, end):
        run = runs.pop(kind)
        if len(run) == 1:
            blips.append((kind, run[0][0]))
            return
        failed = [t for t in TARGETS[kind] if any(t in r and not r[t][0] for _, r in run)]
        errors = [r[t][1] for _, r in run for t in TARGETS[kind] if t in r and not r[t][0] and r[t][1]]
        start = run[0][0]
        outages.append({
            "type": kind,
            "start": start,
            "end": end,
            "length": int(((end or now) - start).total_seconds()),
            "failed_targets": failed,
            "sample_error": errors[0] if errors else None,
        })

    last = None
    for at, interval, results in rounds:
        if last and (at - last).total_seconds() > 3 * interval:
            gaps.append((last, at))
            for kind in list(runs):
                close(kind, last)
        down = classify(results)
        for kind in list(runs):
            if kind not in down:
                close(kind, at)
        for kind in down:
            runs.setdefault(kind, []).append((at, results))
        last = at
    if rounds:
        stale = (now - last).total_seconds() > 3 * rounds[-1][1]
        if stale:
            gaps.append((last, now))
        for kind in list(runs):
            close(kind, last if stale else None)
    outages.sort(key=lambda o: o["start"])
    blips.sort(key=lambda b: b[1])
    return outages, blips, gaps
