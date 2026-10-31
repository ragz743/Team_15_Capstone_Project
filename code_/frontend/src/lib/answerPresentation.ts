import type { Source } from "./api";

const measurementWords: Record<string, string> = {
  AVG: "average", MAX: "high", MIN: "low", SUM: "total", TEMP: "temperature",
  HUMID: "humidity", SP: "speed", DIR: "direction", PRECIP: "precipitation", RAD: "radiation",
};

export function measurementLabel(measurement: string): string {
  const [column, ...unit] = measurement.split(" (");
  if (!/^[A-Z][A-Z0-9_]*$/.test(column)) return measurement;
  const name = column.split("_").map(word => measurementWords[word] ?? word.toLowerCase()).join(" ");
  return name + (unit.length ? ` (${unit.join(" (")}`.replace("(F)", "(°F)") : "");
}

export function answerText(text: string, sources: Source[] = []): string {
  let visible = text
    .replace(/[ \t]*\((?:station(?:\s+(?:id|number))?|id)\s*[:#]?\s*\d+\)/gi, "")
    .replace(/\bstation\s+(?:(?:id|number)\s*)?[:#]?\s*\d+\b/gi, "the weather station");
  for (const source of sources) {
    for (const measurement of source.measurements) {
      const column = measurement.split(" (")[0];
      if (/^[A-Z][A-Z0-9_]*$/.test(column)) {
        visible = visible.replace(new RegExp(`\\b${column}\\b`, "g"), measurementLabel(column));
      }
    }
  }
  return visible;
}

export function sourceLabel(source: Source): string {
  const station = source.county ? `${source.station}, ${source.county} County` : source.station;
  const kind = source.kind === "forecast" ? "Forecast" : "Observed weather";
  return [station, kind, source.times.join(", "), ...source.measurements.map(measurementLabel)]
    .filter(Boolean).join(" · ");
}
