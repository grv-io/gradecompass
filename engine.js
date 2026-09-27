/* GradeCompass engine -- 1:1 JavaScript port of solution/poc/gradecompass_poc.py.
   Returns the same JSON payload shape as the Python recommend() entry point,
   so this file is a stand-in for the production FastAPI endpoint.
   Parity-tested against the Python reference across the full scenario grid. */

const GRADES = {
  "409":  { family: "ferritic",         pren: 10.5, ys: 170, cost: 0.90, form: 3, weld: 3, maxTemp: 675,  mo: 0.0, lGrade: false, stabilized: true,  tags: ["exhaust"] },
  "430":  { family: "ferritic",         pren: 16.5, ys: 205, cost: 1.00, form: 3, weld: 2, maxTemp: 815,  mo: 0.0, lGrade: false, stabilized: false, tags: ["interior", "appliance", "kitchen_panel"] },
  "439":  { family: "ferritic",         pren: 17.5, ys: 205, cost: 1.05, form: 3, weld: 3, maxTemp: 845,  mo: 0.0, lGrade: false, stabilized: true,  tags: ["exhaust"] },
  "202":  { family: "austenitic200",    pren: 18.0, ys: 260, cost: 1.10, form: 4, weld: 3, maxTemp: 815,  mo: 0.0, lGrade: false, stabilized: false, tags: ["utensil_bis", "furniture", "interior"] },
  "304":  { family: "austenitic300",    pren: 19.0, ys: 205, cost: 1.30, form: 5, weld: 4, maxTemp: 870,  mo: 0.0, lGrade: false, stabilized: false, tags: ["utensil_bis", "railing", "interior", "railway_rdso", "food_processing", "facade"] },
  "304L": { family: "austenitic300",    pren: 19.0, ys: 170, cost: 1.35, form: 5, weld: 5, maxTemp: 870,  mo: 0.0, lGrade: true,  stabilized: false, tags: ["food_processing", "water_treatment", "railing", "railway_rdso"] },
  "316":  { family: "austenitic300",    pren: 24.5, ys: 205, cost: 1.60, form: 4, weld: 4, maxTemp: 870,  mo: 2.1, lGrade: false, stabilized: false, tags: ["railing", "facade", "food_processing", "marine", "railway_rdso"] },
  "316L": { family: "austenitic300",    pren: 24.0, ys: 170, cost: 1.65, form: 4, weld: 5, maxTemp: 870,  mo: 2.1, lGrade: true,  stabilized: false, tags: ["railing", "facade", "water_treatment", "food_processing", "pharma", "marine", "electrolyzer"] },
  "321":  { family: "austenitic300",    pren: 18.5, ys: 205, cost: 2.10, form: 4, weld: 5, maxTemp: 870,  mo: 0.0, lGrade: false, stabilized: true,  tags: ["high_temp"] },
  "310":  { family: "austenitic300",    pren: 25.0, ys: 205, cost: 2.50, form: 3, weld: 4, maxTemp: 1035, mo: 0.0, lGrade: false, stabilized: false, tags: ["furnace", "high_temp"] },
  "2205": { family: "duplex",           pren: 35.0, ys: 450, cost: 1.80, form: 2, weld: 3, maxTemp: 300,  mo: 3.1, lGrade: true,  stabilized: false, tags: ["railing", "facade", "marine", "water_treatment", "electrolyzer", "chemical"] },
  "904L": { family: "super_austenitic", pren: 35.5, ys: 220, cost: 3.00, form: 3, weld: 4, maxTemp: 400,  mo: 4.3, lGrade: true,  stabilized: false, tags: ["electrolyzer", "chemical", "marine", "water_treatment"] },
};

// JS objects re-sort integer-like keys ("2205" before "316L"), so catalog
// iteration order must be pinned explicitly to match the Python reference.
const GRADE_ORDER = ["409", "430", "439", "202", "304", "304L", "316", "316L", "321", "310", "2205", "904L"];

// Fixed cost-normalisation anchors (not derived from the catalogue: adding a grade
// must never change the ranking of an unrelated query). Clamped to [0, 1].
const COST_INDEX_LO = 0.9, COST_INDEX_HI = 3.0;
const CATALOG_COST_MIN = COST_INDEX_LO, CATALOG_COST_MAX = COST_INDEX_HI;

const DISTRICTS = {
  "Mumbai (Marine Drive)": { coast: 0.5,  rh: 75, rain: 2200, so2: "med",
    documented: "Severe pitting reported on 304 railings within 18-24 months (field observation); 316 acceptable with cleaning" },
  "Panaji, Goa":           { coast: 2.0,  rh: 78, rain: 2900, so2: "low",
    documented: "Coastal monsoon belt; 304 pits in 2-3 yrs (field observation); 316/duplex specified for exteriors" },
  "Chennai":               { coast: 3.0,  rh: 70, rain: 1400, so2: "med",
    documented: "Aggressive coastal-urban; 316 minimum for seafront exteriors, duplex specified in Chennai-area desalination and coastal plant (industry practice, team note)" },
  "Visakhapatnam":         { coast: 2.0,  rh: 70, rain: 1100, so2: "high",
    documented: "Coastal-industrial (steel plant, port, refinery): chloride plus SO2 -- treated as one of India's more aggressive urban atmospheres (team note)" },
  "Surat":                 { coast: 15.0, rh: 65, rain: 1200, so2: "med",
    documented: "304 adequate but early exterior tarnishing after 5-7 yrs; 316 for premium installs" },
  "Jamshedpur":            { coast: 175,  rh: 65, rain: 1400, so2: "high",
    documented: "Industrial atmospheric corrosion; 304 adequate for most uses; 316L for chemical exposure" },
  "Delhi":                 { coast: 830, rh: 52, rain: 790,  so2: "med",
    documented: "Urban inland; 304 standard for architecture and transit interior fittings" },
  "Pune":                  { coast: 100,  rh: 58, rain: 722,  so2: "med",
    documented: "Inland industrial; standard grades perform well" },
  "Rajkot":                { coast: 65,   rh: 50, rain: 650,  so2: "low",
    documented: "Dry inland; 202-type/304 standard for utensil industry" },
  "Nashik":                { coast: 115,  rh: 52, rain: 690,  so2: "low",
    documented: "Semi-arid inland; 304 and 430 perform well outdoors" },
  "Hisar":                 { coast: 870, rh: 50, rain: 450,  so2: "low",
    documented: "Continental dry (Jindal registered office and Hisar plant); minimal atmospheric corrosion" },
  "Jaipur":                { coast: 650,  rh: 43, rain: 600,  so2: "low",
    documented: "Semi-arid; even 202-type/430 perform well outdoors" },
};

const CATEGORY_ORDER = ["C1", "C1-C2", "C2", "C2-C3", "C3", "C3-C4", "C4", "C4-C5", "C5", "CX"];
const PREN_THRESHOLDS = {
  "C1": [0, 0], "C1-C2": [0, 14], "C2": [14, 14], "C2-C3": [14, 18],
  "C3": [18, 18], "C3-C4": [18, 24], "C4": [24, 24], "C4-C5": [24, 30],
  "C5": [24, 30], "CX": [30, 35],
};

const APPLICATIONS = {
  outdoor_railing:  { tag: "railing",         profile: [0.6, 0.3, 0.1] },
  kitchen_utensils: { tag: "utensil_bis",     profile: [0.4, 0.5, 0.1],
                      override: { floor: [16, 18], label: "food-contact service (PREN floor 16, target 18)",
                                  display: "food-contact service (washed, indoor) -- atmospheric pathway not applicable" } },
  pem_electrolyzer: { tag: "electrolyzer",    profile: [0.7, 0.1, 0.2], chemical: true, welded: true, temp: 80,
                      override: { floor: [24, 30], label: "chemical service (alloy-content floor: PREN 24, target 30)",
                                  display: "chemical (PEM balance-of-plant: high-purity water + O2, 80C, H2 side) -- atmospheric pathway overridden" },
                      exclude: { duplex: "hydrogen-assisted fracture risk in the ferrite phase (Sandia H2 Technical Reference); not offered for H2-wetted service" } },
  auto_exhaust:     { tag: "exhaust",         profile: [0.6, 0.3, 0.1], temp: 650, internal: true },  // cold end (muffler / tailpipe)
  cooling_tower:    { tag: "water_treatment", profile: [0.6, 0.2, 0.2], mic: true, welded: true },
  metro_interior:   { tag: "railway_rdso",    profile: [0.3, 0.4, 0.3], indoor: true },
  furnace_liner:    { tag: "furnace",         profile: [0.6, 0.1, 0.3], temp: 1200 },
};

const COST_WEIGHT = { low: 0.15, medium: 0.35, high: 0.65 };
const BASE_COST_RS_PER_KG = 175;

// Decimal rounding of the exact binary value (matches Python's round()
// everywhere a true tie doesn't occur, and ties are non-representable here).
const round = (x, d) => parseFloat(x.toFixed(d));

/* ----- Layer 1: environment decoder ----- */
function classifyEnvironment(districtName) {
  const d = DISTRICTS[districtName];
  if (d.coast < 1) return "C5";
  if (d.coast < 5) return "C4-C5";
  if (d.coast < 25) return d.so2 === "high" ? "C3-C4" : "C3";
  if (d.rh < 40) return "C1-C2";
  if (d.so2 === "high") return "C3-C4";
  if (d.rh < 50 || d.rain < 700) return "C2";
  return "C2-C3";
}

function effectiveCategory(cat, indoor) {
  if (!indoor) return cat;
  const i = CATEGORY_ORDER.indexOf(cat);
  return CATEGORY_ORDER[Math.min(Math.max(0, i - 2), CATEGORY_ORDER.indexOf("C3"))];
}

/* ----- Layer 2: failure-mode eliminator ----- */
function eliminate(appKey, category, welded, serviceTemp) {
  const app = APPLICATIONS[appKey];
  let hard, upper;
  if (app.override) [hard, upper] = app.override.floor;
  else if (app.internal) { hard = 0; upper = 0; }
  else [hard, upper] = PREN_THRESHOLDS[category];

  const survivors = [], marginal = {}, log = [];
  for (const name of GRADE_ORDER) {
    const g = GRADES[name];
    if (!g.tags.includes(app.tag)) continue;
    if (app.exclude && app.exclude[g.family]) {
      log.push(`  x ${name} eliminated: ${app.exclude[g.family]}`);
      continue;
    }
    if (g.pren < hard) {
      log.push(`  x ${name} eliminated: PREN ${g.pren.toFixed(1)} < floor ${hard} for ${category}`);
      continue;
    }
    if (serviceTemp && g.maxTemp < serviceTemp) {
      log.push(`  x ${name} eliminated: max service temp ${g.maxTemp}C < required ${serviceTemp}C`);
      continue;
    }
    let weldCaution = false;
      if (welded && g.family === "austenitic300" && !g.lGrade && !g.stabilized) {
        if (hard >= 24) {
          log.push(`  x ${name} eliminated: sensitization risk (welded, non-L) in ${category}`);
          continue;
        }
        if (hard >= 18) weldCaution = true;
      }
    if (app.mic && g.mo < 2.0) {
      log.push(`  x ${name} eliminated: MIC risk in stagnant water: Mo-free grade (Mo ${g.mo.toFixed(1)}% < 2%) not offered; Mo-bearing grades resist MIC better, but biocide dosing and stagnation control remain mandatory for any grade`);
      continue;
    }
    survivors.push(name);
    if (g.pren < upper) {
      marginal[name] = true;
      log.push(`  ! ${name} passes but MARGINAL: PREN ${g.pren.toFixed(1)} < upper target ${upper}`);
    }
    if (weldCaution) {
      marginal[name] = true;
      log.push(`  ! ${name} passes but MARGINAL: weld sensitization risk (non-L, welded) in ${category} -- specify the L-grade or verify thin section / low heat input`);
    }
  }
  return { survivors, marginal, log, hard, upper };
}

/* ----- Layer 3: trade-off ranker + Pareto frontier ----- */
function rank(survivors, marginal, appKey, costSensitivity, welded = false) {
  const app = APPLICATIONS[appKey];
  const wCost = COST_WEIGHT[costSensitivity];
  const [wEnv, wForm, wStr] = app.profile.map((p) => p * (1 - wCost));
  const scored = survivors.map((name) => {
    const g = GRADES[name];
    const costScore = Math.min(1.0, Math.max(0.0, (COST_INDEX_HI - g.cost) / (COST_INDEX_HI - COST_INDEX_LO)));
    const envScore = marginal[name] ? 0.7 : 1.0;
    const fab = welded ? (g.form + g.weld) / 2.0 : g.form;
    const formScore = fab / 5.0;
    const strScore = Math.min(1.0, g.ys / 500.0);
    const total = wCost * costScore + wEnv * envScore + wForm * formScore + wStr * strScore;
    return { score: round(total, 4), name };
  });
  // Matches Python's reverse tuple sort: score desc, then name desc on ties.
  scored.sort((a, b) => b.score - a.score || (b.name < a.name ? -1 : b.name > a.name ? 1 : 0));
  return scored;
}

function serviceLifeBand(name, upper) {
  if (upper <= 18) return ["25+ yrs", 27.5];   // C3 and milder: passing grades are not pitting-life-limited
  const margin = GRADES[name].pren - upper;
  if (margin >= 10) return ["25+ yrs", 27.5];
  if (margin >= 5) return ["20-25 yrs", 22.5];
  if (margin >= 0) return ["15-20 yrs", 17.5];
  return ["8-15 yrs (periodic maintenance)", 11.5];
}

function costPerServiceYear(name, upper) {
  const [band, years] = serviceLifeBand(name, upper);
  const rsPerKg = round(GRADES[name].cost * BASE_COST_RS_PER_KG, 2);
  return { band, rsPerKg, rsPerYear: round(rsPerKg / years, 1) };
}

function paretoFrontier(survivors) {
  const front = survivors.filter((a) => {
    const ga = GRADES[a];
    return !survivors.some((b) => {
      const gb = GRADES[b];
      return b !== a && gb.cost <= ga.cost && gb.pren >= ga.pren
        && (gb.cost < ga.cost || gb.pren > ga.pren);
    });
  });
  return front.sort((x, y) => GRADES[x].cost - GRADES[y].cost);
}

function buildRecommendation(ranking, marginal, category) {
  if (!ranking.length) return null;
  const { score: topScore, name: top } = ranking[0];
  const g = GRADES[top];
  const alternatives = ranking.slice(1, 3).map(({ score, name }) => {
    const ga = GRADES[name];
    return {
      grade: name, score,
      cost_delta: round(ga.cost - g.cost, 2),
      pren_delta: round(ga.pren - g.pren, 1),
    };
  });
  return {
    grade: top, score: topScore, pren: g.pren, cost_index: g.cost,
    yield_mpa: g.ys, formability: g.form, category,
    marginal: Boolean(marginal[top]), alternatives,
  };
}

/* ----- Engine entry point: same payload shape as the Python recommend() ----- */
function recommend(appKey, district = null, costSensitivity = "medium",
                   welded = null, serviceTemp = null) {
  const t0 = (typeof performance !== "undefined" ? performance : Date).now();
  const app = APPLICATIONS[appKey];
  if (!app) throw new Error(`unknown application '${appKey}'`);
  if (!app.override && !DISTRICTS[district]) throw new Error(`unknown district '${district}'`);
  if (!(costSensitivity in COST_WEIGHT)) throw new Error(`unknown cost sensitivity '${costSensitivity}'`);
  welded = (welded === null || welded === undefined) ? Boolean(app.welded) : welded === true;
  if (serviceTemp === null) serviceTemp = app.temp ?? null;

  let raw, catForFilter, catDisplay;
  if (app.override) {
    raw = null;
    catForFilter = app.override.label;
    catDisplay = app.override.display;
  } else {
    raw = classifyEnvironment(district);
    catForFilter = effectiveCategory(raw, Boolean(app.indoor));
    catDisplay = raw + (app.indoor ? ` -> indoor adjusted to ${catForFilter}` : "");
  }

  const { survivors, marginal, log, hard, upper } = eliminate(appKey, catForFilter, welded, serviceTemp);
  const ranking = rank(survivors, marginal, appKey, costSensitivity, welded);
  const front = paretoFrontier([...survivors]);

  let economics = null;
  if (ranking.length && !app.internal && !app.override) {   // null for internal (exhaust) and override (chemical / food-contact)
    economics = ranking.map(({ name }) => {
      const { band, rsPerKg, rsPerYear } = costPerServiceYear(name, upper);
      return { grade: name, life_band: band, rs_per_kg: rsPerKg, rs_per_kg_year: rsPerYear };
    });
  }

  const result = {
    input: { app: appKey, location: district, welded, cost_sensitivity: costSensitivity, service_temp: serviceTemp },
    environment: { category_raw: raw, category: catForFilter, display: catDisplay, pren_floor: hard, pren_upper_target: upper },
    elimination_log: log,
    survivors,
    marginal: Object.keys(marginal).sort(),
    pareto_frontier: front,
    ranking: ranking.map(({ name, score }) => ({ grade: name, score })),
    economics,
    recommendation: buildRecommendation(ranking, marginal, catForFilter),
  };
  result.engine_ms = round((typeof performance !== "undefined" ? performance : Date).now() - t0, 2);
  return result;
}

const GradeCompass = {
  GRADES, GRADE_ORDER, DISTRICTS, APPLICATIONS, CATEGORY_ORDER, PREN_THRESHOLDS,
  COST_WEIGHT, BASE_COST_RS_PER_KG, CATALOG_COST_MIN, CATALOG_COST_MAX,
  classifyEnvironment, effectiveCategory, eliminate, rank,
  serviceLifeBand, costPerServiceYear, paretoFrontier, recommend,
};

if (typeof module !== "undefined" && module.exports) module.exports = GradeCompass;
if (typeof window !== "undefined") window.GradeCompass = GradeCompass;
