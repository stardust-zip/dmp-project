import {
  clock,
  clockShort,
  displayDeviceName,
  displayLocationName,
  displayModelName,
  fmt,
  fmt1,
  fmtKwh,
  humanizeIdentifier,
  isBuildingLocation,
  isSiteLocation,
  locationSearchText,
  timeAgo,
} from "@/lib/format";

describe("humanizeIdentifier", () => {
  it("returns Unspecified for blank values", () => {
    expect(humanizeIdentifier()).toBe("Unspecified");
    expect(humanizeIdentifier(null)).toBe("Unspecified");
    expect(humanizeIdentifier("")).toBe("Unspecified");
    expect(humanizeIdentifier("   ")).toBe("Unspecified");
  });

  it("applies human token overrides", () => {
    expect(humanizeIdentifier("ai_hvac_kwh")).toBe("AI HVAC kWh");
  });

  it("splits on underscore, hyphen, and space", () => {
    expect(humanizeIdentifier("north-wing main_floor")).toBe("North Wing Main Floor");
  });

  it("title-cases unknown tokens", () => {
    expect(humanizeIdentifier("return_air")).toBe("Return Air");
  });

  it("collapses multiple delimiters", () => {
    expect(humanizeIdentifier("foo__bar")).toBe("Foo Bar");
  });
});

describe("displayModelName", () => {
  it("returns Unnamed Model for nullish input", () => {
    expect(displayModelName()).toBe("Unnamed Model");
    expect(displayModelName(null)).toBe("Unnamed Model");
  });

  it("formats dmp_energy_prediction prefix", () => {
    expect(displayModelName("dmp_energy_prediction_building_a_kwh")).toBe("Energy Prediction - Building A - kWh");
  });

  it("falls back to humanizeIdentifier when only one part remains after stripping", () => {
    expect(displayModelName("dmp_energy_prediction_kwh")).toBe("DMP Energy Prediction kWh");
  });

  it("strips leading dmp from non-energy-prediction names", () => {
    expect(displayModelName("dmp_anomaly_detector")).toBe("Anomaly Detector");
  });
});

describe("displayDeviceName", () => {
  it("returns Unnamed Device for nullish input", () => {
    expect(displayDeviceName()).toBe("Unnamed Device");
    expect(displayDeviceName(null)).toBe("Unnamed Device");
  });

  it("strips meter prefix and formats as type meter and location", () => {
    expect(displayDeviceName("meter_electric_building_a")).toBe("Electric Meter - Building A");
  });

  it("falls back to humanizeIdentifier when only one part remains after stripping", () => {
    expect(displayDeviceName("meter")).toBe("Meter");
  });
});

describe("displayLocationName", () => {
  it("returns Unnamed Location for nullish name and id", () => {
    expect(displayLocationName()).toBe("Unnamed Location");
  });

  it("strips building and site prefixes", () => {
    expect(displayLocationName("building_north")).toBe("North");
    expect(displayLocationName("site campus")).toBe("Campus");
  });

  it("falls back to id when name is empty", () => {
    expect(displayLocationName(" ", "building_south")).toBe("South");
  });
});

describe("timeAgo", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-06-28T12:00:00Z"));
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("returns seconds notation for less than 60 seconds", () => {
    expect(timeAgo(Date.now() - 30_000)).toBe("30s ago");
  });

  it("returns minutes notation for less than 1 hour", () => {
    expect(timeAgo(Date.now() - 5 * 60_000)).toBe("5m ago");
  });

  it("returns hours notation for less than 24 hours", () => {
    expect(timeAgo(Date.now() - 3 * 60 * 60_000)).toBe("3h ago");
  });

  it("returns days notation for 24 hours or more", () => {
    expect(timeAgo(Date.now() - 2 * 24 * 60 * 60_000)).toBe("2d ago");
  });
});

describe("fmt / fmt1 / fmtKwh", () => {
  it("fmt rounds to nearest integer and formats with commas", () => {
    expect(fmt(1234.56)).toBe("1,235");
  });

  it("fmt1 always shows one decimal place", () => {
    expect(fmt1(12)).toBe("12.0");
  });

  it("fmtKwh shows 3 decimal places when absolute value is less than 1", () => {
    expect(fmtKwh(0.1254)).toBe("0.125");
  });

  it("fmtKwh rounds to integer when absolute value is at least 1", () => {
    expect(fmtKwh(12.7)).toBe("13");
  });

  it("fmtKwh handles negative values below 1 with decimal format", () => {
    expect(fmtKwh(-0.5)).toBe("-0.500");
  });
});

describe("clock helpers", () => {
  it("formats a full date/time label", () => {
    expect(clock(new Date(2026, 5, 28, 9, 5).getTime())).toMatch(/Jun 28, 09:05/);
  });

  it("formats a short time label", () => {
    expect(clockShort(new Date(2026, 5, 28, 9, 5).getTime())).toBe("09:05");
  });
});

describe("location helpers", () => {
  it("detects site locations case-insensitively", () => {
    expect(isSiteLocation({ location_type: "Site" })).toBe(true);
    expect(isSiteLocation({ location_type: "building" })).toBe(false);
  });

  it("treats non-site locations as buildings", () => {
    expect(isBuildingLocation({ location_type: "site" })).toBe(false);
    expect(isBuildingLocation({ location_type: null })).toBe(true);
  });

  it("builds searchable location text including parent details", () => {
    expect(
      locationSearchText(
        { id: "building_a", name: "Building A", location_type: "building", parent_id: "site_1" },
        { id: "site_1", name: "Main Campus" },
      ),
    ).toContain("main campus");
  });
});
