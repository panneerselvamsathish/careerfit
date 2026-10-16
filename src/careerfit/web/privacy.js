// The privacy page's two controls: turning usage counts off in this browser, and leaving the waitlist.
// Same storage keys as app.js. Text from the server is set with textContent only.
"use strict";

const VISITOR_KEY = "careerfit-visitor";
const OPT_OUT_KEY = "careerfit-usage-opt-out";
const $ = (id) => document.getElementById(id);

function storage() {
  try {
    return window.localStorage;
  } catch {
    return null; // storage blocked: there is no ID to keep or remove
  }
}

function showTracking() {
  const store = storage();
  const button = $("tracking-toggle");
  if (!store) {
    $("tracking-status").textContent = "This browser blocks site storage, so careerfit keeps no ID here.";
    button.hidden = true;
    return;
  }
  const off = store.getItem(OPT_OUT_KEY) === "1";
  const anonymous = navigator.globalPrivacyControl === true || navigator.doNotTrack === "1";
  $("tracking-status").textContent = off ? "Usage counts are off in this browser."
    : anonymous ? "Your browser asks not to be tracked, so visits are counted without an ID."
    : "Usage counts are on in this browser.";
  button.textContent = off ? "Turn usage counts back on" : "Turn usage counts off";
  button.hidden = false;
}

function toggleTracking() {
  const store = storage();
  if (!store) return;
  if (store.getItem(OPT_OUT_KEY) === "1") {
    store.removeItem(OPT_OUT_KEY);
    $("tracking-message").textContent = "Usage counts are back on.";
  } else {
    store.setItem(OPT_OUT_KEY, "1");
    store.removeItem(VISITOR_KEY);
    $("tracking-message").textContent = "Usage counts are off, and this browser's ID is deleted.";
  }
  $("tracking-message").className = "waitlist-message is-ok";
  showTracking();
}

async function removeEmail(event) {
  event.preventDefault();
  const button = $("remove-submit");
  const message = $("remove-message");
  const email = $("remove-email").value.trim();
  if (button.getAttribute("aria-disabled") === "true") return;
  if (!email) {
    message.textContent = "Enter the email address to remove.";
    message.className = "waitlist-message is-error";
    $("remove-email").focus();
    return;
  }
  button.setAttribute("aria-disabled", "true");
  try {
    const response = await fetch("/api/waitlist/remove", {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ email }),
    });
    const payload = await response.json().catch(() => ({}));
    message.textContent = typeof payload.detail === "string" ? payload.detail
      : response.ok ? "Done." : "That didn't work. Please try again later.";
    message.className = `waitlist-message ${response.ok ? "is-ok" : "is-error"}`;
    if (response.ok) $("remove-email").value = "";
  } catch {
    message.textContent = "Could not reach the careerfit server.";
    message.className = "waitlist-message is-error";
  } finally {
    button.removeAttribute("aria-disabled");
  }
}

document.addEventListener("DOMContentLoaded", () => {
  showTracking();
  $("tracking-toggle").addEventListener("click", toggleTracking);
  $("remove-form").addEventListener("submit", removeEmail);
});
