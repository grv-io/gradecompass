"""
GradeCompass engine parity test
================================
Runs every input combination -- 7 applications x 12 districts x 3 cost
sensitivities x 3 welded states (app default / True / False) = 756 cases --
through the Python reference engine (gradecompass_poc.py) and the JavaScript
port (../frontend/engine.js, and the copy inlined in ../frontend/index.html),
and asserts that the JSON payloads are identical apart from timing.

Run:  python parity_test.py          (needs python3 and node on PATH)
Exit code 0 = all 756 cases identical in all three engines.
"""
import itertools, json, os, subprocess, sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import gradecompass_poc as G  # noqa: E402

FRONTEND = os.environ.get("GC_FRONTEND") or (
    os.path.join(HERE, "..", "frontend")
    if os.path.exists(os.path.join(HERE, "..", "frontend", "index.html"))
    else os.path.join(HERE, ".."))   # public repo layout: index.html / engine.js at the root, this test under poc/
COSTS = ["low", "medium", "high"]
WELDS = [None, True, False]


def python_cases():
    out = []
    for app, dist, cost, weld in itertools.product(G.APPLICATIONS, G.DISTRICTS, COSTS, WELDS):
        r = G.recommend(app, dist, cost, weld)
        r.pop("engine_ms")
        out.append(r)
    return out


def js_cases(mode):
    """mode = 'module' (engine.js via require) or 'inline' (index.html <script>)."""
    script = os.path.join(HERE, "parity_test.js")
    res = subprocess.run(["node", script, mode, FRONTEND], capture_output=True, text=True, encoding="utf-8")
    if res.returncode != 0:
        raise SystemExit(f"node failed ({mode}):\n{res.stderr}")
    return json.loads(res.stdout)


def normalise(x):
    return json.loads(json.dumps(x, sort_keys=True))


def main():
    py = python_cases()
    ok = True
    for mode in ("module", "inline"):
        js = js_cases(mode)
        mism = [i for i, (a, b) in enumerate(zip(py, js)) if normalise(a) != normalise(b)]
        status = "OK" if (not mism and len(js) == len(py)) else "MISMATCH"
        print(f"{mode:7} : {len(py)} python cases vs {len(js)} js cases -> {len(mism)} mismatches  [{status}]")
        for i in mism[:3]:
            print("  PY:", json.dumps(py[i], sort_keys=True)[:300])
            print("  JS:", json.dumps(js[i], sort_keys=True)[:300])
        ok = ok and status == "OK"
    none = [(r["input"]["app"], r["input"]["location"]) for r in py if r["recommendation"] is None]
    apps_without_grade = sorted({a for a, _ in none})
    print(f"no-recommendation cases: {len(none)} (applications: {apps_without_grade})")

    # Behavioural regression guards -- one per flaw the 26 Sep audit corrected.
    # They run on the Python reference; parity above carries them to both JS copies.
    def guard(label, cond):
        nonlocal ok
        print(f"guard   : {label:58} [{'OK' if cond else 'FAIL'}]")
        ok = ok and cond
    pem = [r for r in py if r["input"]["app"] == "pem_electrolyzer"]
    guard("PEM never returns duplex (hydrogen-embrittlement veto)",
          all(r["recommendation"]["grade"] != "2205" and "2205" not in r["survivors"] for r in pem))
    kit = [r for r in py if r["input"]["app"] == "kitchen_utensils"]
    guard("utensils always return a grade (food-contact pathway)",
          bool(kit) and all(r["recommendation"] is not None for r in kit))
    goa_w = [r for r in py if r["input"]["app"] == "outdoor_railing"
             and r["input"]["location"] == "Panaji, Goa" and r["input"]["welded"] is True]
    guard("welded coastal railing offers 316L and drops 316",
          bool(goa_w) and all("316L" in r["survivors"] and "316" not in r["survivors"] for r in goa_w))
    guard("only the deliberate furnace case escalates", apps_without_grade == ["furnace_liner"])
    print("PARITY PASSED" if ok else "PARITY FAILED")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
