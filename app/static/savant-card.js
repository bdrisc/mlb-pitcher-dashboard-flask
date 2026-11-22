"use strict";

const root = document.querySelector("#savant-app");

if (root) {
  const elements = {
    form: document.querySelector("#profile-filters"),
    pitcher: document.querySelector("#pitcher-select"),
    season: document.querySelector("#season-filter"),
    team: document.querySelector("#team-filter"),
    pitchType: document.querySelector("#pitch-type-filter"),
    batterSide: document.querySelector("#batter-side-filter"),
    count: document.querySelector("#count-filter"),
    homeAway: document.querySelector("#home-away-filter"),
    dateFrom: document.querySelector("#date-from-filter"),
    dateTo: document.querySelector("#date-to-filter"),
    apply: document.querySelector("#apply-filters"),
    reset: document.querySelector("#reset-filters"),
    summary: document.querySelector("#filter-summary"),
    loading: document.querySelector("#loading-state"),
    error: document.querySelector("#error-state"),
    errorTitle: document.querySelector("#error-title"),
    errorMessage: document.querySelector("#error-message"),
    errorDetails: document.querySelector("#error-details"),
    empty: document.querySelector("#empty-state"),
    content: document.querySelector("#profile-content"),
    monogram: document.querySelector("#player-monogram"),
    throwingHand: document.querySelector("#throwing-hand"),
    teamList: document.querySelector("#team-list"),
    pitcherName: document.querySelector("#pitcher-name"),
    coverage: document.querySelector("#profile-coverage"),
    samplePitches: document.querySelector("#sample-pitches"),
    sampleGames: document.querySelector("#sample-games"),
    samplePa: document.querySelector("#sample-pa"),
    playerId: document.querySelector("#player-id"),
    arsenal: document.querySelector("#arsenal-body"),
    arsenalView: document.querySelector("#arsenal-view"),
    separationReference: document.querySelector("#separation-reference"),
    separationBody: document.querySelector("#separation-body"),
    separationTable: document.querySelector("#separation-table"),
    separationEmpty: document.querySelector("#separation-empty"),
    transitionHead: document.querySelector("#transition-head"),
    transitionBody: document.querySelector("#transition-body"),
    transitionTable: document.querySelector("#transition-table"),
    transitionEmpty: document.querySelector("#transition-empty"),
    pairPrevious: document.querySelector("#pitch-pair-previous"),
    pairBody: document.querySelector("#pitch-pair-body"),
    pairTable: document.querySelector("#pitch-pair-table"),
    pairEmpty: document.querySelector("#pitch-pair-empty"),
    pairSortButtons: document.querySelectorAll("[data-pair-sort]"),
    splits: document.querySelector("#platoon-splits"),
    ttoTabs: document.querySelectorAll("[data-tto-view]"),
    ttoPerformancePanel: document.querySelector("#tto-performance-panel"),
    ttoMixPanel: document.querySelector("#tto-mix-panel"),
    ttoPerformanceBody: document.querySelector("#tto-performance-body"),
    ttoPerformanceEmpty: document.querySelector("#tto-performance-empty"),
    ttoMixTableScroll: document.querySelector("#tto-mix-table-scroll"),
    ttoMixHead: document.querySelector("#tto-mix-head"),
    ttoMixBody: document.querySelector("#tto-mix-body"),
    ttoMixEmpty: document.querySelector("#tto-mix-empty"),
    databaseFreshness: document.querySelector("#database-freshness"),
  };

  const state = {
    pitchers: [],
    requestController: null,
    separation: null,
    separationPitcherId: null,
    ttoView: "performance",
    pairEffectiveness: null,
    pairPitcherId: null,
    pairSort: { key: "pair_count", direction: "desc" },
  };

  const pitchColors = {
    FF: "#d7263d",
    FA: "#d7263d",
    SI: "#f28e2b",
    FC: "#8f2d56",
    SL: "#2f6fed",
    ST: "#6f52c7",
    SV: "#8257e5",
    CU: "#19a974",
    KC: "#178f6b",
    CH: "#e0a100",
    FS: "#00a6a6",
  };

  const percentageMetrics = new Set([
    "strike_pct",
    "swing_pct",
    "whiff_pct",
    "zone_whiff_pct",
    "out_of_zone_whiff_pct",
    "swstr_pct",
    "putaway_pct",
    "csw_pct",
    "zone_pct",
    "chase_pct",
    "hard_hit_pct",
    "barrel_pct",
    "gb_pct",
    "fb_pct",
    "ld_pct",
    "pu_pct",
    "strikeout_pct",
    "walk_pct",
    "k_minus_bb_pct",
    "usage_pct",
  ]);

  function formatNumber(value, digits = 1) {
    if (value === null || value === undefined) return "—";
    return Number(value).toLocaleString("en-US", {
      minimumFractionDigits: digits,
      maximumFractionDigits: digits,
    });
  }

  function formatMetric(key, value) {
    if (value === null || value === undefined) return "—";
    if (key === "haaaa" || key === "vaa_adj") {
      const number = Number(value) === 0 ? 0 : Number(value);
      return `${number > 0 ? "+" : ""}${formatNumber(number, 2)}°`;
    }
    if (["vaa", "haa", "avg_arm_angle", "avg_spin_axis"].includes(key)) return `${formatNumber(Number(value) === 0 ? 0 : value)}°`;
    if (["release_point_sd_inches", "release_height_sd_inches", "release_side_sd_inches"].includes(key)) {
      return `${formatNumber(value, 1)} in`;
    }
    if (key === "avg_release_height") return `${formatNumber(value, 1)} ft`;
    if (key === "release_extension") return `${formatNumber(value, 1)} ft`;
    if (key === "avg_release_side") {
      const number = Number(value) === 0 ? 0 : Number(value);
      return `${number > 0 ? "+" : ""}${formatNumber(number, 1)} ft`;
    }
    if (key === "spin_efficiency_pct") return `${formatNumber(value, 1)}%`;
    if (percentageMetrics.has(key)) return `${formatNumber(value)}%`;
    if (key === "avg_spin" || ["stuff_plus", "location_plus", "pitching_plus"].includes(key)) return formatNumber(value, 0);
    if (["fip", "xfip", "siera", "xera"].includes(key)) return formatNumber(value, 2);
    if (["run_value_per_100", "paired_actual_run_value_per_100", "expected_run_value_per_100", "run_value_minus_expected", "run_value_minus_expected_per_100"].includes(key)) {
      const formatted = formatNumber(value);
      return value > 0 ? `+${formatted}` : formatted;
    }
    if (["woba_against", "xwoba_on_contact", "xwoba_against", "xba", "xslg"].includes(key)) return Number(value).toFixed(3).replace(/^0/, "");
    return formatNumber(value);
  }

  function formatDate(value) {
    if (!value) return "—";
    return new Intl.DateTimeFormat("en-US", {
      month: "short",
      day: "numeric",
      year: "numeric",
      timeZone: "UTC",
    }).format(new Date(`${value}T00:00:00Z`));
  }

  function initials(name) {
    const parts = (name || "").split(/[\s,]+/).filter(Boolean);
    if (!parts.length) return "P";
    if (parts.length === 1) return parts[0].slice(0, 2).toUpperCase();
    return `${parts[0][0]}${parts.at(-1)[0]}`.toUpperCase();
  }

  function setVisible(element, visible) {
    element.hidden = !visible;
  }

  function setLoading(isLoading) {
    root.setAttribute("aria-busy", String(isLoading));
    setVisible(elements.loading, isLoading);
    elements.apply.disabled = isLoading || !elements.pitcher.value;
    elements.pitcher.disabled = isLoading || state.pitchers.length === 0;
  }

  function clearMessages() {
    setVisible(elements.error, false);
    setVisible(elements.empty, false);
    elements.errorDetails.replaceChildren();
  }

  function showError(error, title = "Profile Unavailable") {
    setVisible(elements.content, false);
    setVisible(elements.loading, false);
    setVisible(elements.empty, false);
    setVisible(elements.error, true);
    elements.errorTitle.textContent = title;
    elements.errorMessage.textContent =
      error.payload?.message || error.message || "The request could not be completed.";
    elements.errorDetails.replaceChildren();

    const details = error.payload?.details || {};
    Object.entries(details).forEach(([field, messages]) => {
      messages.forEach((message) => {
        const item = document.createElement("li");
        item.textContent = `${field}: ${message}`;
        elements.errorDetails.append(item);
      });
    });
  }

  async function requestJson(url, signal) {
    const response = await fetch(url, {
      headers: { Accept: "application/json" },
      signal,
    });
    const payload = await response.json().catch(() => ({}));
    if (!response.ok) {
      const error = new Error(payload.message || `Request failed with status ${response.status}.`);
      error.payload = payload;
      error.status = response.status;
      throw error;
    }
    return payload;
  }

  function appendOption(select, value, label) {
    const option = document.createElement("option");
    option.value = String(value);
    option.textContent = label;
    select.append(option);
  }

  function populatePitchers() {
    elements.pitcher.replaceChildren();
    appendOption(elements.pitcher, "", "Select a Pitcher");
    state.pitchers.forEach((pitcher) => {
      const hand = pitcher.throws ? `${pitcher.throws}HP` : "Throwing hand N/A";
      const teams = pitcher.teams.length ? pitcher.teams.join("/") : "Team N/A";
      appendOption(
        elements.pitcher,
        pitcher.mlb_id,
        `${pitcher.name || `MLB ${pitcher.mlb_id}`} — ${teams} · ${hand}`,
      );
    });
  }

  function renderDataFreshness(freshness) {
    const latestGameDate = freshness?.latest_game_date;
    elements.databaseFreshness.textContent = latestGameDate
      ? `Database through ${formatDate(latestGameDate)}`
      : "Database coverage unavailable";
  }

  function selectedPitcher() {
    const selectedId = Number(elements.pitcher.value);
    return state.pitchers.find((pitcher) => pitcher.mlb_id === selectedId);
  }

  function configureDependentFilters({ selectLatestSeason = false } = {}) {
    const pitcher = selectedPitcher();
    elements.season.replaceChildren();
    appendOption(elements.season, "", "All Seasons");
    elements.team.replaceChildren();
    appendOption(elements.team, "", "All Teams");

    if (!pitcher) {
      elements.season.disabled = true;
      elements.team.disabled = true;
      elements.apply.disabled = true;
      return;
    }

    const firstYear = Number(pitcher.first_game_date.slice(0, 4));
    const lastYear = Number(pitcher.last_game_date.slice(0, 4));
    for (let year = lastYear; year >= firstYear; year -= 1) {
      appendOption(elements.season, year, year);
    }
    pitcher.teams.forEach((team) => appendOption(elements.team, team, team));
    elements.season.disabled = false;
    elements.team.disabled = pitcher.teams.length === 0;
    elements.apply.disabled = false;
    if (selectLatestSeason) elements.season.value = String(lastYear);
  }

  function setValueIfAvailable(element, value) {
    if (!value) return;
    const optionExists = [...element.options].some((option) => option.value === value);
    if (optionExists) element.value = value;
  }

  function applyUrlState() {
    const params = new URLSearchParams(window.location.search);
    setValueIfAvailable(elements.season, params.get("season"));
    setValueIfAvailable(elements.team, params.get("team"));
    setValueIfAvailable(elements.pitchType, params.get("pitch_type"));
    setValueIfAvailable(elements.batterSide, params.get("batter_side"));
    setValueIfAvailable(elements.homeAway, params.get("home_away"));
    elements.dateFrom.value = params.get("date_from") || "";
    elements.dateTo.value = params.get("date_to") || "";
    const balls = params.get("balls");
    const strikes = params.get("strikes");
    const count = params.get("count_group") ||
      (balls !== null && strikes !== null ? `${balls}-${strikes}` : strikes === "2" && balls === null ? "two_strikes" : "");
    setValueIfAvailable(elements.count, count);
  }

  function profileParameters() {
    const params = new URLSearchParams();
    [
      ["season", elements.season.value],
      ["team", elements.team.value],
      ["pitch_type", elements.pitchType.value],
      ["batter_side", elements.batterSide.value],
      ["home_away", elements.homeAway.value],
      ["date_from", elements.dateFrom.value],
      ["date_to", elements.dateTo.value],
    ].forEach(([key, value]) => {
      if (value) params.set(key, value);
    });
    const count = elements.count.value;
    if (/^[0-3]-[0-2]$/.test(count)) {
      const [balls, strikes] = count.split("-");
      params.set("balls", balls);
      params.set("strikes", strikes);
    } else if (count) {
      params.set("count_group", count);
    }
    return params;
  }

  function syncPageUrl(params) {
    const pageParams = new URLSearchParams(params);
    pageParams.set("pitcher_id", elements.pitcher.value);
    const nextUrl = `${window.location.pathname}?${pageParams.toString()}`;
    window.history.replaceState({}, "", nextUrl);
  }

  function renderMetricCards(overall) {
    document.querySelectorAll("[data-metric]").forEach((element) => {
      const key = element.dataset.metric;
      element.textContent = formatMetric(key, overall[key]);
      if (["fip", "xfip", "siera", "xera"].includes(key)) element.title = publishedTitle(key, overall);
      if (key === "woba_against") element.title = wobaTitle(overall);
      if (key === "xwoba_against") {
        element.title = "Savant-style full xwOBA allowed: expected tracked contact, " +
          "zero for strikeouts, and sourced unintentional walk/HBP weights. " +
          `${overall.xwoba_scored_pa} of ${overall.xwoba_eligible_pa} eligible PA scored. ` +
          (overall.xwoba_missing_pa
            ? "Incomplete tracking: xwOBA withheld to avoid biased values."
            : "Lower is better. Responds to active filters.");
      }
      if (key === "xba") element.title = xbaTitle(overall);
      if (key === "xslg") element.title = xslgTitle(overall);
      if (key === "run_value_per_100") element.title = runValueTitle(overall);
      if (key === "expected_run_value_per_100") element.title = expectedRunValueTitle(overall);
      if (key === "putaway_pct") element.title = putawayTitle(overall);
      if (key === "barrel_pct") element.title = barrelTitle(overall);
      if (["gb_pct", "fb_pct", "ld_pct", "pu_pct"].includes(key)) {
        element.title = battedBallTypeTitle(key, overall);
      }
      if (key === "zone_whiff_pct") element.title = zoneWhiffTitle(overall);
      if (key === "out_of_zone_whiff_pct") element.title = zoneWhiffTitle(overall, "out_of_zone");
    });
  }

  function publishedTitle(key, metrics) {
    const season = metrics.reference_season || "a selected season";
    const side = metrics.reference_batter_side;
    const scope = side === "L" || side === "R"
      ? `${season} vs ${side}HH` : `${season} full season`;
    if (key === "xera") {
      return side === "L" || side === "R"
        ? "Official Baseball Savant xERA is available here only for full seasons; no official handedness xERA was imported. Clear the batter-side filter to view it."
        : `Official Baseball Savant xERA, ${scope}. Not recalculated from xwOBA. Last source refresh: ${metrics.reference_savant_updated || "not available"}. Pitch type, count, date, team and venue filters do not change this season reference.`;
    }
    return `Official FanGraphs ${key === "xfip" ? "xFIP" : key.toUpperCase()}, ${scope}. Last source refresh: ${metrics.reference_fangraphs_updated || "not available"}. Only the batter-handedness selector changes this reference; pitch type, count, date, team and venue filters do not. Missing values mean no verified publisher result was imported.`;
  }

  function xslgTitle(metrics) {
    const scored = metrics.xslg_scored_at_bats || 0;
    const untracked = metrics.xslg_untracked_at_bats || 0;
    return `Expected slugging against: sum of Savant expected total bases on tracked batted balls divided by ${scored.toLocaleString("en-US")} scored at-bats (tracked contact plus strikeouts). Strikeouts count as zero; walks, HBP and sacrifices are excluded. ${untracked.toLocaleString("en-US")} untracked at-bats were omitted rather than treated as zeros. Lower is better; recalculates with active filters.`;
  }

  function xbaTitle(metrics) {
    const scored = metrics.xba_scored_at_bats || 0;
    const untracked = metrics.xba_untracked_at_bats || 0;
    return `Expected batting average allowed: sum of Statcast hit probabilities on tracked batted balls divided by ${scored.toLocaleString("en-US")} scored at-bats (tracked batted balls plus strikeouts). Strikeouts count as zero. Walks, hit-by-pitches and sacrifices do not count as at-bats. ${untracked.toLocaleString("en-US")} untracked at-bats are omitted instead of treated as zeros. Lower is better; recalculates with active filters.`;
  }

  function wobaTitle(metrics) {
    if (metrics.woba_pending_outcomes) return "Waiting for Baseball Savant to verify all selected outcomes.";
    const eligible = metrics.woba_denominator.toLocaleString("en-US");
    return `Actual weighted on-base average allowed on the selected pitches. Uses Baseball Savant's exact weights across ${eligible} eligible plate appearances. Lower is better.`;
  }

  function zoneWhiffTitle(metrics, prefix = "zone") {
    const location = prefix === "zone" ? "in-zone" : "out-of-zone";
    const whiffs = metrics[`${prefix}_whiff_count`].toLocaleString("en-US");
    const swings = metrics[`${prefix}_swing_count`].toLocaleString("en-US");
    return `${whiffs} whiffs / ${swings} ${location} swings. Uses the same swing and whiff definitions as Whiff%; excludes pitches without known location.`;
  }

  function barrelTitle(metrics) {
    const total = metrics.barrel_bbe_count;
    const checked = metrics.barrel_checked_bbe_count;
    const classified = metrics.barrel_classified_bbe_count;
    const pending = total - checked;
    return `${metrics.barrel_count.toLocaleString("en-US")} official barrels / ${total.toLocaleString("en-US")} batted-ball events allowed. Lower is better. ${classified.toLocaleString("en-US")} classified; ${(checked - classified).toLocaleString("en-US")} source-checked events lack classification. ${pending.toLocaleString("en-US")} events awaiting backfill. All batted-ball events remain in the denominator; the rate is withheld until backfill is complete and at least one event is classified.`;
  }

  function battedBallTypeTitle(key, metrics) {
    const counts = { gb_pct: "gb_count", fb_pct: "fb_count", ld_pct: "ld_count", pu_pct: "pu_count" };
    const labels = { gb_pct: "Ground balls", fb_pct: "Fly balls", ld_pct: "Line drives", pu_pct: "Popups" };
    const count = metrics[counts[key]] || 0;
    const total = metrics.batted_ball_type_count || 0;
    const unclassified = metrics.batted_ball_type_unclassified || 0;
    return `${labels[key]}: ${count.toLocaleString("en-US")} / ${total.toLocaleString("en-US")} classified batted-ball events. ${unclassified.toLocaleString("en-US")} unclassified events excluded. These four mutually exclusive shares sum to 100.0% when classification data are available; the percentages respond to the selected filters.`;
  }

  function putawayTitle(metrics) {
    return `${metrics.putaway_strikeout_count.toLocaleString("en-US")} strikeouts / ${metrics.putaway_pitch_count.toLocaleString("en-US")} two-strike pitches thrown. Count is before the pitch; called and swinging strikeouts count. Automatic calls are excluded.`;
  }

  function runValueTitle(metrics) {
    const count = metrics.run_value_pitch_count || 0;
    return `Context-neutral runs prevented per 100 pitches; higher is better. ${count.toLocaleString("en-US")} of ${(metrics.run_value_denominator || 0).toLocaleString("en-US")} pitches have run-value data (${formatNumber(metrics.run_value_coverage_pct || 0)}% coverage).`;
  }

  function expectedRunValueQualityTitle(metrics) {
    const total = metrics.expected_run_value_contact_count || 0;
    const tracked = metrics.expected_run_value_scored_contact_count || 0;
    const coverage = metrics.expected_run_value_contact_coverage_pct;
    const percent = coverage === null || coverage === undefined ? "not applicable" : `${formatNumber(coverage)}%`;
    const status = metrics.expected_run_value_quality || "unavailable";
    const advisory = {
      descriptive: "Adequate descriptive sample; not a validated talent projection.",
      small_sample: "Small sample: interpret rates cautiously and avoid standalone rankings.",
      limited_coverage: "Incomplete tracking: the observed-versus-expected comparison may be biased.",
      unavailable: "No paired expected RV sample."
    };
    return `${tracked.toLocaleString("en-US")} / ${total.toLocaleString("en-US")} eligible contact plays tracked (${percent}); ${advisory[status] || advisory.unavailable}`;
  }

  function expectedRunValueTitle(metrics) {
    const scored = metrics.expected_run_value_pitch_count || 0;
    const total = metrics.run_value_denominator || 0;
    const missing = metrics.expected_run_value_unscored_contact || 0;
    const missingRV = metrics.expected_run_value_missing_actual || 0;
    const unsupported = metrics.expected_run_value_unsupported_contact || 0;
    const unknownScale = metrics.expected_run_value_unknown_scale || 0;
    const mismatches = metrics.expected_run_value_imported_weight_mismatch || 0;
    return `Custom contact-adjusted xRV, NOT an official Baseball Savant xRV metric. Starts with stored context-neutral pitcher RV (verified when the Savant refresh has run), then adds (seasonal FanGraphs outcome wOBA weight − Statcast estimated wOBA on contact) / the SAME season's FanGraphs wOBAScale. This prevents older exported wOBA weights from being mixed with updated seasonal scales. Balls, strikes, whiffs, walks and HBP retain actual pitch RV. ${scored.toLocaleString("en-US")} of ${total.toLocaleString("en-US")} physical pitches scored (${formatNumber(metrics.expected_run_value_coverage_pct || 0)}% coverage); ${missing.toLocaleString("en-US")} unscored batted balls, including ${unsupported.toLocaleString("en-US")} excluded unusual events; ${missingRV.toLocaleString("en-US")} missing RV; ${unknownScale.toLocaleString("en-US")} missing seasonal scales; ${mismatches.toLocaleString("en-US")} stored contact weights differ from the current FanGraphs constants. Missing contact is NOT treated as zero difference. Higher xRV is better for pitchers. ${expectedRunValueQualityTitle(metrics)}. This metric was calibrated against observed contact on the public 2026 cohort; it has not shown statistically reliable superior future-RV prediction versus actual RV.`;
  }

  function signedMovement(value) {
    if (value === null || value === undefined) return "—";
    const number = Number(value) === 0 ? 0 : Number(value);
    return `${number > 0 ? "+" : ""}${formatNumber(number)}`;
  }

  function movementVsAverageTitle(pitch, component) {
    const label = component === "hb" ? "Horizontal movement" : "Induced vertical break";
    if (pitch.movement_joint_pitches === 0) {
      return "No selected pitches have both movement and arm-angle tracking.";
    }
    if (!pitch.movement_avg_pitches) {
      return "A verified full-MLB arm-angle movement reference has not been loaded for this season. Never uses the limited public pitcher cohort.";
    }
    const slots = `${pitch.movement_avg_pitchers} MLB pitchers, ${pitch.movement_avg_pitches.toLocaleString("en-US")} pitches`;
    const caveat = pitch.movement_avg_pitchers < 5 || pitch.movement_avg_pitches < 100
      ? "Insufficient MLB comparison sample; no residual displayed."
      : "Positive HB means more arm-side break than average; negative HB means more glove-side break. Positive IVB means more rise.";
    return `${label} vs. full MLB ${slots}, matching pitch type, throwing hand, and ±5° of average arm angle (${formatNumber(pitch.movement_avg_arm_angle)}°). ${pitch.movement_joint_pitches} selected pitches with joint tracking. ${caveat}`;
  }

  function tableCell(row, value, className = "") {
    const cell = document.createElement("td");
    cell.textContent = value;
    if (className) cell.className = className;
    row.append(cell);
    return cell;
  }

  function tableHeadings(body) {
    return Array.from(body.closest("table").tHead.rows[0].cells);
  }

  function prepareResponsiveRows(body) {
    const headings = tableHeadings(body);
    for (const row of body.rows) {
      row.setAttribute("role", "row");
      Array.from(row.cells).forEach((cell, index) => {
        cell.setAttribute("role", index === 0 ? "rowheader" : "cell");
        if (index === 0) return;
        const label = document.createElement("span");
        label.className = "responsive-cell-label";
        label.setAttribute("aria-hidden", "true");
        label.textContent = headings[index].dataset.mobileLabel || headings[index].textContent;
        cell.prepend(label);
      });
    }
  }

  // The same Extension metric has a different position in the two shape views.
  // Move both the heading and matching body cells to keep them aligned.
  function moveArsenalColumnBefore(label, beforeLabel) {
    const headings = tableHeadings(elements.arsenal);
    const fromIndex = headings.findIndex((heading) => heading.textContent.trim() === label);
    const toIndex = headings.findIndex((heading) => heading.textContent.trim() === beforeLabel);
    if (fromIndex < 0 || toIndex < 0 || fromIndex === toIndex) return;

    headings[fromIndex].parentNode.insertBefore(headings[fromIndex], headings[toIndex]);
    for (const row of elements.arsenal.rows) {
      const cells = Array.from(row.cells);
      row.insertBefore(cells[fromIndex], cells[toIndex]);
    }
  }

  function updateArsenalView() {
    const view = elements.arsenalView.value;
    if (view === "shape-release") {
      moveArsenalColumnBefore("Extension", "Arm Angle");
    } else if (view === "shape-overview") {
      moveArsenalColumnBefore("Extension", "Release Height");
    }
    tableHeadings(elements.arsenal).forEach((heading, index) => {
      const hidden = Boolean(
        heading.dataset.view && !heading.dataset.view.split(/\s+/).includes(view),
      );
      heading.hidden = hidden;
      for (const row of elements.arsenal.rows) row.cells[index].hidden = hidden;
    });
  }

  function renderArsenal(arsenal) {
    elements.arsenal.replaceChildren();
    // Rows are created in the default overview order before the active view is applied.
    moveArsenalColumnBefore("Extension", "Release Height");
    arsenal.forEach((pitch) => {
      const row = document.createElement("tr");
      const pitchCell = document.createElement("th");
      pitchCell.scope = "row";
      const label = document.createElement("span");
      label.className = "pitch-label";
      const dot = document.createElement("span");
      dot.className = "pitch-dot";
      dot.style.backgroundColor = pitchColors[pitch.pitch_type] || "#64748b";
      const text = document.createElement("span");
      text.textContent = pitch.pitch_name || pitch.pitch_type;
      const code = document.createElement("small");
      code.textContent = pitch.pitch_type;
      label.append(dot, text, code);
      pitchCell.append(label);
      row.append(pitchCell);

      tableCell(row, Number(pitch.pitch_count).toLocaleString("en-US"));
      tableCell(row, formatMetric("usage_pct", pitch.usage_pct), "emphasized-cell");
      tableCell(row, formatMetric("run_value_per_100", pitch.run_value_per_100)).title = runValueTitle(pitch);
      tableCell(row, formatMetric("expected_run_value_per_100", pitch.expected_run_value_per_100)).title = expectedRunValueTitle(pitch);
      tableCell(row, formatMetric("stuff_plus", pitch.stuff_plus));
      tableCell(row, formatMetric("location_plus", pitch.location_plus));
      tableCell(row, formatMetric("pitching_plus", pitch.pitching_plus));
      tableCell(row, formatMetric("avg_velocity", pitch.avg_velocity));
      tableCell(row, formatMetric("avg_effective_velocity", pitch.avg_effective_velocity)).title = `Average official Statcast Perceived Velocity (effective_speed; mph), adjusted for release extension relative to an average MLB release point. Not a pitch-location-based Effective Velocity or sequencing adjustment. ${pitch.effective_velocity_pitch_count.toLocaleString("en-US")} of ${pitch.pitch_count.toLocaleString("en-US")} selected pitches have valid effective-speed tracking; automatic balls/strikes excluded. Responds to active filters.`;
      tableCell(row, formatMetric("max_velocity", pitch.max_velocity));
      tableCell(row, formatMetric("avg_spin", pitch.avg_spin));
      tableCell(row, formatMetric("avg_spin_axis", pitch.avg_spin_axis)).title = `Circular average of official Statcast spin axes (0–360°) for this pitch type. 0° = topspin; 180° = backspin. ${pitch.spin_axis_pitch_count.toLocaleString("en-US")} of ${pitch.pitch_count.toLocaleString("en-US")} selected pitches have valid tracked spin axis. Automatic calls excluded. Undefined when directions cancel out. Responds to active filters.`;
      tableCell(row, formatMetric("spin_efficiency_pct", pitch.spin_efficiency_pct)).title = `Official directly measured, spin-based Baseball Savant Active Spin % for ${pitch.spin_efficiency_season || "the selected season"} and this pitch type. Full-season reference, NOT recalculated for date, batter handedness, count, venue, or other narrower filters. No movement-derived estimate; unavailable values appear as —. High or low efficiency is not automatically better.`;
      tableCell(row, formatMetric("avg_arm_angle", pitch.avg_arm_angle)).title = `Average release arm angle measured from horizontal (0°) to over the top (90°). ${pitch.arm_angle_pitch_count.toLocaleString("en-US")} of ${pitch.pitch_count.toLocaleString("en-US")} selected pitches have valid arm-angle tracking. Responds to active filters.`;
      tableCell(row, formatMetric("horizontal_break", pitch.horizontal_break));
      tableCell(row, formatMetric("vertical_break", pitch.vertical_break));
      tableCell(row, formatMetric("release_extension", pitch.release_extension)).title = `Average Statcast release extension, in feet from the front of the pitching rubber toward home plate. ${pitch.release_extension_pitch_count.toLocaleString("en-US")} of ${pitch.pitch_count.toLocaleString("en-US")} selected pitches have valid extension tracking; automatic balls and strikes excluded. Responds to active filters.`;
      tableCell(row, formatMetric("avg_release_height", pitch.avg_release_height)).title = `Average Statcast release position above ground, in feet. ${pitch.release_height_pitch_count.toLocaleString("en-US")} of ${pitch.pitch_count.toLocaleString("en-US")} selected pitches have tracked release height; automatic balls and strikes are excluded. Responds to active filters.`;
      tableCell(row, formatMetric("avg_release_side", pitch.avg_release_side)).title = `Average signed horizontal Statcast release position in feet from home-plate center, from the catcher's perspective. Positive = catcher's right, negative = catcher's left. ${pitch.release_side_pitch_count.toLocaleString("en-US")} of ${pitch.pitch_count.toLocaleString("en-US")} selected pitches have tracked release side; automatic balls and strikes are excluded. Responds to active filters.`;
      tableCell(row, formatMetric("release_point_sd_inches", pitch.release_point_sd_inches)).title = `Release-point dispersion for this pitch type: sqrt(SD(side)² + SD(height)²) in inches, using sample SD on the same physically thrown pitches with both coordinates. Horizontal SD: ${formatMetric("release_side_sd_inches", pitch.release_side_sd_inches)}; vertical SD: ${formatMetric("release_height_sd_inches", pitch.release_height_sd_inches)}. Paired tracking: ${pitch.release_point_sd_pitch_count.toLocaleString("en-US")} of ${pitch.pitch_count.toLocaleString("en-US")} selected pitches. Requires at least 2. Lower is more repeatable, but not a command grade; changes across games can increase season-wide SD.`;
      tableCell(row, signedMovement(pitch.hb_vs_avg)).title = movementVsAverageTitle(pitch, "hb");
      tableCell(row, signedMovement(pitch.ivb_vs_avg)).title = movementVsAverageTitle(pitch, "ivb");
      tableCell(row, formatMetric("vaa", pitch.vaa)).title = `Raw VAA at the front of home plate; negative means descending. ${pitch.vaa_pitch_count.toLocaleString("en-US")} of ${pitch.pitch_count.toLocaleString("en-US")} pitches tracked.`;
      tableCell(row, formatMetric("vaa_adj", pitch.vaa_adj)).title = `VAA minus expected VAA for this pitch type and front-plane height. Positive = flatter; negative = steeper. Frozen 2025 MLB baseline. ${pitch.vaa_adj_pitch_count.toLocaleString("en-US")} of ${pitch.pitch_count.toLocaleString("en-US")} pitches scored.`;
      tableCell(row, formatMetric("haa", pitch.haa)).title = `Raw HAA at the front of home plate; positive is toward the catcher's right. ${pitch.haa_pitch_count.toLocaleString("en-US")} of ${pitch.pitch_count.toLocaleString("en-US")} pitches tracked.`;
      tableCell(row, formatMetric("haaaa", pitch.haaaa)).title = `HAA above expected: observed minus expected HAA, adjusted for pitch type, throwing hand, release side and horizontal location. Frozen 2025 MLB baseline; signed like HAA, not a better/worse grade. ${pitch.haaaa_pitch_count.toLocaleString("en-US")} of ${pitch.pitch_count.toLocaleString("en-US")} pitches scored.`;
      tableCell(row, formatMetric("whiff_pct", pitch.whiff_pct));
      tableCell(row, formatMetric("zone_whiff_pct", pitch.zone_whiff_pct)).title = zoneWhiffTitle(pitch);
      tableCell(row, formatMetric("out_of_zone_whiff_pct", pitch.out_of_zone_whiff_pct)).title = zoneWhiffTitle(pitch, "out_of_zone");
      tableCell(row, formatMetric("swstr_pct", pitch.swstr_pct)).title = `${pitch.swinging_strike_count.toLocaleString("en-US")} swinging strikes / ${pitch.swstr_pitch_count.toLocaleString("en-US")} pitches thrown. Foul tips and bunt attempts are not swinging strikes; automatic calls are not pitches thrown.`;
      tableCell(row, formatMetric("putaway_pct", pitch.putaway_pct)).title = putawayTitle(pitch);
      tableCell(row, formatMetric("csw_pct", pitch.csw_pct));
      tableCell(row, formatMetric("zone_pct", pitch.zone_pct));
      tableCell(row, formatMetric("chase_pct", pitch.chase_pct));
      tableCell(row, formatMetric("barrel_pct", pitch.barrel_pct)).title = barrelTitle(pitch);
      elements.arsenal.append(row);
    });
    prepareResponsiveRows(elements.arsenal);
    updateArsenalView();
  }

  function signedSeparation(value) {
    if (value === null || value === undefined) return "—";
    const rounded = Number(Number(value).toFixed(1)) || 0;
    return `${rounded > 0 ? "+" : ""}${formatNumber(rounded)}`;
  }

  function renderSeparation(data, pitcherId) {
    const previous = state.separationPitcherId === pitcherId ? elements.separationReference.value : null;
    state.separation = data;
    state.separationPitcherId = pitcherId;
    elements.separationReference.replaceChildren();
    appendOption(elements.separationReference, "", "All Pitch Pairs");
    data.pitch_types.forEach((pitch) => {
      appendOption(elements.separationReference, pitch.pitch_type, `${pitch.pitch_name} (${pitch.pitch_type})`);
    });
    const keepPrevious = previous !== null && (previous === "" || data.pitch_types.some((pitch) => pitch.pitch_type === previous));
    elements.separationReference.value = keepPrevious ? previous : data.reference_pitch_type || "";
    elements.separationReference.disabled = data.pitch_types.length < 2;
    renderSeparationRows();
  }

  function renderSeparationRows() {
    const data = state.separation;
    if (!data) return;
    const reference = elements.separationReference.value;
    const pitches = new Map(data.pitch_types.map((pitch) => [pitch.pitch_type, pitch]));
    const pairs = data.pairs.filter((pair) => !reference || [pair.pitch_a, pair.pitch_b].includes(reference));
    elements.separationBody.replaceChildren();
    setVisible(elements.separationEmpty, pairs.length === 0);
    setVisible(elements.separationTable, pairs.length > 0);
    pairs.forEach((pair) => {
      const reverse = reference && pair.pitch_b === reference;
      const a = pitches.get(reverse ? pair.pitch_b : pair.pitch_a);
      const b = pitches.get(reverse ? pair.pitch_a : pair.pitch_b);
      const sign = reverse ? -1 : 1;
      const row = document.createElement("tr");
      const label = document.createElement("th");
      label.scope = "row";
      label.textContent = `${a.pitch_name} (${a.pitch_type})`;
      row.append(label);
      tableCell(row, `${b.pitch_name} (${b.pitch_type})`);
      const velocity = tableCell(row, formatNumber(pair.velocity_gap_mph));
      velocity.title = `Mean velocity gap. ${a.pitch_type}: ${a.velocity_pitch_count.toLocaleString("en-US")} of ${a.pitch_count.toLocaleString("en-US")} pitches; ${b.pitch_type}: ${b.velocity_pitch_count.toLocaleString("en-US")} of ${b.pitch_count.toLocaleString("en-US")} pitches. B minus A: ${signedSeparation(pair.velocity_difference_mph === null ? null : sign * pair.velocity_difference_mph)} mph.`;
      const coverage = `Joint HB/IVB tracking: ${a.pitch_type} ${a.movement_pitch_count.toLocaleString("en-US")}/${a.pitch_count.toLocaleString("en-US")}; ${b.pitch_type} ${b.movement_pitch_count.toLocaleString("en-US")}/${b.pitch_count.toLocaleString("en-US")}. Differences are B minus A in catcher-perspective coordinates.`;
      tableCell(row, signedSeparation(pair.horizontal_difference_inches === null ? null : sign * pair.horizontal_difference_inches)).title = coverage;
      tableCell(row, signedSeparation(pair.vertical_difference_inches === null ? null : sign * pair.vertical_difference_inches)).title = coverage;
      tableCell(row, formatNumber(pair.movement_gap_inches)).title = `Distance between mean movement vectors, not the difference of their magnitudes. ${coverage}`;
      const sequenceCoverage = `Consecutive ${pair.pitch_a} ↔ ${pair.pitch_b} pitches to the same batter, pooling both directions. ${pair.observed_sequence_pair_count.toLocaleString("en-US")} observed pairs. Filters apply to the second pitch.`;
      tableCell(row, formatNumber(pair.release_gap_inches)).title = `Mean 3D release-point distance over ${pair.release_pair_count.toLocaleString("en-US")} tracked pairs. ${sequenceCoverage}`;
      tableCell(row, signedSeparation(pair.late_separation_inches)).title = `Mean plate gap minus tunnel gap over ${pair.late_separation_pair_count.toLocaleString("en-US")} tracked pairs. Tunnel point: 23.8 ft before the front of the plate. Positive: paths spread apart; negative: they converge. Not pure pitch break. ${sequenceCoverage}`;
      elements.separationBody.append(row);
    });
    prepareResponsiveRows(elements.separationBody);
  }

  function renderTransitions(matrix) {
    const { pitch_types: types, rows } = matrix;
    elements.transitionHead.replaceChildren();
    elements.transitionBody.replaceChildren();

    setVisible(elements.transitionEmpty, rows.length === 0);
    setVisible(elements.transitionTable, rows.length > 0);
    if (!rows.length) return;

    const firstHeading = document.createElement("th");
    firstHeading.scope = "col";
    firstHeading.textContent = "Previous Pitch ↓ / Next Pitch Probability →";
    elements.transitionHead.append(firstHeading);
    types.forEach((pitch) => {
      const heading = document.createElement("th");
      heading.scope = "col";
      heading.textContent = pitch.pitch_type;
      heading.title = `Next pitch: ${pitch.pitch_name} (${pitch.pitch_type})`;
      elements.transitionHead.append(heading);
    });
    const totalHeading = document.createElement("th");
    totalHeading.scope = "col";
    totalHeading.textContent = "Row Total";
    elements.transitionHead.append(totalHeading);

    const pitchNames = new Map(types.map((pitch) => [pitch.pitch_type, pitch.pitch_name]));
    rows.forEach((transition) => {
      const row = document.createElement("tr");
      const label = document.createElement("th");
      label.scope = "row";
      label.textContent = transition.pitch_type;
      label.title = `Previous pitch: ${transition.pitch_name}`;
      row.append(label);

      transition.cells.forEach((cell) => {
        const value = document.createElement("td");
        value.className = "transition-cell";
        if (cell.count) {
          value.style.backgroundColor = `rgba(26, 122, 126, ${(0.04 + cell.pct * 0.005).toFixed(3)})`;
        }
        const percentage = document.createElement("strong");
        percentage.textContent = `${formatNumber(cell.pct)}%`;
        const count = document.createElement("small");
        count.textContent = `${cell.count.toLocaleString("en-US")} PC`;
        value.title = `${transition.pitch_name} → ${pitchNames.get(cell.pitch_type)}: ${cell.count.toLocaleString("en-US")} of ${transition.total.toLocaleString("en-US")} observed transitions (${formatNumber(cell.pct)}%). Filters apply to the next pitch.`;
        value.append(percentage, count);
        row.append(value);
      });

      const rowTotal = document.createElement("td");
      rowTotal.className = "transition-row-total";
      rowTotal.textContent = transition.total.toLocaleString("en-US");
      rowTotal.title = `Observed consecutive pitches following ${transition.pitch_name} in the filtered sample.`;
      row.append(rowTotal);
      elements.transitionBody.append(row);
    });
  }

  function renderPitchPairEffectiveness(data, pitcherId) {
    const previous = state.pairPitcherId === pitcherId ? elements.pairPrevious.value : "";
    state.pairEffectiveness = data;
    state.pairPitcherId = pitcherId;
    if (!previous) state.pairSort = { key: "pair_count", direction: "desc" };

    elements.pairPrevious.replaceChildren();
    appendOption(elements.pairPrevious, "", "All Previous Pitches");
    (data?.previous_pitch_types || []).forEach((pitch) => {
      appendOption(elements.pairPrevious, pitch.pitch_type, `${pitch.pitch_name} (${pitch.pitch_type})`);
    });
    elements.pairPrevious.value =
      (data?.previous_pitch_types || []).some((pitch) => pitch.pitch_type === previous)
        ? previous : "";
    elements.pairPrevious.disabled = !(data?.previous_pitch_types || []).length;
    renderPitchPairRows();
  }

  const MAX_PITCH_PAIR_ROWS = 5;

  function renderPitchPairRows() {
    const data = state.pairEffectiveness || { pairs: [] };
    const selected = elements.pairPrevious.value;
    const { key, direction } = state.pairSort;
    const pairs = data.pairs.filter((pair) => !selected || pair.pitch_a === selected);

    elements.pairBody.replaceChildren();
    setVisible(elements.pairEmpty, pairs.length === 0);
    setVisible(elements.pairTable, pairs.length > 0);
    document.querySelectorAll("[data-pair-sort-col]").forEach((heading) => {
      heading.setAttribute(
        "aria-sort",
        heading.dataset.pairSortCol !== key
          ? "none" : (direction === "asc" ? "ascending" : "descending"),
      );
    });
    if (!pairs.length) return;

    const sorted = [...pairs].sort((a, b) => {
      if (key === "pair") {
        const first = `${a.pitch_a}:${a.pitch_b}`;
        const second = `${b.pitch_a}:${b.pitch_b}`;
        return (direction === "asc" ? 1 : -1) * first.localeCompare(second);
      }
      // A missing value always sorts last, regardless of direction.
      const left = a[key];
      const right = b[key];
      if (left == null && right == null) return b.pair_count - a.pair_count;
      if (left == null) return 1;
      if (right == null) return -1;
      return (direction === "asc" ? 1 : -1) * (left - right) ||
        b.pair_count - a.pair_count || a.pitch_a.localeCompare(b.pitch_a) ||
        a.pitch_b.localeCompare(b.pitch_b);
    });

    // Filter and sort the full sample first, then render at most five rows.
    // A selected previous pitch gets its own top five, rather than a subset
    // of the unfiltered table's top five.
    sorted.slice(0, MAX_PITCH_PAIR_ROWS).forEach((pair) => {
      const row = document.createElement("tr");
      const heading = document.createElement("th");
      heading.scope = "row";
      heading.className = "pitch-pair-name";
      const names = document.createElement("strong");
      names.textContent = `${pair.pitch_a} → ${pair.pitch_b}`;
      names.title = `${pair.pitch_a_name} followed by ${pair.pitch_b_name} within the same plate appearance.`;
      heading.append(names);
      if (pair.small_sample) {
        const small = document.createElement("small");
        small.className = "pitch-pair-small-sample";
        small.textContent = "Small sample";
        small.title = "Fewer than 30 observed consecutive pitch pairs";
        heading.append(small);
      }
      row.append(heading);

      tableCell(row, pair.pair_count.toLocaleString("en-US")).title =
        `${pair.pair_count.toLocaleString("en-US")} consecutive, classified pitches. ` +
        "The dashboard filters apply to the second pitch.";
      tableCell(row, formatMetric("whiff_pct", pair.whiff_pct)).title =
        `${pair.whiff_count} whiffs / ${pair.swing_count} swings on the second pitch. ` +
        "Uses the same whiff and swing definitions as the overall profile.";
      tableCell(row, formatMetric("csw_pct", pair.csw_pct)).title =
        `${pair.csw_count} called strikes and whiffs / ${pair.pair_count} second pitches.`;

      const xwobaCell = tableCell(row, formatMetric("xwoba_on_contact", pair.xwoba_on_contact));
      xwobaCell.title =
        `Second-pitch expected wOBA on CONTACT: ` +
        `${pair.xwoba_scored_batted_balls} of ${pair.xwoba_batted_balls} batted balls tracked. ` +
        "Includes only the second pitch of each pair; excludes walks, strikeouts and other " +
        "non-contact outcomes. " +
        (pair.xwoba_on_contact == null
          ? (pair.xwoba_batted_balls
            ? "Batted balls occurred, but none have a usable Statcast expected-wOBA measurement."
            : "No eligible classified batted balls were recorded on the second pitch of this pair.")
          : "Lower is better.");
      if (pair.xwoba_batted_balls) {
        const count = document.createElement("small");
        count.className = "pitch-pair-count-note";
        count.textContent = `${pair.xwoba_scored_batted_balls} BBE`;
        xwobaCell.append(count);
      }
      tableCell(row, formatMetric("run_value_per_100", pair.run_value_per_100)).title =
        `Context-neutral runs prevented on the second pitch per 100 physical pitches. ` +
        `${pair.rv_scored_pitches} of ${pair.pair_count} pitches have RV tracking. ` +
        (pair.run_value_per_100 == null
          ? "Unavailable unless all second pitches have run-value data."
          : "Positive = runs prevented for the pitcher.");
      elements.pairBody.append(row);
    });
  }

  function splitMetric(label, key, value) {
    const wrapper = document.createElement("div");
    const term = document.createElement("dt");
    const description = document.createElement("dd");
    term.textContent = label;
    description.textContent = formatMetric(key, value);
    wrapper.append(term, description);
    return wrapper;
  }

  function renderSplits(splits) {
    elements.splits.replaceChildren();
    splits.forEach((split) => {
      const card = document.createElement("article");
      card.className = "split-card";
      const heading = document.createElement("div");
      const title = document.createElement("h3");
      const sample = document.createElement("span");
      title.textContent = split.label.replace(/^vs /, "Vs ");
      sample.textContent = `${split.pitch_count.toLocaleString("en-US")} pitches · ${split.plate_appearances.toLocaleString("en-US")} PA`;
      heading.append(title, sample);

      const metrics = document.createElement("dl");
      metrics.append(
        splitMetric("Whiff%", "whiff_pct", split.whiff_pct),
        splitMetric("Chase%", "chase_pct", split.chase_pct),
        splitMetric("K%", "strikeout_pct", split.strikeout_pct),
        splitMetric("BB%", "walk_pct", split.walk_pct),
        splitMetric("Hard-Hit%", "hard_hit_pct", split.hard_hit_pct),
        splitMetric("GB%", "gb_pct", split.gb_pct),
        splitMetric("FB%", "fb_pct", split.fb_pct),
        splitMetric("LD%", "ld_pct", split.ld_pct),
        splitMetric("PU%", "pu_pct", split.pu_pct),
        splitMetric("xwOBAcon", "xwoba_on_contact", split.xwoba_on_contact),
        splitMetric("FIP (FG)", "fip", split.fip),
        splitMetric("xFIP (FG)", "xfip", split.xfip),
        splitMetric("SIERA (FG)", "siera", split.siera),
      );
      card.append(heading, metrics);
      elements.splits.append(card);
    });
  }

  function selectTtoView(view) {
    state.ttoView = view === "mix" ? "mix" : "performance";
    elements.ttoPerformancePanel.hidden = state.ttoView !== "performance";
    elements.ttoMixPanel.hidden = state.ttoView !== "mix";
    elements.ttoTabs.forEach((tab) => {
      const selected = tab.dataset.ttoView === state.ttoView;
      tab.setAttribute("aria-selected", String(selected));
      tab.tabIndex = selected ? 0 : -1;
      tab.classList.toggle("is-active", selected);
    });
  }

  function renderTtoSplits(tto) {
    const performance = tto && Array.isArray(tto.performance) ? tto.performance : [];
    const pitchMix = tto && Array.isArray(tto.pitch_mix) ? tto.pitch_mix : [];
    elements.ttoPerformanceBody.replaceChildren();
    elements.ttoPerformanceEmpty.hidden = performance.length > 0;
    for (const trip of performance) {
      const row = document.createElement("tr");
      const heading = document.createElement("th");
      heading.scope = "row";
      heading.textContent = trip.label;
      if (trip.small_sample) {
        const note = document.createElement("small");
        note.className = "tto-small-sample";
        note.textContent = "Small sample";
        note.title = "Fewer than 30 recorded plate appearances";
        heading.append(note);
      }
      row.append(heading);
      tableCell(row, Number(trip.pitch_count).toLocaleString("en-US"));
      tableCell(row, Number(trip.plate_appearances).toLocaleString("en-US"));
      for (const key of [
        "strikeout_pct", "walk_pct", "k_minus_bb_pct", "whiff_pct",
        "xwoba_against", "run_value_per_100",
      ]) {
        const cell = tableCell(row, formatMetric(key, trip[key]));
        if (key === "xwoba_against") {
          cell.title = "Full Savant-style xwOBA allowed on eligible PA in this lineup trip: " +
            `${trip.xwoba_scored_pa} of ${trip.xwoba_eligible_pa} scored. ` +
            (trip.xwoba_scored_pa < trip.xwoba_eligible_pa
              ? "Withheld due to incomplete outcome tracking."
              : "Lower is better.");
        }
        if (key === "run_value_per_100") {
          cell.title = "Runs prevented per 100 physical pitches: "
            + Number(trip.run_value_pitch_count).toLocaleString("en-US")
            + " tracked outcomes / "
            + Number(trip.run_value_denominator).toLocaleString("en-US")
            + " eligible pitches.";
        }
      }
      elements.ttoPerformanceBody.append(row);
    }

    elements.ttoMixHead.replaceChildren();
    elements.ttoMixBody.replaceChildren();
    elements.ttoMixTableScroll.hidden = pitchMix.length === 0;
    elements.ttoMixEmpty.hidden = pitchMix.length > 0;

    if (pitchMix.length) {
      // Each lineup trip is a column with its own usage denominator.
      const pitchHeader = document.createElement("th");
      pitchHeader.scope = "col";
      pitchHeader.textContent = "Pitch Type";
      elements.ttoMixHead.append(pitchHeader);
      for (const trip of pitchMix) {
        const heading = document.createElement("th");
        heading.scope = "col";
        const name = document.createElement("span");
        name.textContent = trip.label;
        const count = document.createElement("small");
        count.textContent = Number(trip.pitch_count).toLocaleString("en-US") + " pitches";
        heading.append(name, count);
        elements.ttoMixHead.append(heading);
      }

      // Rows are pitch types, ordered by total selected usage across all trips.
      const pitchTypes = new Map();
      for (const trip of pitchMix) {
        for (const pitch of trip.pitches) {
          const prior = pitchTypes.get(pitch.pitch_type);
          pitchTypes.set(pitch.pitch_type, {
            name: pitch.pitch_name,
            count: (prior ? prior.count : 0) + Number(pitch.pitch_count),
          });
        }
      }
      const order = [...pitchTypes].sort(
        (a, b) => b[1].count - a[1].count || a[0].localeCompare(b[0]),
      );
      for (const [pitchType, details] of order) {
        const row = document.createElement("tr");
        const heading = document.createElement("th");
        heading.scope = "row";
        const label = document.createElement("span");
        label.className = "tto-mix-pitch-label";
        const dot = document.createElement("span");
        dot.className = "pitch-dot";
        dot.style.backgroundColor = pitchColors[pitchType] || "#64748b";
        const name = document.createElement("span");
        name.textContent = details.name;
        const code = document.createElement("small");
        code.textContent = pitchType;
        label.append(dot, name, code);
        heading.append(label);
        row.append(heading);

        for (const trip of pitchMix) {
          const pitch = trip.pitches.find((p) => p.pitch_type === pitchType);
          const pitchCount = pitch ? Number(pitch.pitch_count) : 0;
          const usage = pitch ? Number(pitch.usage_pct) : 0;
          const cell = document.createElement("td");
          const percentage = document.createElement("strong");
          percentage.textContent = formatNumber(usage, 1) + "%";
          const count = document.createElement("small");
          count.textContent = pitchCount.toLocaleString("en-US") + " pitches";
          cell.append(percentage, count);
          row.append(cell);
        }
        elements.ttoMixBody.append(row);
      }
    }

    selectTtoView(state.ttoView);
  }

  function renderProfile(profile) {
    const { pitcher, sample, overall } = profile;
    elements.monogram.textContent = initials(pitcher.name);
    elements.throwingHand.textContent = pitcher.throws ? `${pitcher.throws}HP` : "Hand N/A";
    elements.teamList.textContent = pitcher.teams.length ? pitcher.teams.join(" / ") : "Team N/A";
    elements.pitcherName.textContent = pitcher.name || `MLB ${pitcher.mlb_id}`;
    elements.coverage.textContent = `${formatDate(sample.first_game_date)} – ${formatDate(sample.last_game_date)}`;
    elements.samplePitches.textContent = sample.pitches.toLocaleString("en-US");
    elements.sampleGames.textContent = sample.games.toLocaleString("en-US");
    elements.samplePa.textContent = sample.plate_appearances.toLocaleString("en-US");
    elements.playerId.textContent = pitcher.mlb_id;
    elements.summary.textContent = `${sample.pitches.toLocaleString("en-US")} pitches across ${sample.games.toLocaleString("en-US")} games`;
    renderMetricCards(overall);
    renderArsenal(profile.arsenal);
    renderSeparation(profile.pitch_separation, pitcher.mlb_id);
    renderTransitions(profile.pitch_transition_matrix);
    renderPitchPairEffectiveness(profile.pitch_pair_effectiveness, pitcher.mlb_id);
    renderSplits(profile.platoon_splits);
    renderTtoSplits(profile.times_through_order_splits);
    setVisible(elements.content, true);
  }

  async function loadProfile() {
    if (!elements.pitcher.value) return;
    if (state.requestController) state.requestController.abort();
    const controller = new AbortController();
    state.requestController = controller;
    clearMessages();
    setVisible(elements.content, false);
    setLoading(true);
    window.SavantCharts?.setLoading(true);

    const params = profileParameters();
    const baseUrl = root.dataset.pitchersUrl.replace(/\/$/, "");
    const query = params.toString();
    const url = `${baseUrl}/${encodeURIComponent(elements.pitcher.value)}/profile${query ? `?${query}` : ""}`;
    const chartsBaseUrl = root.dataset.chartsUrlTemplate.replace(
      "/0/charts",
      `/${encodeURIComponent(elements.pitcher.value)}/charts`,
    );
    const chartsUrl = `${chartsBaseUrl}${query ? `?${query}` : ""}`;
    try {
      const [profileResult, chartsResult] = await Promise.allSettled([
        requestJson(url, controller.signal),
        requestJson(chartsUrl, controller.signal),
      ]);
      if (profileResult.status === "rejected") throw profileResult.reason;
      renderProfile(profileResult.value);
      syncPageUrl(params);
      if (chartsResult.status === "fulfilled") {
        await window.SavantCharts?.render(chartsResult.value);
      } else if (chartsResult.reason.name !== "AbortError") {
        window.SavantCharts?.showError(
          chartsResult.reason.payload?.message || "The chart data could not be loaded.",
        );
      }
    } catch (error) {
      if (error.name !== "AbortError") {
        const title = error.status === 404 ? "No Matching Pitches" : "Profile Unavailable";
        showError(error, title);
      }
    } finally {
      if (state.requestController === controller) {
        setLoading(false);
        window.SavantCharts?.setLoading(false);
      }
    }
  }

  async function initialize() {
    clearMessages();
    setLoading(true);
    try {
      const directory = await requestJson(root.dataset.pitchersUrl);
      state.pitchers = directory.pitchers;
      renderDataFreshness(directory.data_freshness);
      if (!state.pitchers.length) {
        elements.pitcher.replaceChildren();
        appendOption(elements.pitcher, "", "No Pitchers in Database");
        setVisible(elements.empty, true);
        elements.summary.textContent = "Ingest data to begin.";
        return;
      }

      populatePitchers();
      const params = new URLSearchParams(window.location.search);
      const requestedId = params.get("pitcher_id");
      const requestedExists = state.pitchers.some(
        (pitcher) => String(pitcher.mlb_id) === requestedId,
      );
      elements.pitcher.value = requestedExists ? requestedId : String(state.pitchers[0].mlb_id);
      configureDependentFilters({ selectLatestSeason: true });
      applyUrlState();
      await loadProfile();
    } catch (error) {
      showError(error, "Could Not Load Pitcher Directory");
    } finally {
      setLoading(false);
    }
  }

  elements.ttoTabs.forEach((tab, index) => {
    tab.addEventListener("click", () => selectTtoView(tab.dataset.ttoView));
    tab.addEventListener("keydown", (event) => {
      if (!["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key)) return;
      event.preventDefault();
      let target = index;
      if (event.key === "ArrowRight") target = (index + 1) % elements.ttoTabs.length;
      if (event.key === "ArrowLeft") target = (index - 1 + elements.ttoTabs.length) % elements.ttoTabs.length;
      if (event.key === "Home") target = 0;
      if (event.key === "End") target = elements.ttoTabs.length - 1;
      const next = elements.ttoTabs[target];
      selectTtoView(next.dataset.ttoView);
      next.focus();
    });
  });
  elements.arsenalView.addEventListener("change", updateArsenalView);
  elements.separationReference.addEventListener("change", renderSeparationRows);
  elements.pairPrevious.addEventListener("change", renderPitchPairRows);
  elements.pairSortButtons.forEach((button) => {
    button.addEventListener("click", () => {
      const key = button.dataset.pairSort;
      const current = state.pairSort;
      const defaultDirection = key === "pair" || key === "xwoba_on_contact" ? "asc" : "desc";
      state.pairSort = {
        key,
        direction: current.key === key
          ? (current.direction === "asc" ? "desc" : "asc")
          : defaultDirection,
      };
      renderPitchPairRows();
    });
  });

  elements.form.addEventListener("submit", (event) => {
    event.preventDefault();
    loadProfile();
  });

  elements.pitcher.addEventListener("change", () => {
    configureDependentFilters({ selectLatestSeason: true });
    elements.team.value = "";
    elements.dateFrom.value = "";
    elements.dateTo.value = "";
    loadProfile();
  });

  elements.reset.addEventListener("click", () => {
    elements.season.value = "";
    elements.team.value = "";
    elements.pitchType.value = "";
    elements.batterSide.value = "";
    elements.count.value = "";
    elements.homeAway.value = "";
    elements.dateFrom.value = "";
    elements.dateTo.value = "";
    loadProfile();
  });

  initialize();
}
