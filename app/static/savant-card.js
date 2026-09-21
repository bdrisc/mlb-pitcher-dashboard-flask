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
    splits: document.querySelector("#platoon-splits"),
    definitions: document.querySelector("#metric-definitions"),
    databaseFreshness: document.querySelector("#database-freshness"),
  };

  const state = {
    pitchers: [],
    requestController: null,
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
    "csw_pct",
    "zone_pct",
    "chase_pct",
    "hard_hit_pct",
    "strikeout_pct",
    "walk_pct",
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
    if (percentageMetrics.has(key)) return `${formatNumber(value)}%`;
    if (key === "avg_spin") return formatNumber(value, 0);
    if (key === "xwoba_on_contact") return Number(value).toFixed(3).replace(/^0/, "");
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

  function showError(error, title = "Profile unavailable") {
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
    appendOption(elements.pitcher, "", "Select a pitcher");
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
    appendOption(elements.season, "", "All seasons");
    elements.team.replaceChildren();
    appendOption(elements.team, "", "All teams");

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
    setValueIfAvailable(elements.count, balls !== null && strikes !== null ? `${balls}-${strikes}` : "");
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
    if (elements.count.value) {
      const [balls, strikes] = elements.count.value.split("-");
      params.set("balls", balls);
      params.set("strikes", strikes);
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
    });
  }

  function tableCell(row, value, className = "") {
    const cell = document.createElement("td");
    cell.textContent = value;
    if (className) cell.className = className;
    row.append(cell);
  }

  function renderArsenal(arsenal) {
    elements.arsenal.replaceChildren();
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

      tableCell(row, formatMetric("usage_pct", pitch.usage_pct), "emphasized-cell");
      tableCell(row, Number(pitch.pitch_count).toLocaleString("en-US"));
      tableCell(row, formatMetric("avg_velocity", pitch.avg_velocity));
      tableCell(row, formatMetric("max_velocity", pitch.max_velocity));
      tableCell(row, formatMetric("avg_spin", pitch.avg_spin));
      tableCell(row, formatMetric("horizontal_break", pitch.horizontal_break));
      tableCell(row, formatMetric("vertical_break", pitch.vertical_break));
      tableCell(row, formatMetric("whiff_pct", pitch.whiff_pct));
      tableCell(row, formatMetric("csw_pct", pitch.csw_pct));
      tableCell(row, formatMetric("zone_pct", pitch.zone_pct));
      tableCell(row, formatMetric("chase_pct", pitch.chase_pct));
      elements.arsenal.append(row);
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
      title.textContent = split.label;
      sample.textContent = `${split.pitch_count.toLocaleString("en-US")} pitches · ${split.plate_appearances.toLocaleString("en-US")} PA`;
      heading.append(title, sample);

      const metrics = document.createElement("dl");
      metrics.append(
        splitMetric("Whiff%", "whiff_pct", split.whiff_pct),
        splitMetric("Chase%", "chase_pct", split.chase_pct),
        splitMetric("K%", "strikeout_pct", split.strikeout_pct),
        splitMetric("BB%", "walk_pct", split.walk_pct),
        splitMetric("Hard-Hit%", "hard_hit_pct", split.hard_hit_pct),
        splitMetric("xwOBAcon", "xwoba_on_contact", split.xwoba_on_contact),
      );
      card.append(heading, metrics);
      elements.splits.append(card);
    });
  }

  function renderDefinitions(definitions) {
    const labels = {
      rate_unit: "Rate unit",
      whiff_pct: "Whiff%",
      chase_pct: "Chase%",
      zone_pct: "Zone%",
      hard_hit_pct: "Hard-Hit%",
      xwoba_on_contact: "xwOBAcon",
    };
    elements.definitions.replaceChildren();
    Object.entries(definitions).forEach(([key, definition]) => {
      const term = document.createElement("dt");
      const description = document.createElement("dd");
      term.textContent = labels[key] || key;
      description.textContent = definition;
      elements.definitions.append(term, description);
    });
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
    renderSplits(profile.platoon_splits);
    renderDefinitions(profile.definitions);
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
        const title = error.status === 404 ? "No matching pitches" : "Profile unavailable";
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
        appendOption(elements.pitcher, "", "No pitchers in database");
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
      showError(error, "Could not load pitcher directory");
    } finally {
      setLoading(false);
    }
  }

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
