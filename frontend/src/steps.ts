// The step machine: upload -> when -> where -> flyovers -> review -> searching -> result.
// The step lives in the URL hash so a reload returns to it; the case id is in the path.
import type { Case } from "./api";

export const STEPS = ["upload", "when", "where", "flyovers", "review", "searching", "result"] as const;
export type Step = (typeof STEPS)[number];
/** The five the progress row shows. */
export const MARKED: { id: Step; label: string }[] = [
  { id: "upload", label: "Upload" }, { id: "when", label: "When" }, { id: "where", label: "Where" },
  { id: "flyovers", label: "Flyovers" }, { id: "review", label: "Review" },
];

export const isStep = (s: string): s is Step => (STEPS as readonly string[]).includes(s);

const searchActive = (c: Case) => c.job?.kind === "search" && (c.job.status === "queued" || c.job.status === "running");

/** A search the worker has not picked up yet. */
export const searchQueued = (c: Case) => c.job?.kind === "search" && c.job.status === "queued";

const STOPPED: Record<string, string> = { worker_restarted: "the worker was restarted", timeout: "it ran out of time" };

/** When the newest search failed and an earlier result is still shown, the line that says so. */
export function failedSearchNote(c: Case): string | null {
  if (!c.result || c.job?.kind !== "search" || c.job.status !== "failed") return null;
  const e = c.job.error ?? "";
  const why = STOPPED[e] ?? (e.startsWith("crashed") ? "it crashed" : e || "of an error");
  return `Your latest search stopped before it finished, because ${why}. This is the result of the search before it.`;
}

/** Whether the case has what a step needs. */
export function canEnter(step: Step, c: Case | null): boolean {
  if (step === "upload") return true;
  if (!c || !c.media) return false;
  switch (step) {
    case "when": return true;
    case "where": return !!c.date_local;
    case "flyovers": return !!c.date_local;
    case "review": return !!c.date_local && c.events.confirmed >= 2;
    case "searching": return searchActive(c);
    case "result": return !!c.result;
  }
}

/** Where a case should open: a running search wins, then a result, else the first step still missing something. */
export function resumeStep(c: Case | null): Step {
  if (!c || !c.media) return "upload";
  if (searchActive(c)) return "searching";
  if (c.result) return "result";
  if (!c.date_local) return "when";
  if (c.events.confirmed >= 2) return "review";
  return c.region_ids || c.custom_bbox ? "flyovers" : "where";
}

/** The step to show for a requested one: itself when allowed, else the nearest earlier step that is. */
export function resolveStep(requested: string | null, c: Case | null): Step {
  if (!requested || !isStep(requested)) return resumeStep(c);
  // a running search wins over an earlier result, which it is about to replace
  if (requested === "result" && c && searchActive(c)) return "searching";
  if (canEnter(requested, c)) return requested;
  // a search that has ended: its screen gives way to the result, or back to review
  if (requested === "searching" && c) return c.result ? "result" : resolveStep("review", c);
  for (let i = STEPS.indexOf(requested) - 1; i >= 0; i--) if (canEnter(STEPS[i], c)) return STEPS[i];
  return "upload";
}

/** Where the back arrow leads from a step of a case: the nearest earlier step the case can
 *  show (never the Searching screen), and the cases list from its first step. */
export function backOf(step: Step, c: Case | null): Step | "cases" | null {
  if (step === "upload" || !c) return null;
  for (let i = STEPS.indexOf(step) - 1; i >= 1; i--) if (STEPS[i] !== "searching" && canEnter(STEPS[i], c)) return STEPS[i];
  return "cases";
}

export type MarkState = "done" | "current" | "later";

/** How each of the five progress markers is drawn for the current step. */
export function markStates(current: Step): MarkState[] {
  const at = Math.min(STEPS.indexOf(current), MARKED.length);     // searching and result: all five done
  return MARKED.map((_, i) => (i < at ? "done" : i === at ? "current" : "later"));
}

/** `/cases/<id>#step` <-> { caseId, step } */
export function parseLocation(pathname: string, hash: string): { caseId: string | null; step: string | null; list: boolean } {
  const m = pathname.match(/^\/cases\/([0-9A-Za-z]{10,40})\/?$/);
  return { caseId: m ? m[1] : null, step: hash.replace(/^#/, "") || null, list: /^\/cases\/?$/.test(pathname) };
}

/** What a step is called, for the page title and the cases list. */
export const STEP_TITLES: Record<Step, string> = { upload: "Upload", when: "When", where: "Where", flyovers: "Flyovers", review: "Review", searching: "Searching", result: "Result" };

export const caseUrl = (caseId: string, step: Step) => `/cases/${caseId}#${step}`;
