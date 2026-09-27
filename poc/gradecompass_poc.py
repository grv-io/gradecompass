"""
GradeCompass Proof-of-Concept Engine
=====================================
A runnable, self-contained implementation of the three-layer recommendation
cascade described in proposed_solution.md:

    Layer 1: Environment Decoder   (location -> ISO 9223 corrosivity category)
    Layer 2: Failure-Mode Eliminator (category + application -> surviving grades)
    Layer 3: Trade-Off Ranker      (application-weighted scoring + Pareto frontier)

Scope of the PoC (deliberately reduced, per validation_and_feasibility.md #2):
    - 12 grades (vs 120+ in production)  - properties from published typical
      values (IMOA / worldstainless / ASTM A240 ranges)
    - 12 districts (vs ~740 in production) - simplified ISO 9223 rule set
      standing in for the full IMD/CSIR-CECRI/CPCB data pipeline
    - 7 applications (6 domains + a deliberate no-match edge case)

Parity: solution/poc/parity_test.py runs all 7 x 12 x 3 x 3 = 756 input
combinations through this file and the JavaScript port and asserts identical
payloads.

Run:  python gradecompass_poc.py
No dependencies beyond the Python 3 standard library.

API surface: recommend(app_key, district, cost_sensitivity, welded,
service_temp) returns one JSON-serializable dict per query -- the payload the
production FastAPI endpoint serves and the frontend binds to. The console
demo (run_scenario / print_result) is a thin presentation wrapper over it.
"""

import time

# ---------------------------------------------------------------------------
# DATA LAYER (PoC subset)
# ---------------------------------------------------------------------------
# PREN = %Cr + 3.3*%Mo + 16*%N, evaluated at nominal (mid-range) ASTM A240
# composition and cross-checked against the IMOA/ISSF PREN table (Module 5):
# 430 16-18, 304 17.5-20.8, 316 23.1-28.5, 2205 30.8-38.1, 904L 32.2-39.9.
# NOTE: "202" here is ASTM A240 S20200 (Cr 17-19, N <= 0.25 -> PREN ~18-20);
# Indian Cr-Mn utensil variants with lower Cr (e.g. J4-type, ~15-16% Cr) sit
# lower and must be entered per Jindal MTC in production.
# ys = yield strength (MPa, ASTM A240 minimum; 409 = S40910/20/30 at 170 MPa,
# the legacy S40900 205 MPa row no longer exists in A240).
# cost_index is relative to 430 = 1.00 (indicative Indian ex-mill ordering;
# stockist quotes for thinly traded grades such as 2205 run higher -- see
# validation_and_feasibility.md #2.6 price sensitivity).
# form/weld are 1-5 application-engineering ratings.
# max_temp = conservative oxidation limit in deg C = the LOWER of the commonly
# published continuous / intermittent figures (304/316: 870 intermittent, 925
# continuous; 430: 815/870; 409: 675/815; 310: 1035/1150). Duplex capped ~300C (ASME limit
# 316C; 475C embrittlement). 439: 815 (lower of published 815 / Atlas 870 continuous); 904L approximate.

GRADES = {
    "409":  dict(family="ferritic",   pren=10.5, ys=170, cost=0.90, form=3, weld=3, max_temp=675,  mo=0.0, l_grade=False, stabilized=True,
                 tags={"exhaust"}),
    "430":  dict(family="ferritic",   pren=16.5, ys=205, cost=1.00, form=3, weld=2, max_temp=815,  mo=0.0, l_grade=False, stabilized=False,
                 tags={"interior", "appliance", "kitchen_panel"}),
    "439":  dict(family="ferritic",   pren=17.5, ys=205, cost=1.05, form=3, weld=3, max_temp=815,  mo=0.0, l_grade=False, stabilized=True,
                 tags={"exhaust"}),
    "202":  dict(family="austenitic200", pren=18.0, ys=260, cost=1.10, form=4, weld=3, max_temp=815, mo=0.0, l_grade=False, stabilized=False,
                 tags={"utensil_bis", "furniture", "interior"}),
    "304":  dict(family="austenitic300", pren=19.0, ys=205, cost=1.30, form=5, weld=4, max_temp=870, mo=0.0, l_grade=False, stabilized=False,
                 tags={"utensil_bis", "railing", "interior", "railway_rdso", "food_processing", "facade"}),
    "304L": dict(family="austenitic300", pren=19.0, ys=170, cost=1.35, form=5, weld=5, max_temp=870, mo=0.0, l_grade=True, stabilized=False,
                 tags={"food_processing", "water_treatment", "railing", "railway_rdso"}),
    "316":  dict(family="austenitic300", pren=24.5, ys=205, cost=1.60, form=4, weld=4, max_temp=870, mo=2.1, l_grade=False, stabilized=False,
                 tags={"railing", "facade", "food_processing", "marine", "railway_rdso"}),
    "316L": dict(family="austenitic300", pren=24.0, ys=170, cost=1.65, form=4, weld=5, max_temp=870, mo=2.1, l_grade=True, stabilized=False,
                 tags={"railing", "facade", "water_treatment", "food_processing", "pharma", "marine", "electrolyzer"}),
    "321":  dict(family="austenitic300", pren=18.5, ys=205, cost=2.10, form=4, weld=5, max_temp=870, mo=0.0, l_grade=False, stabilized=True,
                 tags={"high_temp"}),
    "310":  dict(family="austenitic300", pren=25.0, ys=205, cost=2.50, form=3, weld=4, max_temp=1035, mo=0.0, l_grade=False, stabilized=False,
                 tags={"furnace", "high_temp"}),
    "2205": dict(family="duplex",     pren=35.0, ys=450, cost=1.80, form=2, weld=3, max_temp=300,  mo=3.1, l_grade=True, stabilized=False,
                 tags={"railing", "facade", "marine", "water_treatment", "electrolyzer", "chemical"}),
    "904L": dict(family="super_austenitic", pren=35.5, ys=220, cost=3.00, form=3, weld=4, max_temp=400, mo=4.3, l_grade=True, stabilized=False,
                 tags={"electrolyzer", "chemical", "marine", "water_treatment"}),
}

# Fixed cost-normalisation anchors (cheapest ferritic ~0.9 .. super-austenitic
# ~3.0 on the 430 = 1.0 index). Deliberately NOT derived from the catalogue
# contents: adding or removing a grade must never change the ranking of an
# unrelated query. Cost scores are clamped to [0, 1] outside the anchors.
COST_INDEX_LO = 0.9
COST_INDEX_HI = 3.0
CATALOG_COST_MIN = COST_INDEX_LO   # kept for API compatibility
CATALOG_COST_MAX = COST_INDEX_HI

# District environmental fingerprints (PoC stand-in for the IMD/CECRI/CPCB
# pipeline). coast = approx. km to coastline, rh = approx. mean annual RH %
# (average of IMD 08:30 and 17:30 climatological normals), rain = approx.
# annual normal, mm/yr, so2 in {"low","med","high"}. All values are hand-
# compiled approximations of published climatological normals; the classifier
# is insensitive to them except at the rule boundaries (RH 40/50 %, 700 mm).
# documented = published/reported real-world corrosion observation or
# practitioner field note used for back-testing (indicative, not a citation).
DISTRICTS = {
    "Mumbai (Marine Drive)": dict(coast=0.5,  rh=75, rain=2200, so2="med",
        documented="Severe pitting reported on 304 railings within 18-24 months (field observation); 316 acceptable with cleaning"),
    "Panaji, Goa":           dict(coast=2.0,  rh=78, rain=2900, so2="low",
        documented="Coastal monsoon belt; 304 pits in 2-3 yrs (field observation); 316/duplex specified for exteriors"),
    "Chennai":               dict(coast=3.0,  rh=70, rain=1400, so2="med",
        documented="Aggressive coastal-urban; 316 minimum for seafront exteriors, duplex specified in Chennai-area desalination and coastal plant (industry practice, team note)"),
    "Visakhapatnam":         dict(coast=2.0,  rh=70, rain=1100, so2="high",
        documented="Coastal-industrial (steel plant, port, refinery): chloride plus SO2 -- treated as one of India's more aggressive urban atmospheres (team note)"),
    "Surat":                 dict(coast=15.0, rh=65, rain=1200, so2="med",
        documented="304 adequate but early exterior tarnishing after 5-7 yrs; 316 for premium installs"),
    "Jamshedpur":            dict(coast=175,  rh=65, rain=1400, so2="high",
        documented="Industrial atmospheric corrosion; 304 adequate for most uses; 316L for chemical exposure"),
    "Delhi":                 dict(coast=830, rh=52, rain=790,  so2="med",
        documented="Urban inland; 304 standard for architecture and transit interior fittings"),
    "Pune":                  dict(coast=100,  rh=58, rain=722,  so2="med",
        documented="Inland industrial; standard grades perform well"),
    "Rajkot":                dict(coast=65,   rh=50, rain=650,  so2="low",
        documented="Dry inland; 202-type/304 standard for utensil industry"),
    "Nashik":                dict(coast=115,  rh=52, rain=690,  so2="low",
        documented="Semi-arid inland; 304 and 430 perform well outdoors"),
    "Hisar":                 dict(coast=870, rh=50, rain=450,  so2="low",
        documented="Continental dry (Jindal registered office and Hisar plant); minimal atmospheric corrosion"),
    "Jaipur":                dict(coast=650,  rh=43, rain=600,  so2="low",
        documented="Semi-arid; even 202-type/430 perform well outdoors"),
}

# Ordered corrosivity scale. Each category range maps to
# (hard PREN floor, upper PREN target). A grade below the floor is ELIMINATED;
# a grade between floor and target passes but is flagged MARGINAL.
# Floors are a team synthesis (IMOA selection guidance + EN 1993-1-4 Annex A,
# where 1.4401/316 sits in CRC III and 1.4462/2205 in CRC IV): in C5 marine
# atmospheres 316 remains the usual minimum WITH a warning (floor 24, target
# 30); CX (offshore/splash) needs duplex or better (floor 30, target 35).
CATEGORY_ORDER = ["C1", "C1-C2", "C2", "C2-C3", "C3", "C3-C4", "C4", "C4-C5", "C5", "CX"]
PREN_THRESHOLDS = {
    "C1": (0, 0), "C1-C2": (0, 14), "C2": (14, 14), "C2-C3": (14, 18),
    "C3": (18, 18), "C3-C4": (18, 24), "C4": (24, 24), "C4-C5": (24, 30),
    "C5": (24, 30), "CX": (30, 35),
}

# Application knowledge base: required catalog tag, non-cost weight profile
# (corrosion/environment, formability, strength), and special filters.
#   override  = service pathway that replaces the atmospheric classification
#               (floor, upper target) -- location is then not used.
#   exclude   = {family: reason} hard exclusions on failure-mode grounds.
#   indoor    = sheltered/conditioned interior: two categories milder than the
#               outdoor class (ISO 9223 treats indoor atmospheres separately,
#               typically C1-C2; two steps is the PoC heuristic).
APPLICATIONS = {
    "outdoor_railing":  dict(tag="railing",       profile=(0.6, 0.3, 0.1)),
    # Utensils are used and washed indoors: corrosion is governed by food
    # contact and cleaning, not by the district's outdoor corrosivity.
    "kitchen_utensils": dict(tag="utensil_bis",   profile=(0.4, 0.5, 0.1),
                             override=dict(floor=(16, 18),
                                           label="food-contact service (PREN floor 16, target 18)",
                                           display="food-contact service (washed, indoor) -- atmospheric pathway not applicable")),
    # PEM electrolyser balance-of-plant: acidic DI-water / O2-side piping,
    # 80C, welded. Stack parts (bipolar plates, PTLs) are coated titanium and
    # out of scope for a stainless selector. Duplex is excluded on hydrogen-
    # assisted-fracture grounds (ferrite phase; Sandia H2 Technical Reference).
    # Service medium: high-purity DI water carrying dissolved O2 (anode loop)
    # at 60-80C, trace fluoride from membrane degradation, hydrogen on the
    # cathode side. The selection drivers are metal-ion leaching into the
    # membrane and hydrogen embrittlement -- NOT chloride pitting -- so the
    # PREN floor here is only a stand-in for "Mo-bearing austenitic or
    # better"; production needs medium-specific data (OEM specs, iso-corrosion
    # curves), see assumptions_and_limitations.md L12.
    "pem_electrolyzer": dict(tag="electrolyzer",  profile=(0.7, 0.1, 0.2), chemical=True, welded=True, temp=80,
                             override=dict(floor=(24, 30),
                                           label="chemical service (alloy-content floor: PREN 24, target 30)",
                                           display="chemical (PEM balance-of-plant: high-purity water + O2, 60-80C, H2 side) -- atmospheric pathway overridden"),
                             exclude={"duplex": "hydrogen-assisted fracture risk in the ferrite phase (Sandia H2 Technical Reference); not offered for H2-wetted service"}),
    # internal=True: enclosed internal service (exhaust gas path) -- the
    # atmospheric pitting floor does not apply. This flag was ADDED after the
    # first PoC run wrongly eliminated 409 (the global exhaust standard) on
    # atmospheric PREN grounds -- a knowledge-base gap the test suite caught.
    "auto_exhaust":     dict(tag="exhaust",       profile=(0.6, 0.3, 0.1), temp=650, internal=True),  # cold end (muffler / tailpipe); hot-end manifolds need 439/441 or better
    "cooling_tower":    dict(tag="water_treatment", profile=(0.6, 0.2, 0.2), mic=True, welded=True),
    "metro_interior":   dict(tag="railway_rdso",  profile=(0.3, 0.4, 0.3), indoor=True),
    "furnace_liner":    dict(tag="furnace",       profile=(0.6, 0.1, 0.3), temp=1200),  # deliberate no-match edge case
}

COST_WEIGHT = {"low": 0.15, "medium": 0.35, "high": 0.65}


# ---------------------------------------------------------------------------
# LAYER 1: ENVIRONMENT DECODER
# ---------------------------------------------------------------------------
def classify_environment(district_name):
    """Simplified ISO 9223 classification from the district fingerprint.
    Production version replaces these rules with the full TOW / Cl- deposition /
    SO2 dose-response calculation on IMD + CECRI + CPCB data."""
    d = DISTRICTS[district_name]
    if d["coast"] < 1:
        cat = "C5"
    elif d["coast"] < 5:
        cat = "C4-C5"
    elif d["coast"] < 25:
        cat = "C3-C4" if d["so2"] == "high" else "C3"
    else:  # inland
        if d["rh"] < 40:
            cat = "C1-C2"
        elif d["so2"] == "high":
            cat = "C3-C4"
        elif d["rh"] < 50 or d["rain"] < 700:
            cat = "C2"
        else:
            cat = "C2-C3"
    return cat


def effective_category(cat, indoor):
    """Sheltered/conditioned interior: two steps milder than the outdoor class,
    and never worse than C3 (PoC heuristic; ISO 9223 classifies indoor
    atmospheres separately, typically C1-C3 even in coastal cities)."""
    if not indoor:
        return cat
    i = CATEGORY_ORDER.index(cat)
    return CATEGORY_ORDER[min(max(0, i - 2), CATEGORY_ORDER.index("C3"))]


# ---------------------------------------------------------------------------
# LAYER 2: FAILURE-MODE ELIMINATOR
# ---------------------------------------------------------------------------
def eliminate(app_key, category, welded, service_temp):
    """Returns (survivors, marginal_flags, elimination_log).
    CONSERVATIVE RESOLUTION RULE: for a range category (e.g. C4-C5) the hard
    floor comes from the LOWER bound and anything below the UPPER bound is
    flagged marginal -- the engine can therefore never pass a grade that fails
    the floor, and ambiguity always resolves toward a warning, never silence."""
    app = APPLICATIONS[app_key]
    if app.get("override"):        # service pathway replaces the atmospheric class
        hard, upper = app["override"]["floor"]
    elif app.get("internal"):      # enclosed internal service: no atmospheric floor
        hard, upper = (0, 0)
    else:
        hard, upper = PREN_THRESHOLDS[category]
    survivors, marginal, log = [], {}, []

    for name, g in GRADES.items():
        # Application relevance filter (curated knowledge base)
        if app["tag"] not in g["tags"]:
            continue
        # Failure-mode family exclusions (e.g. hydrogen embrittlement)
        if app.get("exclude") and g["family"] in app["exclude"]:
            log.append(f"  x {name} eliminated: {app['exclude'][g['family']]}")
            continue
        # Pitting / general corrosion floor
        if g["pren"] < hard:
            log.append(f"  x {name} eliminated: PREN {g['pren']} < floor {hard} for {category}")
            continue
        # Oxidation / max service temperature
        if service_temp and g["max_temp"] < service_temp:
            log.append(f"  x {name} eliminated: max service temp {g['max_temp']}C < required {service_temp}C")
            continue
        # Sensitization: welded austenitic non-L, non-stabilized. Eliminated in
        # >= C4 service; flagged MARGINAL in C3-C4 (thin sheet cools fast enough
        # that sensitization is often negligible, but the engine cannot see
        # section thickness or heat input, so it warns rather than assumes).
        weld_caution = False
        if (welded and g["family"] == "austenitic300" and not g["l_grade"]
                and not g["stabilized"]):
            if hard >= 24:
                log.append(f"  x {name} eliminated: sensitization risk (welded, non-L) in {category}")
                continue
            if hard >= 18:
                weld_caution = True
        # MIC: stagnant-water applications -- Mo-bearing grades give margin,
        # but stagnation control (drain/dry within days) is the primary
        # defence and MIC is recorded in 316L too (Nickel Institute 10085).
        if app.get("mic") and g["mo"] < 2.0:
            log.append(f"  x {name} eliminated: MIC screen (prototype house rule, not a standard threshold): Mo {g['mo']}% < 2%, so not offered for basin service here; "
                       f"treated 304L basins exist in practice, and biocide dosing and stagnation control remain mandatory for any grade")
            continue
        survivors.append(name)
        if g["pren"] < upper:
            marginal[name] = True
            log.append(f"  ! {name} passes but MARGINAL: PREN {g['pren']} < upper target {upper}")
        if weld_caution:
            marginal[name] = True
            log.append(f"  ! {name} passes but MARGINAL: weld sensitization risk (non-L, welded) in {category} "
                       f"-- specify the L-grade or verify thin section / low heat input")
    return survivors, marginal, log, hard, upper


# ---------------------------------------------------------------------------
# LAYER 3: TRADE-OFF RANKER + PARETO FRONTIER
# ---------------------------------------------------------------------------
def rank(survivors, marginal, app_key, cost_sensitivity, welded=False):
    """Weighted additive score over the SURVIVORS only (this is a plain
    weighted sum with a Pareto frontier alongside -- not TOPSIS; see
    proposed_solution.md #6). Corrosion enters as requirement satisfaction
    (1.0, or 0.7 if flagged marginal), never as a maximised property, so the
    ranking cannot 'reward' over-specification. When the product is welded,
    fabricability is the mean of the formability and weldability ratings."""
    app = APPLICATIONS[app_key]
    w_cost = COST_WEIGHT[cost_sensitivity]
    w_env, w_form, w_str = (p * (1 - w_cost) for p in app["profile"])
    scored = []
    for name in survivors:
        g = GRADES[name]
        cost_score = min(1.0, max(0.0, (COST_INDEX_HI - g["cost"]) / (COST_INDEX_HI - COST_INDEX_LO)))
        env_score = 0.7 if marginal.get(name) else 1.0   # requirement satisfaction, not maximization
        fab = (g["form"] + g["weld"]) / 2.0 if welded else g["form"]
        form_score = fab / 5.0
        str_score = min(1.0, g["ys"] / 500.0)
        total = (w_cost * cost_score + w_env * env_score
                 + w_form * form_score + w_str * str_score)
        scored.append((round(total, 4), name))
    scored.sort(reverse=True)
    return scored


BASE_COST_RS_PER_KG = 175  # illustrative 430-baseline price; production uses Stainless Mart pricing


def service_life_band(name, hard, upper):
    """Indicative YEARS TO FIRST MAJOR INTERVENTION (re-polish / partial
    replacement) from the grade's PREN margin over the environment's upper
    corrosivity target -- not an end-of-life figure: a maintained 316 railing
    can outlast the band, at a maintenance cost the metric does not include.
    This is an ENGINEERING-
    JUDGMENT lookup, not a standards model: ISO 9224 publishes dose-response
    rates only for carbon steel, zinc, copper and aluminium, and no ISO service-
    life model exists for stainless steel. Production calibrates these bands
    against CSIR-CECRI stainless exposure data and Jindal field-failure records.
    Returns (label, midpoint_years)."""
    if upper <= 18:                 # C3 and milder: passing grades are not pitting-life-limited
        return "25+ yrs", 27.5
    margin = GRADES[name]["pren"] - upper
    if margin >= 10:
        return "25+ yrs", 27.5
    if margin >= 5:
        return "20-25 yrs", 22.5
    if margin >= 0:
        return "15-20 yrs", 17.5
    return "8-15 yrs (periodic maintenance)", 11.5


def cost_per_service_year(name, hard, upper):
    """The Rs/kg -> Rs/service-year inversion: material cost divided by
    estimated service life. Often flips which grade is 'cheapest'."""
    band, years = service_life_band(name, hard, upper)
    rs_per_kg = round(GRADES[name]["cost"] * BASE_COST_RS_PER_KG, 2)
    return band, rs_per_kg, round(rs_per_kg / years, 1)


def pareto_frontier(survivors):
    """Non-dominated set on (minimize cost, maximize PREN)."""
    front = []
    for a in survivors:
        ga = GRADES[a]
        dominated = any(
            GRADES[b]["cost"] <= ga["cost"] and GRADES[b]["pren"] >= ga["pren"] and b != a
            and (GRADES[b]["cost"] < ga["cost"] or GRADES[b]["pren"] > ga["pren"])
            for b in survivors)
        if not dominated:
            front.append(a)
    return sorted(front, key=lambda n: GRADES[n]["cost"])


def build_recommendation(ranking, marginal, category):
    """Structured recommendation block (top pick + up to 2 alternatives with
    trade-off deltas). None when nothing survived elimination."""
    if not ranking:
        return None
    top_score, top = ranking[0]
    g = GRADES[top]
    alternatives = []
    for score, alt in ranking[1:3]:
        ga = GRADES[alt]
        alternatives.append(dict(
            grade=alt, score=score,
            cost_delta=round(ga["cost"] - g["cost"], 2),
            pren_delta=round(ga["pren"] - g["pren"], 1)))
    return dict(grade=top, score=top_score, pren=g["pren"], cost_index=g["cost"],
                yield_mpa=g["ys"], formability=g["form"], category=category,
                marginal=top in marginal, alternatives=alternatives)


# ---------------------------------------------------------------------------
# ENGINE ENTRY POINT -- structured result
# ---------------------------------------------------------------------------
def recommend(app_key, district=None, cost_sensitivity="medium",
              welded=None, service_temp=None):
    """Runs the full three-layer cascade and returns ONE JSON-serializable
    dict -- the exact payload the production FastAPI endpoint will serve and
    the frontend (risk dashboard, Pareto chart, economics table) will bind to.
    The engine never prints; all console output lives in print_result()."""
    t0 = time.perf_counter()
    app = APPLICATIONS.get(app_key)
    if app is None:
        raise ValueError(f"unknown application '{app_key}'")
    if not app.get("override") and district not in DISTRICTS:
        raise ValueError(f"unknown district '{district}'")
    if cost_sensitivity not in COST_WEIGHT:
        raise ValueError(f"unknown cost sensitivity '{cost_sensitivity}'")
    welded = app.get("welded", False) if welded is None else (welded is True)
    service_temp = app.get("temp") if service_temp is None else service_temp

    if app.get("override"):
        raw = None
        cat_for_filter = app["override"]["label"]
        cat_display = app["override"]["display"]
    else:
        raw = classify_environment(district)
        cat_for_filter = effective_category(raw, app.get("indoor", False))
        cat_display = raw + (f" -> indoor adjusted to {cat_for_filter}" if app.get("indoor") else "")

    survivors, marginal, log, hard, upper = eliminate(app_key, cat_for_filter, welded, service_temp)
    ranking = rank(survivors, marginal, app_key, cost_sensitivity, welded)
    front = pareto_frontier(survivors)

    economics = None                # None for internal (exhaust) and override (chemical / food-contact)
    if ranking and not app.get("internal") and not app.get("override"):
        economics = []
        for _, name in ranking:
            band, rs_kg, rs_yr = cost_per_service_year(name, hard, upper)
            economics.append(dict(grade=name, life_band=band,
                                  rs_per_kg=rs_kg, rs_per_kg_year=rs_yr))

    result = dict(
        input=dict(app=app_key, location=district, welded=welded,
                   cost_sensitivity=cost_sensitivity, service_temp=service_temp),
        environment=dict(category_raw=raw, category=cat_for_filter,
                         display=cat_display, pren_floor=hard, pren_upper_target=upper),
        elimination_log=log,
        survivors=survivors,
        marginal=sorted(marginal),
        pareto_frontier=front,
        ranking=[dict(grade=name, score=score) for score, name in ranking],
        economics=economics,
        recommendation=build_recommendation(ranking, marginal, cat_for_filter),
    )
    result["engine_ms"] = round((time.perf_counter() - t0) * 1000, 2)
    return result


# ---------------------------------------------------------------------------
# CONSOLE PRESENTATION (thin wrapper over the structured result)
# ---------------------------------------------------------------------------
def explanation_text(result):
    rec = result["recommendation"]
    if rec is None:
        return ("  NO GRADE in the PoC catalog meets all constraints. "
                "-> Edge-case handler: show closest partial matches and escalate "
                "to Jindal technical team with pre-filled context (objective F6).")
    lines = [f"  TOP RECOMMENDATION: {rec['grade']}  (score {rec['score']})"]
    lines.append(f"    Why: PREN {rec['pren']} vs environment {rec['category']}; "
                 f"cost index {rec['cost_index']}x (430=1.0); yield {rec['yield_mpa']} MPa; "
                 f"formability {rec['formability']}/5.")
    if rec["marginal"]:
        lines.append("    CAUTION: marginal for the upper bound of the corrosivity range -- "
                     "recommendation carries an explicit warning + escalation option.")
    for alt in rec["alternatives"]:
        lines.append(f"    Alternative {alt['grade']} (score {alt['score']}): "
                     f"{'+' if alt['cost_delta'] >= 0 else ''}{alt['cost_delta']:.2f}x cost, "
                     f"{'+' if alt['pren_delta'] >= 0 else ''}{alt['pren_delta']:.1f} PREN vs {rec['grade']}.")
    return "\n".join(lines)


def print_result(label, result):
    inp = result["input"]
    print(f"\n=== {label} ===")
    print(f"  Input: app={inp['app']}, location={inp['location'] or 'n/a (service pathway override)'}, "
          f"welded={inp['welded']}, cost_sensitivity={inp['cost_sensitivity']}")
    print(f"  Layer 1 -> corrosivity: {result['environment']['display']}")
    print("  Layer 2 elimination log:")
    log = result["elimination_log"]
    print("\n".join(log) if log else "    (no eliminations)")
    print(f"  Survivors: {result['survivors']}")
    if result["pareto_frontier"]:
        print(f"  Pareto frontier (cost vs PREN): {result['pareto_frontier']}")
    print(f"  Layer 3 ranking: {[(r['grade'], r['score']) for r in result['ranking']]}")
    if result["economics"] is not None:
        print("  Service-life economics (Rs/kg -> Rs per year to first major intervention, the inversion):")
        for row in result["economics"]:
            print(f"    {row['grade']:5} Rs {row['rs_per_kg']:.0f}/kg "
                  f"| first intervention {row['life_band']:32} | ~Rs {row['rs_per_kg_year']}/kg-year")
    print(explanation_text(result))
    print(f"  [engine time: {result['engine_ms']:.2f} ms]")


def run_scenario(label, app_key, district=None, cost_sensitivity="medium",
                 welded=None, service_temp=None):
    result = recommend(app_key, district, cost_sensitivity, welded, service_temp)
    print_result(label, result)
    return result


def main():
    print("GradeCompass PoC -- engine run", time.strftime("%Y-%m-%d"))
    print("=" * 70)
    print("\n--- PART 1: SIX APPLICATION SCENARIOS (validation_and_feasibility.md #2) ---")

    a_med = run_scenario("Scenario A1: Coastal railing, Panaji, Goa (cost: MEDIUM)",
                         "outdoor_railing", "Panaji, Goa", "medium")
    a_high = run_scenario("Scenario A2: Same railing, cost sensitivity HIGH (slider moved)",
                          "outdoor_railing", "Panaji, Goa", "high")
    run_scenario("Scenario B: Kitchen utensils, Rajkot (cost: HIGH)",
                 "kitchen_utensils", "Rajkot", "high")
    run_scenario("Scenario C: PEM electrolyser balance-of-plant piping (chemical service, welded)",
                 "pem_electrolyzer", None, "medium")
    run_scenario("Scenario D: Automotive exhaust, Pune (cost: HIGH)",
                 "auto_exhaust", "Pune", "high")
    run_scenario("Scenario E: Cooling tower basin, Chennai (cost: HIGH)",
                 "cooling_tower", "Chennai", "high")
    run_scenario("Scenario F: Metro coach interior, Delhi (cost: MEDIUM)",
                 "metro_interior", "Delhi", "medium")

    print("\n--- PART 2: EDGE CASE -- NO MATCHING GRADE (objective F6) ---")
    run_scenario("Edge case: furnace liner at 1200C (exceeds every PoC grade)",
                 "furnace_liner", "Delhi", "low")

    print("\n--- PART 3: DETERMINISM CHECK ---")
    r1 = run_scenario("Determinism run 1 (Scenario A repeat)", "outdoor_railing", "Panaji, Goa", "medium")
    r2 = run_scenario("Determinism run 2 (identical input)", "outdoor_railing", "Panaji, Goa", "medium")
    strip_timing = lambda r: {k: v for k, v in r.items() if k != "engine_ms"}
    print(f"\n  Identical outputs on identical inputs: {strip_timing(r1) == strip_timing(r2)}")

    print("\n--- PART 4: ENVIRONMENTAL CLASSIFIER BACK-TEST (12 districts) ---")
    print(f"  {'District':28} {'PoC class':9} Documented real-world observation")
    for name in DISTRICTS:
        print(f"  {name:28} {classify_environment(name):9} {DISTRICTS[name]['documented']}")

    print("\n--- PART 5: SLIDER SENSITIVITY (Scenario A, medium vs high cost) ---")
    print(f"  medium cost sensitivity -> top pick: {a_med['ranking'][0]['grade']}")
    print(f"  high   cost sensitivity -> top pick: {a_high['ranking'][0]['grade']}")
    print("  (Demonstrates the Layer 3 real-time re-ranking behaviour.)")


if __name__ == "__main__":
    main()
