// Presentation only. Every verdict comes from the server's facts; this file decides nothing.
// Document text is untrusted: it is only ever set with textContent, never parsed as HTML.
"use strict";

const STATUS_LABEL = {
  matched: "Matched",
  partial: "Partly shown",
  gap: "Gap",
  unresolvable: "Ambiguous", // never a conclusion: the keyword pass could not decide
  not_assessed: "Not assessed",
};
const STATUS_ORDER = ["matched", "partial", "gap", "unresolvable", "not_assessed"];
const DECIDED = ["matched", "partial", "gap"];
// Always shown in the summary; the other two statuses only when a result has them.
const CORE_STATUSES = ["matched", "gap", "unresolvable"];
const FILTERS = [
  { key: "all", label: "All", statuses: null },
  { key: "gap", label: "Gaps", statuses: ["gap"], noun: "gaps" },
  { key: "unresolvable", label: "Ambiguous", statuses: ["unresolvable"], noun: "ambiguous skills" },
  { key: "matched", label: "Matched", statuses: ["matched"], noun: "matched skills" },
  { key: "partial", label: "Partly shown", statuses: ["partial"], noun: "partly shown skills", optional: true },
  { key: "not_assessed", label: "Not assessed", statuses: ["not_assessed"], noun: "unassessed skills", optional: true },
];
const ACCEPTED_TYPES = [".pdf", ".txt"]; // the server's own rule (ingest/document.py); it still checks
const LONG_QUOTE = 180; // characters: a longer quote starts clamped to three lines, with a toggle
const REPEAT_QUOTE = 80; // a repeated line longer than this is shown once per view, then referenced

// Usage counts (see /privacy). Only these fields are ever sent, and the server refuses anything else.
const VISITOR_KEY = "careerfit-visitor";
const OPT_OUT_KEY = "careerfit-usage-opt-out";
const TOKEN_RE = /^[A-Za-z0-9._-]{1,64}$/;
const HOST_RE = /^[a-z0-9.-]{1,253}$/;

const $ = (id) => document.getElementById(id);
let downloadUrls = [];
let maxFileMb = 5; // replaced by the server's own limit on load
let limitsReady = Promise.resolve();
let busy = false;
let current = null; // the last result, kept so the filters can re-render it
let activeFilter = "all";
let nextId = 0;

async function loadLimits() {
  try {
    const limits = await (await fetch("/api/limits")).json();
    if (Number.isInteger(limits.max_file_mb)) maxFileMb = limits.max_file_mb;
  } catch {
    // keep the default; the server still enforces its real limit
  }
  document.querySelectorAll(".max-mb").forEach((node) => (node.textContent = String(maxFileMb)));
}

function tooLarge(file) {
  return file && file.size > maxFileMb * 1024 * 1024;
}

function el(tag, text, className) {
  const node = document.createElement(tag);
  if (text !== undefined) node.textContent = text;
  if (className) node.className = className;
  return node;
}

function icon(name, className = "icon") {
  const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  svg.setAttribute("class", className);
  svg.setAttribute("aria-hidden", "true");
  const use = document.createElementNS("http://www.w3.org/2000/svg", "use");
  use.setAttribute("href", `#i-${name}`);
  svg.appendChild(use);
  return svg;
}

function uid(prefix) {
  nextId += 1;
  return `${prefix}-${nextId}`;
}

// ---- usage counts ----

function storageGet(key) {
  try { return window.localStorage.getItem(key); } catch { return null; }
}

function storageSet(key, value) {
  try { window.localStorage.setItem(key, value); } catch { /* private mode: no ID, events go anonymous */ }
}

// "off" after an opt-out on /privacy; "anonymous" (no visitor ID) under Global Privacy Control or Do
// Not Track; otherwise "on": a random ID that only this browser holds.
function trackingMode() {
  if (storageGet(OPT_OUT_KEY) === "1") return "off";
  if (navigator.globalPrivacyControl === true || navigator.doNotTrack === "1") return "anonymous";
  return "on";
}

function visitorId() {
  if (trackingMode() !== "on") return null;
  let id = storageGet(VISITOR_KEY);
  if (!id && window.crypto?.randomUUID) {
    id = window.crypto.randomUUID();
    storageSet(VISITOR_KEY, id);
  }
  return id || null;
}

function track(type, props = {}) {
  if (trackingMode() === "off") return;
  const visitor = visitorId();
  const body = JSON.stringify(visitor ? { type, visitor, props } : { type, props });
  try {
    if (navigator.sendBeacon?.("/api/event", new Blob([body], { type: "application/json" }))) return;
    fetch("/api/event", { method: "POST", body, keepalive: true, headers: { "Content-Type": "application/json" } })
      .catch(() => {});
  } catch {
    // counting must never get in the way of the page
  }
}

function pageViewProps() {
  const props = { path: "/" };
  try {
    const ref = document.referrer ? new URL(document.referrer).hostname.toLowerCase() : "";
    if (ref && ref !== window.location.hostname && HOST_RE.test(ref)) props.ref_host = ref;
  } catch {
    // an unparsable referrer is simply not counted
  }
  const params = new URLSearchParams(window.location.search);
  for (const key of ["utm_source", "utm_medium", "utm_campaign"]) {
    const value = params.get(key);
    if (value && TOKEN_RE.test(value)) props[key] = value;
  }
  return props;
}

function fileType(file) {
  return file.name.toLowerCase().endsWith(".pdf") ? "pdf" : "txt";
}

function announce(message, regionId = "status") {
  // Cleared first, so the same message twice in a row is still read out.
  const region = $(regionId);
  region.textContent = "";
  window.setTimeout(() => (region.textContent = message), 60);
}

// ---- files ----

function formatSize(bytes) {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(bytes < 10 * 1024 ? 1 : 0)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

function fileProblem(file) {
  const name = file.name.toLowerCase();
  if (!ACCEPTED_TYPES.some((type) => name.endsWith(type))) return `${file.name} is not a PDF or TXT file.`;
  if (tooLarge(file)) return `${file.name} is ${formatSize(file.size)}, larger than the ${maxFileMb} MB limit.`;
  return null;
}

function setFieldError(field, control, errorId, message) {
  const error = $(errorId);
  error.textContent = message;
  error.hidden = false;
  control.setAttribute("aria-invalid", "true");
  field.classList.add("has-error");
}

function clearFieldError(field, controls, errorId) {
  const error = $(errorId);
  error.textContent = "";
  error.hidden = true;
  controls.forEach((control) => control.removeAttribute("aria-invalid"));
  field.classList.remove("has-error");
}

function hasFiles(event) {
  return Array.from(event.dataTransfer?.types ?? []).includes("Files");
}

function setupUpload(inputId, errorId) {
  const input = $(inputId);
  const zone = input.closest(".upload");
  const field = input.closest(".field");
  const empty = zone.querySelector(".upload-empty");
  const selected = zone.querySelector(".upload-selected");
  const actions = zone.querySelector(".upload-actions");
  let lastFile = null;

  const refresh = () => {
    const file = input.files[0] ?? null;
    lastFile = file;
    zone.classList.toggle("has-file", Boolean(file));
    empty.hidden = Boolean(file);
    selected.hidden = !file;
    actions.hidden = !file;
    clearFieldError(field, [input], errorId);
    if (!file) return;
    selected.querySelector(".file-name").textContent = file.name;
    selected.querySelector(".file-size").textContent = formatSize(file.size);
    const problem = fileProblem(file);
    if (problem) setFieldError(field, input, errorId, problem);
  };

  const use = (file) => {
    const transfer = new DataTransfer();
    transfer.items.add(file);
    input.files = transfer.files;
  };

  input.addEventListener("change", () => {
    // Some browsers empty the input when the picker is cancelled; keep the file chosen before.
    if (input.files.length === 0 && lastFile) use(lastFile);
    refresh();
  });
  actions.querySelector('[data-action="replace"]').addEventListener("click", () => input.click());
  actions.querySelector('[data-action="remove"]').addEventListener("click", () => {
    input.value = "";
    refresh();
    input.focus();
  });

  let depth = 0;
  zone.addEventListener("dragenter", (event) => {
    if (!hasFiles(event)) return;
    event.preventDefault();
    depth += 1;
    zone.classList.add("is-dragover");
  });
  zone.addEventListener("dragover", (event) => {
    if (!hasFiles(event)) return;
    event.preventDefault();
    event.dataTransfer.dropEffect = "copy";
  });
  zone.addEventListener("dragleave", () => {
    depth = Math.max(0, depth - 1);
    if (depth === 0) zone.classList.remove("is-dragover");
  });
  zone.addEventListener("drop", (event) => {
    event.preventDefault();
    depth = 0;
    zone.classList.remove("is-dragover");
    const file = event.dataTransfer.files[0];
    if (!file) return;
    use(file);
    refresh();
    if (event.dataTransfer.files.length > 1) announce(`Only the first file, ${file.name}, was used.`);
  });
  return refresh;
}

// ---- job description: file or pasted text, never both ----

function jdMode() {
  return document.querySelector('input[name="jd_mode"]:checked').value;
}

function applyJdMode(refreshJd) {
  const mode = jdMode();
  $("jd-file-panel").hidden = mode !== "file";
  $("jd-text-panel").hidden = mode !== "text";
  $("jd").required = mode === "file";
  $("jd_text").required = mode === "text";
  // The other input keeps its content (switching back restores it) but is never sent.
  clearFieldError($("jd").closest(".field"), [$("jd"), $("jd_text")], "jd-error");
  if (mode === "file") refreshJd();
}

// ---- submitting ----

function setBusy(on) {
  busy = on;
  const button = $("submit");
  button.classList.toggle("is-busy", on);
  button.setAttribute("aria-disabled", String(on));
  button.querySelector(".button-label").textContent = on ? "Analysing…" : "Analyse fit";
  // On the button, not the form: a busy ancestor lets screen readers hold back the #status
  // announcement until the request ends.
  button.setAttribute("aria-busy", String(on));
}

function showError(message) {
  $("error").textContent = message;
  $("error").hidden = false;
}

// Returns the first control that needs attention, after marking every problem next to its field.
function validate() {
  const problems = [];
  const resume = $("resume");
  const resumeField = resume.closest(".field");
  const resumeFile = resume.files[0];
  const resumeProblem = resumeFile ? fileProblem(resumeFile) : "Choose a resume file.";
  if (resumeProblem) {
    setFieldError(resumeField, resume, "resume-error", resumeProblem);
    problems.push([resume, resumeProblem]);
  }
  const jdField = $("jd").closest(".field");
  if (jdMode() === "file") {
    const jdFile = $("jd").files[0];
    const jdProblem = jdFile ? fileProblem(jdFile) : "Choose a job description file, or switch to Paste text.";
    if (jdProblem) {
      setFieldError(jdField, $("jd"), "jd-error", jdProblem);
      problems.push([$("jd"), jdProblem]);
    }
  } else if (!$("jd_text").value.trim()) {
    const jdProblem = "Paste the job description, or switch to Upload file.";
    setFieldError(jdField, $("jd_text"), "jd-error", jdProblem);
    problems.push([$("jd_text"), jdProblem]);
  }
  return problems;
}

async function submit(event) {
  event.preventDefault();
  if (busy) return; // one analysis at a time, including while the limits load
  setBusy(true);
  $("error").hidden = true;
  $("result").hidden = true; // a failed run must never leave the previous files' results on screen
  try {
    await limitsReady; // on a cold start the limit lookup may still be in flight
    // Fields are read after the wait, so edits made while it ran are the ones sent.
    const problems = validate();
    if (problems.length) {
      problems[0][0].focus();
      announce(problems.map(([, message]) => message).join(" "));
      return;
    }

    // Only the visible job description input is sent, so a file or text left in the other mode
    // can never override what the user is looking at. The server still requires exactly one.
    const form = new FormData();
    const resumeFile = $("resume").files[0];
    const mode = jdMode();
    form.append("resume", resumeFile);
    if (mode === "file") form.append("jd", $("jd").files[0]);
    else form.append("jd_text", $("jd_text").value.trim());
    const perspective = document.querySelector('input[name="perspective"]:checked').value;
    form.append("perspective", perspective);
    const donate = $("donate_jd").checked;
    if (donate) form.append("donate_jd", "true"); // opt-in only: unticked, nothing about the JD is kept
    const started = performance.now();

    announce("Analysing. This usually takes a few seconds.");
    const response = await fetch("/api/analyze", { method: "POST", body: form });
    const payload = await response.json().catch(() => ({}));
    if (!response.ok) {
      const detail = typeof payload.detail === "string" ? payload.detail
        : response.status === 413 ? `The upload is too large for this server (limit ${maxFileMb} MB per file).`
        : response.status === 429 ? "Too many analyses from this address. Wait a minute and try again."
        : "The server could not read that request.";
      track("analysis_failed", { status: response.status });
      return showError(detail);
    }
    render(payload);
    const facts = payload.facts.skill_observations;
    const count = (status) => facts.filter((o) => o.status === status).length;
    track("analysis_completed", {
      perspective, jd_mode: mode, resume_type: fileType(resumeFile),
      jd_type: mode === "text" ? "pasted" : fileType($("jd").files[0]),
      skills: facts.length, must: facts.filter((o) => o.requirement === "must").length,
      nice: facts.filter((o) => o.requirement === "nice").length,
      matched: count("matched"), gaps: count("gap"), ambiguous: count("unresolvable"),
      ms: Math.min(600000, Math.round(performance.now() - started)), donated: payload.jd_donated ? "yes" : "no",
    });
    const n = payload.facts.skill_observations.length;
    announce(`Analysis ready: ${n} skill${n === 1 ? "" : "s"} from the job description.`);
    $("title").focus();
  } catch {
    track("analysis_failed", { status: 0 });
    showError("Could not reach the careerfit server.");
  } finally {
    setBusy(false);
  }
}

// ---- results ----

function sorted(observations) {
  return [...observations].sort(
    (a, b) => STATUS_ORDER.indexOf(a.status) - STATUS_ORDER.indexOf(b.status) || a.skill.localeCompare(b.skill),
  );
}

function statusBadge(status) {
  const badge = el("span", undefined, `status ${status}`);
  badge.append(icon(status), document.createTextNode(STATUS_LABEL[status] ?? status));
  return badge;
}

function tally(title, observations) {
  const box = el("div", undefined, "tally");
  const head = el("p", undefined, "tally-title");
  head.append(el("span", title), el("span", `${observations.length} skill${observations.length === 1 ? "" : "s"}`, "tally-total"));
  const list = el("ul", undefined, "tally-counts");
  const statuses = STATUS_ORDER.filter(
    (s) => CORE_STATUSES.includes(s) || observations.some((o) => o.status === s),
  );
  for (const status of statuses) {
    const item = el("li", undefined, "tally-count");
    item.append(el("span", String(observations.filter((o) => o.status === status).length), "tally-number"), statusBadge(status));
    list.append(item);
  }
  box.append(head, list);
  return box;
}

function quoteToggle(quote, more, less, mode, describedBy) {
  const button = el("button", more, "text-button quote-toggle");
  button.type = "button";
  button.setAttribute("aria-expanded", "false");
  button.setAttribute("aria-controls", quote.id);
  button.setAttribute("aria-describedby", describedBy);
  button.addEventListener("click", () => {
    const open = button.getAttribute("aria-expanded") !== "true";
    button.setAttribute("aria-expanded", String(open));
    button.textContent = open ? less : more;
    if (mode === "hidden") quote.hidden = !open;
    else quote.classList.toggle("is-clamped", !open);
    if (open) track("expand", { kind: mode === "hidden" ? "repeat" : "clamp" });
  });
  return button;
}

function evidence(ev, doc, observation, seen, skillId) {
  const box = el("div", undefined, "evidence-item");
  const meta = el("p", undefined, "evidence-meta");
  const locator = ev.locator.charAt(0).toUpperCase() + ev.locator.slice(1);
  meta.append(el("span", locator, "locator"));
  // Same wording as the Markdown report: say when a skill is shown through another one.
  if (ev.source === "derived") meta.append(el("span", `shown through ${ev.via}`, "via"));
  box.append(meta);

  const quote = el("p", `“${ev.excerpt}”`, "quote");
  quote.id = uid("quote");
  const key = `${doc}:${ev.locator}`;
  const first = seen.get(key);
  if (first !== undefined && ev.excerpt.length > REPEAT_QUOTE) {
    // Quoted in full on an earlier row of this view: point at it, and keep it one click away.
    meta.append(el("span", `same line as ${first}`, "same-line"));
    quote.hidden = true;
    box.append(quote, quoteToggle(quote, "Show quote", "Hide quote", "hidden", skillId));
    return box;
  }
  if (first === undefined) seen.set(key, observation.skill);
  box.append(quote);
  if (ev.excerpt.length > LONG_QUOTE) {
    quote.classList.add("is-clamped");
    box.append(quoteToggle(quote, "Show full line", "Show less", "clamp", skillId));
  }
  return box;
}

function noEvidence(observation) {
  // Precise per status: only a gap is a confirmed absence.
  const text = {
    gap: "No supporting resume evidence found.",
    unresolvable: "No resume line mentions it. Not counted as a gap: the job description's wording is ambiguous.",
    not_assessed: "Not assessed: part of the resume could not be read, so a missing mention is not reported as a gap.",
  }[observation.status] ?? "No resume line quoted.";
  return el("p", text, "no-evidence");
}

function cell(tag, className, label, content) {
  const node = el(tag, undefined, className);
  node.setAttribute("role", tag === "th" ? "rowheader" : "cell");
  if (label) node.append(el("span", label, "cell-label"));
  node.append(content);
  return node;
}

function table(observations, seen) {
  // Explicit roles keep the table's meaning for screen readers when small screens restyle it.
  const t = el("table", undefined, "evidence");
  t.setAttribute("role", "table");
  const cols = el("colgroup");
  for (const c of ["c-skill", "c-status", "c-jd", "c-resume"]) cols.append(el("col", undefined, c));
  t.append(cols);
  const head = t.createTHead();
  head.setAttribute("role", "rowgroup");
  const headRow = head.insertRow();
  headRow.setAttribute("role", "row");
  for (const h of ["Skill", "Status", "Job requirement", "Resume evidence"]) {
    const th = el("th", h);
    th.scope = "col";
    th.setAttribute("role", "columnheader");
    headRow.append(th);
  }
  const body = t.createTBody();
  body.setAttribute("role", "rowgroup");
  for (const o of observations) {
    const row = body.insertRow();
    row.setAttribute("role", "row");
    const skillId = uid("skill");
    const skill = cell("th", "cell-skill", null, document.createTextNode(o.skill));
    skill.scope = "row";
    skill.id = skillId;
    row.append(
      skill,
      cell("td", "cell-status", null, statusBadge(o.status)),
      cell("td", "cell-evidence", "Job requirement", evidence(o.jd_evidence, "jd", o, seen, skillId)),
      cell("td", "cell-evidence", "Resume evidence",
        o.resume_evidence ? evidence(o.resume_evidence, "resume", o, seen, skillId) : noEvidence(o)),
    );
  }
  return t;
}

function filterCounts(all) {
  return Object.fromEntries(FILTERS.map((f) => [f.key, f.statuses ? all.filter((o) => f.statuses.includes(o.status)).length : all.length]));
}

function renderFilters(all) {
  const counts = filterCounts(all);
  const buttons = FILTERS.filter((f) => !f.optional || counts[f.key] > 0).map((f) => {
    const button = el("button", undefined, "filter");
    button.type = "button";
    button.dataset.filter = f.key;
    button.setAttribute("aria-pressed", String(f.key === activeFilter));
    button.append(el("span", f.label), el("span", String(counts[f.key]), "filter-count"));
    button.addEventListener("click", () => {
      activeFilter = f.key;
      $("filters").querySelectorAll(".filter").forEach((b) => b.setAttribute("aria-pressed", String(b === button)));
      renderGroups();
      track("filter", { key: f.key });
      announce(f.statuses ? `Showing ${counts[f.key]} of ${all.length} skills: ${f.label.toLowerCase()}.` : `Showing all ${all.length} skills.`, "filter-status");
    });
    return button;
  });
  $("filters").replaceChildren(...buttons);
  $("filters").hidden = all.length === 0;
}

// An empty list only says what the readable text shows: a scanned page can hold requirements.
function noSkillsMessage(coverage) {
  if (coverage.chars_extracted === 0) {
    return "No text could be read from the job description (a scanned or image-only PDF, for example), " +
      "so no skills were checked. Paste the text, or upload a PDF that contains text.";
  }
  return "No skill from careerfit's skill list was found in the readable text of the job description, so " +
    "there is nothing to compare. Skills outside the list are not checked." + unreadPart(coverage);
}

function unreadPart(coverage) {
  return coverage.known_blind_spots.includes("scanned_pages")
    ? " Part of the job description could not be read, so skills there were not checked." : "";
}

function renderGroups() {
  const all = current.facts.skill_observations;
  const coverage = current.facts.jd_coverage;
  const filter = FILTERS.find((f) => f.key === activeFilter);
  const seen = new Map(); // repeated long quotes: shown once per view, then referenced
  $("groups").hidden = all.length === 0;
  $("no-skills").hidden = all.length !== 0;
  $("no-skills").textContent = all.length === 0 ? noSkillsMessage(coverage) : "";
  for (const [level, id, name] of [["must", "must", "must-have"], ["nice", "nice", "nice-to-have"]]) {
    const group = all.filter((o) => o.requirement === level);
    const shown = sorted(filter.statuses ? group.filter((o) => filter.statuses.includes(o.status)) : group);
    $(`${id}-count`).textContent = filter.statuses ? `(${shown.length} of ${group.length})` : `(${group.length})`;
    let content;
    if (group.length === 0) {
      content = el("p", `No ${name} skills from careerfit's skill list were found in the readable job description text.` +
        unreadPart(coverage), "empty-state");
    } else if (shown.length === 0) {
      content = el("p", `No ${filter.noun} among the ${name} skills.`, "empty-state");
    } else {
      content = table(shown, seen);
    }
    $(id).replaceChildren(content);
  }
}

function source(name) {
  return name === "pasted-job-description.txt" ? "pasted text" : name;
}

function setDownload(id, text, type) {
  const url = URL.createObjectURL(new Blob([text], { type }));
  downloadUrls.push(url);
  $(id).href = url;
}

function render(payload) {
  const { facts, blind_spots: blindSpots, report_markdown: markdown } = payload;
  current = { facts };
  activeFilter = "all";
  const all = facts.skill_observations;
  const must = all.filter((o) => o.requirement === "must");
  const nice = all.filter((o) => o.requirement === "nice");
  const decided = all.filter((o) => DECIDED.includes(o.status));
  const byKeywords = decided.filter((o) => o.confidence === null).length;
  const ambiguous = all.filter((o) => o.status === "unresolvable").length;

  const candidate = facts.perspective === "candidate";
  $("title").textContent = candidate ? "Your fit for this job" : "Candidate against the job description";
  $("meta").textContent =
    `${candidate ? "Candidate" : "Hiring manager"} report · ${source(facts.resume_source)} compared with ${source(facts.jd_source)}` +
    (payload.jd_donated ? " · Job description donated, thank you" : "");
  $("waitlist-pitch").textContent =
    `An optional AI pass that settles ${ambiguous ? `the ${ambiguous} ambiguous skill${ambiguous === 1 ? "" : "s"} in this result` : "ambiguous skills"}, ` +
    "scores the fit and writes a learning plan for the gaps. Leave your email to hear when it launches.";

  const summary = $("summary");
  summary.setAttribute("role", "group");
  summary.setAttribute("aria-label", "Summary");
  summary.replaceChildren(tally("Must have", must), tally("Nice to have", nice));
  summary.hidden = all.length === 0;

  renderFilters(all);
  renderGroups();

  $("blind-spots").replaceChildren(...blindSpots.map((n) => el("li", n)));
  const judged = decided.length - byKeywords;
  const settled = decided.length === 0
    ? (all.length === 0 ? "There were no skills to decide." : "No skill could be decided from keywords alone.")
    : `${byKeywords} of ${decided.length} decided skill${decided.length === 1 ? " was" : "s were"} settled by keyword matching` +
      (judged ? `, ${judged} by the LLM judge.` : ", without an LLM.");
  $("decided").replaceChildren(
    settled +
      (ambiguous ? ` ${ambiguous} ambiguous skill${ambiguous === 1 ? " stays" : "s stay"} undecided.` : "") +
      " The web app runs the keyword pass only; ",
    el("code", "--deep"),
    ", which asks Claude to settle ambiguous skills, is part of the command-line tool.",
  );

  downloadUrls.forEach((u) => URL.revokeObjectURL(u));
  downloadUrls = [];
  setDownload("download-report", markdown, "text/markdown");
  setDownload("download-facts", JSON.stringify(facts, null, 2) + "\n", "application/json");
  $("result").hidden = false;
}

async function joinWaitlist(event) {
  event.preventDefault();
  const button = $("waitlist-submit");
  const input = $("waitlist-email");
  const message = $("waitlist-message");
  if (button.getAttribute("aria-disabled") === "true") return;
  const email = input.value.trim();
  if (!email) {
    message.textContent = "Enter your email address.";
    message.className = "waitlist-message is-error";
    input.setAttribute("aria-invalid", "true");
    input.focus();
    return;
  }
  button.setAttribute("aria-disabled", "true");
  try {
    const response = await fetch("/api/waitlist", {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ email }),
    });
    const payload = await response.json().catch(() => ({}));
    const ok = response.ok;
    message.textContent = typeof payload.detail === "string" ? payload.detail
      : ok ? "Thanks. We'll email you when it launches." : "That didn't work. Please try again later.";
    message.className = `waitlist-message ${ok ? "is-ok" : "is-error"}`;
    if (ok) {
      input.removeAttribute("aria-invalid");
      input.value = "";
      track("waitlist_joined");
    } else {
      input.setAttribute("aria-invalid", "true");
    }
  } catch {
    message.textContent = "Could not reach the careerfit server.";
    message.className = "waitlist-message is-error";
  } finally {
    button.removeAttribute("aria-disabled");
  }
}

document.addEventListener("DOMContentLoaded", () => {
  const refreshResume = setupUpload("resume", "resume-error");
  const refreshJd = setupUpload("jd", "jd-error");
  limitsReady = loadLimits().then(() => {
    // Files chosen before the limit arrived are checked against the real one.
    refreshResume();
    if (jdMode() === "file") refreshJd();
  });
  document.querySelectorAll('input[name="jd_mode"]').forEach((radio) => radio.addEventListener("change", () => applyJdMode(refreshJd)));
  $("jd_text").addEventListener("input", () => clearFieldError($("jd").closest(".field"), [$("jd"), $("jd_text")], "jd-error"));
  // A file dropped outside an upload area would make the browser open it and lose the form.
  window.addEventListener("dragover", (event) => { if (hasFiles(event)) event.preventDefault(); });
  window.addEventListener("drop", (event) => { if (hasFiles(event)) event.preventDefault(); });
  applyJdMode(refreshJd);
  $("form").addEventListener("submit", submit);
  $("waitlist-form").addEventListener("submit", joinWaitlist);
  $("download-report").addEventListener("click", () => track("download", { kind: "md" }));
  $("download-facts").addEventListener("click", () => track("download", { kind: "json" }));
  track("page_view", pageViewProps());
});
