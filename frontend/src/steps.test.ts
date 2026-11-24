import { describe, expect, it } from "vitest";
import type { Case } from "./api";
import { clock, coords, distance, flightsText, googleMapsUrl, maxHarmonics, metresBetween, presetOf, pText, rangesText, toHHMM, toMinutes } from "./format";
import { backOf, canEnter, caseUrl, failedSearchNote, markStates, parseLocation, resolveStep, resumeStep, searchQueued } from "./steps";

const base: Case = {
  id: "01M7ZSXWCYCP3736S3QC4Z3X7M", case_ref: null, created_at: "", status: "draft", pack_id: "test", date_local: null, time_ranges: null,
  region_ids: null, custom_bbox: null, temperature_c: null, temperature_source: null, temperature_effective: null, media: null,
  events: { proposed: 0, confirmed: 0, rejected: 0 }, job: null, result: null, last_event_id: 0, stream_from: 0,
};
const media = { id: "m", filename: "clip.wav", sha256: "x", size_bytes: 1, duration_s: 1800, spectrogram_ready: true };
const withMedia: Case = { ...base, media };
const dated: Case = { ...withMedia, date_local: "2026-11-14" };
const two: Case = { ...dated, events: { proposed: 3, confirmed: 2, rejected: 0 } };
const searching: Case = { ...two, job: { id: "j", kind: "search", status: "running", stage: "fits", progress: null, error: null } };
const done: Case = { ...two, result: { id: "r", state: "located", band: "High", strength: 100, verdict: "located", p: 0.0004 } };

describe("the step machine", () => {
  it("lets nothing past upload without a recording", () => {
    for (const s of ["when", "where", "flyovers", "review", "searching", "result"] as const) expect(canEnter(s, base)).toBe(false);
    expect(canEnter("upload", null)).toBe(true);
    expect(resolveStep("review", base)).toBe("upload");
  });

  it("needs the date before the area and the flyovers", () => {
    expect(canEnter("when", withMedia)).toBe(true);
    expect(canEnter("where", withMedia)).toBe(false);
    expect(resolveStep("flyovers", withMedia)).toBe("when");
    expect(canEnter("flyovers", dated)).toBe(true);
  });

  it("needs two confirmed flyovers to review; proposals do not count", () => {
    expect(canEnter("review", { ...dated, events: { proposed: 6, confirmed: 1, rejected: 0 } })).toBe(false);
    expect(resolveStep("review", { ...dated, events: { proposed: 6, confirmed: 1, rejected: 0 } })).toBe("flyovers");
    expect(canEnter("review", two)).toBe(true);
  });

  it("opens a case where it was left", () => {
    expect(resumeStep(null)).toBe("upload");
    expect(resumeStep(withMedia)).toBe("when");
    expect(resumeStep(dated)).toBe("where");
    expect(resumeStep({ ...dated, region_ids: ["home"] })).toBe("flyovers");
    expect(resumeStep(two)).toBe("review");
    expect(resumeStep(searching)).toBe("searching");
    expect(resumeStep(done)).toBe("result");
    expect(resolveStep(null, two)).toBe("review");
    expect(resolveStep("nonsense", dated)).toBe("where");
  });

  it("leaves the searching screen once the search has ended", () => {
    expect(resolveStep("searching", searching)).toBe("searching");
    expect(resolveStep("searching", done)).toBe("result");
    expect(resolveStep("searching", two)).toBe("review");
    expect(resolveStep("result", two)).toBe("review");
    // a new search on a case that already has a result: the old one must not show as current
    const researching: Case = { ...done, job: searching.job };
    expect(resolveStep("result", researching)).toBe("searching");
    expect(resumeStep(researching)).toBe("searching");
  });

  it("marks done, current and later steps", () => {
    expect(markStates("upload")).toEqual(["current", "later", "later", "later", "later"]);
    expect(markStates("flyovers")).toEqual(["done", "done", "done", "current", "later"]);
    expect(markStates("searching")).toEqual(["done", "done", "done", "done", "done"]);
  });

  it("keeps the case in the path and the step in the hash", () => {
    expect(parseLocation("/cases/01M7ZSXWCYCP3736S3QC4Z3X7M", "#flyovers")).toEqual({ caseId: "01M7ZSXWCYCP3736S3QC4Z3X7M", step: "flyovers", list: false });
    expect(parseLocation("/", "")).toEqual({ caseId: null, step: null, list: false });
    expect(parseLocation("/cases", "")).toEqual({ caseId: null, step: null, list: true });
    expect(parseLocation("/cases/../etc", "#when").caseId).toBeNull();
    expect(caseUrl("ABC", "when")).toBe("/cases/ABC#when");
  });
});

describe("formatting", () => {
  it("writes audio times as the mockups do", () => {
    expect(clock(308)).toBe("5:08");
    expect(clock(308, true)).toBe("05:08");
    expect(clock(1930)).toBe("32:10");
    expect(clock(3725)).toBe("1:02:05");
  });

  it("recognises presets and describes ranges", () => {
    expect(presetOf([["12:00", "17:00"]])).toBe("afternoon");
    expect(presetOf(null)).toBe("unsure");
    expect(presetOf([["21:00", "06:00"]])).toBe("night");
    expect(presetOf([["13:30", "15:00"]])).toBe("custom");
    expect(rangesText(null)).toBe("Any time");
    expect(rangesText([["12:00", "17:00"]])).toBe("12:00 to 17:00");
    expect(toHHMM(toMinutes("17:30"))).toBe("17:30");
    expect(toHHMM(1440)).toBe("24:00");
  });

  it("caps harmonics so the top one stays on the grid", () => {
    expect(maxHarmonics(144)).toBe(3);
    expect(maxHarmonics(170)).toBe(2);
    expect(maxHarmonics(300)).toBe(1);
  });

  it("writes coordinates, distances and p values for the result screens", () => {
    expect(coords(25.14123, 55.22684)).toBe("25.1412° N, 55.2268° E");
    expect(coords(-33.86, -151.2)).toBe("33.8600° S, 151.2000° W");
    expect(distance(112)).toBe("110 m");
    expect(distance(50)).toBe("50 m");
    expect(distance(1234)).toBe("1.2 km");
    expect(pText(0.0004)).toBe("p under 0.001");
    expect(pText(0.004)).toBe("p 0.004");
    expect(pText(0.2338)).toBe("p 0.23");
    expect(pText(null)).toBe("not judged");
    expect(Math.round(metresBetween([25.05, 55.25], [25.05, 55.26]))).toBeGreaterThan(990);
  });
});

describe("the back arrow", () => {
  it("leads to the step before, and to the cases list from a case's first step", () => {
    expect(backOf("upload", null)).toBe(null);
    expect(backOf("when", withMedia)).toBe("cases");
    expect(backOf("where", dated)).toBe("when");
    expect(backOf("flyovers", dated)).toBe("where");
    expect(backOf("review", two)).toBe("flyovers");
  });

  it("never leads to the Searching screen", () => {
    expect(backOf("searching", searching)).toBe("review");
    expect(backOf("result", done)).toBe("review");
    // a case finished as not locatable has fewer than two flyovers: Review is closed to it
    expect(backOf("result", { ...dated, result: { id: "r", state: "not_locatable", band: null, strength: null, verdict: null, p: null } })).toBe("flyovers");
  });
});

describe("the flight-data icon", () => {
  const s = { status: "idle", utc_date: null, newest_on_disk: null, fraction: null, bytes_total: null, detail: null, error: null };

  it("says what is downloading and how far it has got", () => {
    const t = flightsText({ ...s, status: "fetching", utc_date: "2026-11-20", fraction: 0.25, bytes_total: 3_600_000_000 });
    expect(t.title).toBe("Downloading flight data for 20 Nov 2026");
    expect(t.lines[0]).toBe("0.90 of 3.60 GB");
    // a day an analyst asked for has no known size: the server's own words stand in
    expect(flightsText({ ...s, status: "fetching", utc_date: "2026-11-20", detail: "0.40 GB read, 2,000 aircraft files" }).lines[0]).toBe("0.40 GB read, 2,000 aircraft files");
  });

  it("names the newest day on disk, and the reason when an update fails", () => {
    expect(flightsText({ ...s, status: "current", newest_on_disk: "2026-11-21" })).toEqual({ title: "Flight data is up to date", lines: ["Newest day on this machine: 21 Nov 2026 (UTC)"] });
    expect(flightsText({ ...s, status: "checking" }).title).toBe("Checking for newer flight data");
    expect(flightsText({ ...s, status: "failed", error: "The flight archive could not be reached." }).lines[0]).toBe("The flight archive could not be reached.");
  });

  it("links a point to Google Maps", () => {
    expect(googleMapsUrl(25.049994, 55.25)).toBe("https://www.google.com/maps/search/?api=1&query=25.04999%2C55.25000");
  });
});

describe("a search that did not finish", () => {
  const failedAgain = (error: string | null): Case => ({ ...done, job: { id: "j2", kind: "search", status: "failed", stage: "scoring", progress: null, error } });

  it("says so on the earlier result it left in place", () => {
    expect(resolveStep("result", failedAgain("timeout"))).toBe("result");
    expect(failedSearchNote(failedAgain("worker_restarted"))).toMatch(/latest search stopped.*worker was restarted.*search before it/i);
    expect(failedSearchNote(failedAgain("timeout"))).toMatch(/ran out of time/);
    expect(failedSearchNote(failedAgain("crashed: exit code -9"))).toMatch(/crashed/);
    expect(failedSearchNote(failedAgain("search_failed: no flights"))).toMatch(/search_failed: no flights/);
  });

  it("says nothing when the result is the latest search, or the search was cancelled", () => {
    expect(failedSearchNote(done)).toBeNull();
    expect(failedSearchNote({ ...done, job: { id: "j2", kind: "search", status: "cancelled", stage: null, progress: null, error: null } })).toBeNull();
    expect(failedSearchNote({ ...done, job: { id: "j2", kind: "search", status: "done", stage: null, progress: null, error: null } })).toBeNull();
    expect(failedSearchNote({ ...two, job: failedAgain("timeout").job })).toBeNull();     // no earlier result: Searching shows the error
  });

  it("knows a search still waiting for the worker", () => {
    expect(searchQueued({ ...two, job: { id: "j", kind: "search", status: "queued", stage: null, progress: null, error: null } })).toBe(true);
    expect(searchQueued(searching)).toBe(false);
    expect(searchQueued(done)).toBe(false);
  });
});
