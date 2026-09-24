/**
 * The console, and the ablation table it sits under.
 *
 * Two rules govern everything here.
 *
 * Nothing in this file decides anything. The lattice, the rules and the join
 * live on the server; this asks and renders. A second implementation in the
 * browser could disagree with the one the evaluation measured, and a demo that
 * disagrees with its own results is worse than no demo.
 *
 * Every string that reaches the DOM goes through textContent, never innerHTML.
 * Half the payloads rendered on this page are attack text written to be
 * interpreted by whatever reads it — rendering them as markup is the same
 * mistake the gateway exists to stop, made on the page that claims to stop it.
 */

const CLASS_LABEL = {
  O1: "instruction injection",
  O2: "authority spoofing",
  O3: "payee substitution",
  O4: "exfiltration lure",
  I1: "mandate violation",
  I2: "economic abuse",
  I3: "mandate replay",
  I4: "velocity abuse",
};

const CLASS_ORDER = ["O3", "I1", "I2", "I3", "I4", "O1", "O2", "O4"];
const SEMANTIC = new Set(["O1", "O2", "O4"]);

const $ = (id) => document.getElementById(id);

/** Set text safely. See the note at the top of this file. */
function text(node, value) {
  node.textContent = value === null || value === undefined ? "" : String(value);
  return node;
}

function el(tag, className, content) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (content !== undefined) text(node, content);
  return node;
}

/** A rate as "6.7% (1/15)", or "not measured" when nothing was. */
function rate(cell) {
  if (!cell || cell.denominator === 0 || cell.percent === null) {
    return { label: "not measured", value: null };
  }
  return {
    label: `${cell.percent}% (${cell.numerator}/${cell.denominator})`,
    value: cell.percent,
  };
}

function rateCell(cell) {
  const { label, value } = rate(cell);
  const td = el("td", null, label);
  if (value === null) td.className = "na";
  else if (value === 0) td.className = "zero";
  else if (value >= 50) td.className = "high";
  return td;
}

// ---------------------------------------------------------------- the table

function renderAblation(results) {
  const body = $("ablation-body");
  body.replaceChildren();

  const configs = results.configs;
  const mock = results.semantic_numbers_are_reportable === false;
  if (mock) {
    // The reason comes from the run, not from this page. A run that used the
    // fake and a run in which the real model never answered are both
    // unreportable, for different reasons, and the page must not guess which.
    const reason = results.not_reportable_because;
    text(
      $("mock-reason"),
      reason ? `They were ${reason}.` : "The run did not measure Layer 2."
    );
    $("mock-banner").hidden = false;
  }

  for (const name of CLASS_ORDER) {
    const row = el("tr");
    const label = SEMANTIC.has(name) && mock ? `${name} *` : name;
    row.append(el("td", "mono", label));
    row.append(el("td", "cite", CLASS_LABEL[name] || ""));
    for (const config of ["C0", "C1", "C2"]) {
      row.append(rateCell(configs[config]?.asr_by_class?.[name]));
    }
    body.append(row);
  }

  const foot = $("ablation-foot");
  foot.replaceChildren();
  const total = el("tr");
  total.append(el("td", null, "all"));
  total.append(el("td", "cite", "120 attacks"));
  for (const config of ["C0", "C1", "C2"]) {
    total.append(rateCell(configs[config]?.asr_overall));
  }
  foot.append(total);

  const fbr = ["C0", "C1", "C2"]
    .map((c) => `${c} ${rate(configs[c]?.false_block_rate).label}`)
    .join("   ·   ");
  text(
    $("fbr-line"),
    `False block rate over 60 benign flows, 30 of them written to look like attacks:   ${fbr}. ` +
      `A REVIEW counts — a genuine order sent to a human queue is delayed revenue.`
  );

  const c1 = configs.C1?.payment_path_ms;
  const c2 = configs.C2?.payment_path_ms;
  const content = configs.C2?.content_path_ms;
  const cache = results.cache;
  if (c1 && c2) {
    text(
      $("latency-line"),
      `Payment-path p95: C1 ${c1.p95?.toFixed(3)} ms, C2 ${c2.p95?.toFixed(3)} ms. ` +
        `Content-path p95 ${content?.p95?.toFixed(3)} ms, paid once per version of the text, not per purchase — ` +
        `${cache?.hits} cache hits to ${cache?.misses} misses, and ${cache?.misses} is exactly the number of distinct texts in the corpus.`
    );
  }
}

function renderPredictions(results) {
  const list = $("preds");
  list.replaceChildren();

  for (const prediction of results.predictions || []) {
    const item = el("li");
    const failed = prediction.outcome === "FAILED";
    item.append(
      el("span", failed ? "failed" : "held", `${prediction.id} ${prediction.outcome}`)
    );
    item.append(el("span", null, ` — ${prediction.statement}`));
    if (failed) {
      item.append(el("span", "why", prediction.on_failure));
    }
    list.append(item);
  }
}

// -------------------------------------------------------------- the console

function renderCases(cases) {
  const select = $("case");
  select.replaceChildren();

  const byClass = new Map();
  for (const item of cases) {
    if (!byClass.has(item.attack_class)) byClass.set(item.attack_class, []);
    byClass.get(item.attack_class).push(item);
  }

  for (const name of [...CLASS_ORDER, "benign"]) {
    const group = byClass.get(name);
    if (!group) continue;

    const optgroup = document.createElement("optgroup");
    optgroup.label =
      name === "benign"
        ? "benign flows — these should be allowed"
        : `${name} — ${CLASS_LABEL[name] || ""}`;

    for (const item of group) {
      const option = document.createElement("option");
      option.value = item.id;
      // Summaries are repository content, but they are rendered next to
      // attack text, so they take the same path as everything else.
      text(option, `${item.id} · ${item.summary}`);
      optgroup.append(option);
    }
    select.append(optgroup);
  }

  select.value = "O3-01";
}

function selectedConfig() {
  const checked = document.querySelector('input[name="config"]:checked');
  return checked ? checked.value : "C2";
}

function renderVerdict(data) {
  const box = $("verdict");
  box.className = `verdict verdict-${data.decision}`;
  box.replaceChildren();
  box.append(el("span", null, data.decision));

  const detail =
    data.stopped_by === "layer1"
      ? "stopped by Layer 1 — deterministic, no model consulted"
      : data.stopped_by === "layer2"
        ? "stopped by Layer 2 — semantic screening of the item text"
        : data.config === "C0"
          ? "no guardrail: the request is executed as submitted"
          : "no rule objected";
  box.append(el("span", "by", detail));
}

function renderScreening(data) {
  const host = $("screening");
  host.replaceChildren();
  if (!data.screening) return;

  const parts = [`Layer 2: ${data.screening.decision}`];
  if (data.screening.classes.length) {
    parts.push(`cited ${data.screening.classes.join(", ")}`);
  }
  parts.push(data.screening.reason);
  if (data.screener_is_mock) {
    parts.push(
      `verdict from ${data.screener}, a nine-phrase substring matcher — not a model`
    );
  }
  host.append(el("p", "cite", parts.join(" · ")));
}

function renderFindings(data) {
  const list = $("findings");
  list.replaceChildren();

  if (!data.findings.length) {
    list.append(el("li", "cite", "No rules were consulted."));
    return;
  }

  for (const finding of data.findings) {
    const fired = finding.decision !== "ALLOW";
    const item = el("li", fired ? "fired" : null);
    item.append(el("span", `tag tag-${finding.decision}`, finding.decision));

    const right = el("div");
    right.append(el("div", "rid", finding.rule_id));
    right.append(el("div", "reason", finding.reason));
    item.append(right);
    list.append(item);
  }
}

const rupees = (paise) =>
  `₹${(paise / 100).toLocaleString("en-IN", { minimumFractionDigits: 2 })}`;

function renderFacts(data) {
  const list = $("facts");
  list.replaceChildren();
  const request = data.request;

  const payeeMatches = request.payee_id === request.registered_payee_id;
  const rows = [
    ["payee requested", request.payee_id, !payeeMatches],
    ["payee registered", request.registered_payee_id, false],
    ["quoted total", rupees(request.quoted_total_paise), false],
    ["mandate ceiling", rupees(request.mandate_ceiling_paise), false],
    ["item category", request.item_category, false],
    ["mandate allows", request.mandate_categories.join(", "), false],
    [
      "line",
      request.lines
        .map((l) => `${l.quantity} × ${rupees(l.unit_price_paise)}`)
        .join(", "),
      false,
    ],
    ["catalog price", rupees(request.item_price_paise), false],
    ["prior decisions", String(request.prior_decisions), false],
  ];

  for (const [key, value, flag] of rows) {
    list.append(el("dt", null, key));
    list.append(el("dd", flag ? "mismatch" : null, value));
  }

  text(
    $("untrusted"),
    `untrusted item text —\n${data.request.item_title}\n\n${data.request.item_description}`
  );
}

async function evaluate() {
  const button = $("run");
  const error = $("error");
  button.disabled = true;
  error.hidden = true;

  const custom = $("text").value.trim();
  const body = custom
    ? { delta: { item_description: custom }, config: selectedConfig() }
    : { case_id: $("case").value, config: selectedConfig() };

  try {
    const response = await fetch("/api/evaluate", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(body),
    });

    const data = await response.json();
    if (!response.ok) {
      throw new Error(
        typeof data.detail === "string" ? data.detail : "the request was refused"
      );
    }

    renderVerdict(data);
    renderScreening(data);
    renderFindings(data);
    renderFacts(data);
    $("result").hidden = false;
  } catch (failure) {
    $("result").hidden = true;
    text(error, `Could not evaluate: ${failure.message}`);
    error.hidden = false;
  } finally {
    button.disabled = false;
  }
}

async function load(path) {
  const response = await fetch(path);
  if (!response.ok) throw new Error(`${path} returned ${response.status}`);
  return response.json();
}

function renderMode(mode) {
  if (!mode || !mode.is_mock) return;
  const host = $("mode");
  host.replaceChildren();
  host.append(el("strong", null, "Layer 2 is stubbed in this deployment. "));
  host.append(el("span", null, mode.note.replace(/^Layer 2 is stubbed[^.]*\. /, "")));
  host.hidden = false;
}

async function start() {
  // The results file is static and served from the CDN, so the table renders
  // without waking a Python process. Only the console below needs the app.
  try {
    const results = await load("/results.json");
    renderAblation(results);
    renderPredictions(results);
  } catch (failure) {
    const row = el("tr");
    const cell = el("td", "na", "results are unavailable");
    cell.colSpan = 5;
    row.append(cell);
    $("ablation-body").replaceChildren(row);
  }

  try {
    const { cases } = await load("/api/corpus");
    renderCases(cases);
  } catch (failure) {
    $("case").replaceChildren(el("option", null, "corpus unavailable"));
  }

  // Stated before the first verdict rather than after it. An O1 case coming
  // back ALLOW should read as "Layer 2 is not running here", which is true,
  // rather than as "the gateway missed it", which is not.
  try {
    const { screener } = await load("/api/rules");
    renderMode(screener);
  } catch (failure) {
    /* The panel still works; it just cannot caption itself. */
  }

  $("run").addEventListener("click", evaluate);
}

start();
