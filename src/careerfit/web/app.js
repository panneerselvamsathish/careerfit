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

const $ = (id) => document.getElementById(id);
let downloadUrls = [];
let maxFileMb = 5; // replaced by the server's own limit on load
let limitsReady = Promise.resolve();

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

function cite(evidence) {
  if (!evidence) return "—";
  // Same wording as the Markdown report: say when a skill is shown through another one.
  const through = evidence.source === "derived" ? ` (shown through ${evidence.via})` : "";
  return `${evidence.locator}${through}: "${evidence.excerpt}"`;
}

function table(observations, perspective) {
  if (observations.length === 0) return el("p", "None listed.", "muted");
  const rows = [...observations].sort(
    (a, b) => STATUS_ORDER.indexOf(a.status) - STATUS_ORDER.indexOf(b.status) || a.skill.localeCompare(b.skill),
  );
  const t = el("table");
  const head = t.createTHead().insertRow();
  const resumeHeader = perspective === "candidate" ? "Your resume shows" : "The resume shows";
  for (const h of ["Skill", "Status", "The job description says", resumeHeader]) head.appendChild(el("th", h));
  const body = t.createTBody();
  for (const o of rows) {
    const r = body.insertRow();
    r.appendChild(el("td", o.skill));
    const status = el("td");
    status.appendChild(el("span", STATUS_LABEL[o.status] ?? o.status, `chip ${o.status}`));
    r.appendChild(status);
    r.appendChild(el("td", cite(o.jd_evidence), "quote"));
    r.appendChild(el("td", cite(o.resume_evidence), "quote"));
  }
  return t;
}

function counts(observations) {
  const parts = STATUS_ORDER.map((s) => [s, observations.filter((o) => o.status === s).length])
    .filter(([, n]) => n > 0)
    .map(([s, n]) => `${n} ${STATUS_LABEL[s].toLowerCase()}`);
  return parts.length ? `${parts.join(", ")} (of ${observations.length})` : "none listed";
}

function setDownload(id, text, type) {
  const url = URL.createObjectURL(new Blob([text], { type }));
  downloadUrls.push(url);
  $(id).href = url;
}

function render(payload) {
  const { facts, blind_spots: blindSpots, report_markdown: markdown } = payload;
  const all = facts.skill_observations;
  const must = all.filter((o) => o.requirement === "must");
  const nice = all.filter((o) => o.requirement === "nice");
  const decided = all.filter((o) => DECIDED.includes(o.status));
  const byKeywords = decided.filter((o) => o.confidence === null).length;

  $("title").textContent = facts.perspective === "candidate" ? "Your fit for this job" : "Candidate against the job description";
  $("summary").textContent =
    `Must have: ${counts(must)}. Nice to have: ${counts(nice)}. ` +
    `${byKeywords} of ${decided.length} decided skills were settled by keyword matching, without an LLM.`;
  $("must").replaceChildren(table(must, facts.perspective));
  $("nice").replaceChildren(table(nice, facts.perspective));
  $("blind-spots").replaceChildren(...blindSpots.map((n) => el("li", n)));

  downloadUrls.forEach((u) => URL.revokeObjectURL(u));
  downloadUrls = [];
  setDownload("download-report", markdown, "text/markdown");
  setDownload("download-facts", JSON.stringify(facts, null, 2) + "\n", "application/json");
  $("result").hidden = false;
}

function showError(message) {
  $("error").textContent = message;
  $("error").hidden = false;
}

async function submit(event) {
  event.preventDefault();
  if ($("submit").disabled) return; // one analysis at a time, including while the limits load
  $("error").hidden = true;
  $("result").hidden = true; // a failed run must never leave the previous files' results on screen
  $("submit").disabled = true;
  $("submit").textContent = "Analysing…";
  try {
    await limitsReady; // on a cold start the limit lookup may still be in flight
    // Fields are read after the wait, so edits made while it ran are the ones sent.
    const resume = $("resume").files[0];
    const jdFile = $("jd").files[0];
    const jdText = $("jd_text").value.trim();
    if (!resume) return showError("Choose a resume file.");
    if (Boolean(jdFile) === Boolean(jdText)) return showError("Give the job description either as a file or as pasted text, not both.");
    // Checked here as well as on the server: some hosts refuse a large body before careerfit sees it.
    for (const file of [resume, jdFile]) {
      if (tooLarge(file)) return showError(`${file.name} is larger than ${maxFileMb} MB.`);
    }

    // Only fields that were filled in are sent, so the server never sees an empty file part.
    const form = new FormData();
    form.append("resume", resume);
    if (jdFile) form.append("jd", jdFile);
    else form.append("jd_text", jdText);
    form.append("perspective", document.querySelector('input[name="perspective"]:checked').value);

    const response = await fetch("/api/analyze", { method: "POST", body: form });
    const payload = await response.json().catch(() => ({}));
    if (!response.ok) {
      const detail = typeof payload.detail === "string" ? payload.detail
        : response.status === 413 ? `The upload is too large for this server (limit ${maxFileMb} MB per file).`
        : "The server could not read that request.";
      return showError(detail);
    }
    render(payload);
  } catch {
    showError("Could not reach the careerfit server.");
  } finally {
    $("submit").disabled = false;
    $("submit").textContent = "Analyse";
  }
}

document.addEventListener("DOMContentLoaded", () => {
  limitsReady = loadLimits();
  $("form").addEventListener("submit", submit);
});
