// Small pure helpers: times, ranges, presets, numbers.

/** Seconds of audio as m:ss, or h:mm:ss past an hour. */
export function clock(seconds: number, pad = false): string {
  const s = Math.max(0, Math.round(seconds));
  const h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60), sec = s % 60;
  const mm = h > 0 || pad ? String(m).padStart(2, "0") : String(m);
  return (h > 0 ? `${h}:` : "") + `${mm}:${String(sec).padStart(2, "0")}`;
}

export const minutes = (seconds: number) => Math.round(seconds / 60);

export type Range = [string, string];

/** Time-of-day presets, local time. Night wraps midnight: the server splits it in two. */
export const PRESETS: { id: string; label: string; ranges: Range[] | null }[] = [
  { id: "morning", label: "Morning", ranges: [["06:00", "12:00"]] },
  { id: "afternoon", label: "Afternoon", ranges: [["12:00", "17:00"]] },
  { id: "evening", label: "Evening", ranges: [["17:00", "21:00"]] },
  { id: "night", label: "Night", ranges: [["21:00", "06:00"]] },
  { id: "unsure", label: "Not sure", ranges: null },
];

export const toMinutes = (hhmm: string) => Number(hhmm.slice(0, 2)) * 60 + Number(hhmm.slice(3, 5));
export const toHHMM = (min: number) => {
  const m = Math.max(0, Math.min(1440, Math.round(min)));
  return `${String(Math.floor(m / 60)).padStart(2, "0")}:${String(m % 60).padStart(2, "0")}`;
};

const same = (a: Range[] | null, b: Range[] | null) => JSON.stringify(a ?? null) === JSON.stringify(b ?? null);

/** Which preset the stored ranges are, or "custom". */
export function presetOf(ranges: Range[] | null | undefined): string {
  return PRESETS.find((p) => same(p.ranges, ranges ?? null))?.id ?? "custom";
}

/** "12:00 to 17:00", "21:00 to 06:00", or "Any time" for the whole day. */
export function rangesText(ranges: Range[] | null | undefined): string {
  if (!ranges || ranges.length === 0) return "Any time";
  return ranges.map(([a, b]) => `${a} to ${b}`).join(", ");
}

/** The long name of a time zone on a date ("Gulf Standard Time"), and its short form ("GST" or "GMT+4"). */
export function zoneName(timeZone: string, date: string | null, style: "long" | "short" = "long"): string {
  try {
    const d = date ? new Date(`${date}T12:00:00Z`) : new Date();
    const part = new Intl.DateTimeFormat("en-GB", { timeZone, timeZoneName: style }).formatToParts(d).find((p) => p.type === "timeZoneName");
    return part?.value ?? timeZone;
  } catch {
    return timeZone;
  }
}

/** "14 Nov 2026" */
export function dateText(iso: string | null): string {
  if (!iso) return "Not set";
  const d = new Date(`${iso}T00:00:00Z`);
  return new Intl.DateTimeFormat("en-GB", { day: "numeric", month: "short", year: "numeric", timeZone: "UTC" }).format(d);
}

export const todayISO = () => new Date().toLocaleDateString("en-CA");

/** Kilometres to one decimal, as the flyover list shows distance. */
export const km = (metres: number) => `${(metres / 1000).toFixed(1)} km`;

/** The most harmonics a box may use: the top one must stay inside the 450 Hz grid. At most 3. */
export const maxHarmonics = (f_hi: number, top = 450) => Math.max(1, Math.min(3, Math.floor(top / Math.max(f_hi, 1))));

/** "25.1412° N, 55.2268° E" */
export function coords(lat: number, lon: number): string {
  return `${Math.abs(lat).toFixed(4)}° ${lat >= 0 ? "N" : "S"}, ${Math.abs(lon).toFixed(4)}° ${lon >= 0 ? "E" : "W"}`;
}

/** A distance rounded to two significant figures: "150 m", "1.2 km". */
export function distance(metres: number): string {
  if (metres < 1000) { const p = Math.pow(10, Math.max(0, Math.floor(Math.log10(Math.max(metres, 1))) - 1)); return `${Math.round(metres / p) * p} m`; }
  return `${(metres / 1000).toPrecision(2)} km`;
}

/** A unix time as HH:MM:SS in a time zone. */
export function localClock(unix: number, timeZone: string): string {
  return new Intl.DateTimeFormat("en-GB", { timeZone, hour: "2-digit", minute: "2-digit", second: "2-digit", hour12: false }).format(new Date(unix * 1000));
}

/** A p value the way the verdict rows show it: "0.004", "0.23", "under 0.001". */
export function pText(p: number | null): string {
  if (p == null) return "not judged";
  if (p < 0.001) return "p under 0.001";
  return `p ${p < 0.01 ? p.toFixed(3) : p.toFixed(2)}`;
}

export const SOURCES: Record<string, string> = { analyst: "set by you", climate_monthly: "monthly average", auto: "automatic" };

/** Great-circle distance in metres. */
export function metresBetween(a: [number, number], b: [number, number]): number {
  const r = Math.PI / 180, dla = (b[0] - a[0]) * r, dlo = (b[1] - a[1]) * r;
  const h = Math.sin(dla / 2) ** 2 + Math.cos(a[0] * r) * Math.cos(b[0] * r) * Math.sin(dlo / 2) ** 2;
  return 2 * 6371008.8 * Math.asin(Math.sqrt(h));
}

const gb = (bytes: number) => (bytes / 1e9).toFixed(2);

/** What the flight-data icon says: a title, and the lines under it. */
export function flightsText(s: { status: string; utc_date: string | null; newest_on_disk: string | null; fraction: number | null;
                                 bytes_total: number | null; detail: string | null; error: string | null }): { title: string; lines: string[] } {
  const newest = s.newest_on_disk ? [`Newest day on this machine: ${dateText(s.newest_on_disk)} (UTC)`] : ["No flight day on this machine yet"];
  switch (s.status) {
    case "checking":
      return s.utc_date ? { title: `Waiting to download ${dateText(s.utc_date)}`, lines: ["Another download is running first"] }
                        : { title: "Checking for newer flight data", lines: newest };
    case "fetching": {
      const size = s.bytes_total && s.fraction != null ? [`${gb(s.fraction * s.bytes_total)} of ${gb(s.bytes_total)} GB`] : s.detail ? [s.detail] : [];
      return { title: `Downloading flight data for ${dateText(s.utc_date)}`, lines: [...size, "It runs in the background. You can keep working."] };
    }
    case "current":
      return { title: "Flight data is up to date", lines: newest };
    case "failed":
      return { title: "Flight data could not be updated", lines: [s.error ?? "The update stopped before it finished.", ...newest] };
    default:
      return { title: "Flight data has not been checked", lines: newest };
  }
}

/** The point in Google Maps, by its documented search link. Opening it sends the coordinates to Google. */
export const googleMapsUrl = (lat: number, lon: number) => `https://www.google.com/maps/search/?api=1&query=${lat.toFixed(5)}%2C${lon.toFixed(5)}`;
