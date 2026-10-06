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
