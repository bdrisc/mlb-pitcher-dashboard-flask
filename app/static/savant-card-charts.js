"use strict";

(() => {
  const colors = {
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

  const containers = {
    movement: document.querySelector("#movement-chart"),
    velocity: document.querySelector("#velocity-chart"),
    release: document.querySelector("#release-chart"),
    location: document.querySelector("#location-chart"),
    countUsage: document.querySelector("#count-usage-chart"),
  };
  const inningMetricSelect = document.querySelector("#inning-metric");
  const inningDisplayMode = document.querySelector("#inning-display-mode");
  const inningGrid = document.querySelector("#inning-chart-grid");
  let inningData = { pitch_types: [], rows: [] };
  const status = document.querySelector("#chart-status");
  const chartGrid = document.querySelector("#chart-grid");

  const config = {
    responsive: true,
    displaylogo: false,
    scrollZoom: false,
    modeBarButtonsToRemove: ["lasso2d", "select2d"],
    toImageButtonOptions: { format: "png", scale: 2 },
  };

  function baseLayout(overrides = {}) {
    return {
      autosize: true,
      height: 365,
      margin: { l: 58, r: 24, t: 24, b: 58 },
      paper_bgcolor: "rgba(0,0,0,0)",
      plot_bgcolor: "#ffffff",
      font: {
        family: 'Inter, ui-sans-serif, system-ui, -apple-system, "Segoe UI", sans-serif',
        color: "#4f5b67",
        size: 11,
      },
      hoverlabel: { bgcolor: "#17202a", bordercolor: "#17202a", font: { color: "white" } },
      hovermode: "closest",
      legend: {
        orientation: "h",
        x: 0,
        xanchor: "left",
        y: 1.06,
        yanchor: "bottom",
        font: { size: 10 },
      },
      xaxis: { gridcolor: "#e8ebee", zerolinecolor: "#bdc5cc", automargin: true },
      yaxis: { gridcolor: "#e8ebee", zerolinecolor: "#bdc5cc", automargin: true },
      ...overrides,
    };
  }

  function pitchGroups(rows) {
    const groups = new Map();
    rows.forEach((row) => {
      if (!groups.has(row.pitch_type)) groups.set(row.pitch_type, []);
      groups.get(row.pitch_type).push(row);
    });
    return groups;
  }

  function pitchColor(pitchType) {
    return colors[pitchType] || "#64748b";
  }

  function paddedRange(rows, key, minimumSpan, padding) {
    const values = rows.map((row) => Number(row[key])).filter(Number.isFinite);
    if (!values.length) return undefined;
    const minimum = Math.min(...values);
    const maximum = Math.max(...values);
    const span = Math.max(maximum - minimum, minimumSpan);
    const center = (minimum + maximum) / 2;
    return [center - span / 2 - padding, center + span / 2 + padding];
  }

  function emptyChart(container, message) {
    if (window.Plotly) window.Plotly.purge(container);
    container.replaceChildren();
    const empty = document.createElement("p");
    empty.className = "chart-empty";
    empty.textContent = message;
    container.append(empty);
  }

  async function draw(container, traces, layout, emptyMessage) {
    if (!traces.length) {
      emptyChart(container, emptyMessage);
      return;
    }
    await window.Plotly.react(container, traces, layout, config);
  }

  function movementTraces(chart) {
    return [...pitchGroups(chart.points).entries()].map(([pitchType, rows]) => ({
      type: "scatter",
      mode: "markers",
      name: pitchType,
      x: rows.map((row) => row.horizontal_break),
      y: rows.map((row) => row.vertical_break),
      customdata: rows.map((row) => [row.pitch_name, row.velocity, row.spin_rate]),
      marker: {
        color: pitchColor(pitchType),
        size: 9,
        opacity: 0.72,
        line: { color: "white", width: 0.8 },
      },
      hovertemplate:
        "<b>%{customdata[0]}</b><br>HB: %{x:.1f} in.<br>IVB: %{y:.1f} in." +
        "<br>Velocity: %{customdata[1]:.1f} mph<br>Spin: %{customdata[2]:.0f} rpm<extra></extra>",
    }));
  }

  function velocityTraces(chart) {
    return [...pitchGroups(chart.rows).entries()].flatMap(([pitchType, rows]) => {
      const points = {
        type: "scatter",
        mode: "markers",
        name: pitchType,
        x: rows.map((row) => row.game_date),
        y: rows.map((row) => row.avg_velocity),
        customdata: rows.map((row) => [
          row.pitch_name,
          row.pitch_count,
          row.min_velocity,
          row.max_velocity,
        ]),
        marker: { color: pitchColor(pitchType), size: 7, opacity: 0.78 },
        hovertemplate:
          "<b>%{customdata[0]}</b><br>%{x|%b %d, %Y}<br>Average: %{y:.1f} mph" +
          "<br>Range: %{customdata[2]:.1f}–%{customdata[3]:.1f} mph" +
          "<br>Pitches: %{customdata[1]}<extra></extra>",
      };
      if (rows.length < 2) return [points];

      const dates = rows.map((row) => Date.parse(`${row.game_date}T00:00:00Z`));
      const firstDate = Math.min(...dates);
      const x = dates.map((date) => (date - firstDate) / 86400000);
      const y = rows.map((row) => Number(row.avg_velocity));
      const xMean = x.reduce((sum, value) => sum + value, 0) / x.length;
      const yMean = y.reduce((sum, value) => sum + value, 0) / y.length;
      const denominator = x.reduce((sum, value) => sum + (value - xMean) ** 2, 0);
      const slope = denominator
        ? x.reduce((sum, value, index) => sum + (value - xMean) * (y[index] - yMean), 0) /
          denominator
        : 0;
      const minimumX = Math.min(...x);
      const maximumX = Math.max(...x);
      const fitted = (value) => yMean + slope * (value - xMean);
      const trend = {
        type: "scatter",
        mode: "lines",
        name: `${pitchType} trend`,
        showlegend: false,
        hoverinfo: "skip",
        x: [new Date(firstDate + minimumX * 86400000), new Date(firstDate + maximumX * 86400000)],
        y: [fitted(minimumX), fitted(maximumX)],
        line: { color: pitchColor(pitchType), width: 3 },
        opacity: 0.38,
      };
      return [points, trend];
    });
  }

  function releaseTraces(chart) {
    return [...pitchGroups(chart.points).entries()].map(([pitchType, rows]) => ({
      type: "scatter",
      mode: "markers",
      name: pitchType,
      x: rows.map((row) => row.release_pos_x),
      y: rows.map((row) => row.release_pos_z),
      customdata: rows.map((row) => [row.pitch_name, row.game_date, row.release_extension]),
      marker: {
        color: pitchColor(pitchType),
        size: 9,
        opacity: 0.7,
        line: { color: "white", width: 0.8 },
      },
      hovertemplate:
        "<b>%{customdata[0]}</b><br>Horizontal: %{x:.2f} ft<br>Height: %{y:.2f} ft" +
        "<br>Extension: %{customdata[2]:.2f} ft<br>%{customdata[1]}<extra></extra>",
    }));
  }

  function locationTraces(chart) {
    return [...pitchGroups(chart.points).entries()].map(([pitchType, rows]) => ({
      type: "scatter",
      mode: "markers",
      name: pitchType,
      x: rows.map((row) => row.plate_x),
      y: rows.map((row) => row.plate_z),
      customdata: rows.map((row) => [row.pitch_name, row.count, row.description || "—"]),
      marker: {
        color: pitchColor(pitchType),
        size: 9,
        opacity: 0.68,
        line: { color: "white", width: 0.8 },
      },
      hovertemplate:
        "<b>%{customdata[0]}</b><br>Plate X: %{x:.2f} ft<br>Plate Z: %{y:.2f} ft" +
        "<br>Count: %{customdata[1]}<br>%{customdata[2]}<extra></extra>",
    }));
  }

  function countUsageTraces(chart) {
    const countOrder = ["0-0", "0-1", "0-2", "1-0", "1-1", "1-2", "2-0", "2-1", "2-2", "3-0", "3-1", "3-2"];
    const observedCounts = countOrder.filter((count) =>
      chart.rows.some((row) => row.count === count),
    );
    return [...pitchGroups(chart.rows).entries()].map(([pitchType, rows]) => {
      const lookup = new Map(rows.map((row) => [row.count, row]));
      return {
        type: "bar",
        name: pitchType,
        x: observedCounts,
        y: observedCounts.map((count) => lookup.get(count)?.usage_pct || 0),
        customdata: observedCounts.map((count) => [
          lookup.get(count)?.pitch_name || pitchType,
          lookup.get(count)?.pitch_count || 0,
        ]),
        marker: { color: pitchColor(pitchType) },
        hovertemplate:
          "<b>%{customdata[0]}</b><br>Count: %{x}<br>Usage: %{y:.1f}%" +
          "<br>Pitches: %{customdata[1]}<extra></extra>",
      };
    });
  }

  const inningMeasures = {
    velocity: { key: "avg_velocity", count: "velocity_count", unit: "mph", title: "Velocity" },
    hb: { key: "avg_hb", count: "hb_count", unit: "in.", title: "Horizontal Break" },
    ivb: { key: "avg_ivb", count: "ivb_count", unit: "in.", title: "Induced Vertical Break" },
  };

  async function renderInningCharts() {
    const measure = inningMeasures[inningMetricSelect.value];
    const showChange = inningDisplayMode.value === "change";

    // Dispose of Plotly's listeners before replacing the pitch-type cards.
    inningGrid.querySelectorAll(".plotly-chart").forEach((chart) => {
      if (window.Plotly) window.Plotly.purge(chart);
    });
    inningGrid.replaceChildren();

    if (!inningData.pitch_types.length) {
      const empty = document.createElement("p");
      empty.className = "inning-empty";
      empty.textContent = "No pitches with inning data are available for this sample.";
      inningGrid.append(empty);
      return;
    }

    // Rank by pitch count within the active filters, not by pitch name or code.
    const orderedPitches = [...inningData.pitch_types].sort(
      (a, b) =>
        b.pitch_count - a.pitch_count ||
        a.pitch_name.localeCompare(b.pitch_name) ||
        a.pitch_type.localeCompare(b.pitch_type),
    );
    // Use the latest observed inning across every pitch type for all x-axes.
    // Do not invent points where a particular pitch was no longer thrown.
    const maxInning = inningData.rows.reduce(
      (latest, row) => Math.max(latest, row.inning_pitched),
      1,
    );
    const charts = orderedPitches.map((pitch) => {
      const card = document.createElement("article");
      card.className = "chart-card";

      const heading = document.createElement("div");
      heading.className = "chart-card-heading";
      const name = document.createElement("h3");
      name.textContent = `${pitch.pitch_name} (${pitch.pitch_type})`;
      const sample = document.createElement("span");
      sample.textContent = `${pitch.pitch_count.toLocaleString("en-US")} PC`;
      heading.append(name, sample);

      const container = document.createElement("div");
      container.className = "plotly-chart inning-chart";
      container.setAttribute("role", "img");
      container.setAttribute(
        "aria-label",
        `${pitch.pitch_name}: ${measure.title} by inning of appearance`,
      );
      card.append(heading, container);
      inningGrid.append(card);

      const rows = inningData.rows
        .filter((row) => row.pitch_type === pitch.pitch_type)
        .sort((a, b) => a.inning_pitched - b.inning_pitched);
      const tracked = rows.filter(
        (row) => row[measure.key] !== null && row[measure.key] !== undefined,
      );
      if (!tracked.length) {
        return draw(container, [], baseLayout(), "No tracked pitches for this metric.");
      }

      const baselineInning = tracked[0].inning_pitched;
      const baseline = tracked[0][measure.key];
      const trace = {
        type: "scatter",
        mode: "lines+markers",
        name: pitch.pitch_type,
        x: tracked.map((row) => row.inning_pitched),
        y: tracked.map((row) =>
          showChange ? +(row[measure.key] - baseline).toFixed(1) : row[measure.key],
        ),
        customdata: tracked.map((row) => [
          row[measure.key],
          +(row[measure.key] - baseline).toFixed(1),
          row[measure.count],
          row.game_count,
          baselineInning,
        ]),
        marker: { color: pitchColor(pitch.pitch_type), size: 8 },
        line: { color: pitchColor(pitch.pitch_type), width: 2.5 },
        hovertemplate:
          "<b>" + pitch.pitch_name + "</b><br>Inning of appearance: %{x}" +
          "<br>Average: %{customdata[0]:.1f} " + measure.unit +
          "<br>Change: %{customdata[1]:+.1f} " + measure.unit +
          "<br>Tracked pitches: %{customdata[2]}" +
          "<br>Games: %{customdata[3]}" +
          "<br>Baseline inning: %{customdata[4]}<extra></extra>",
      };
      return draw(
        container,
        [trace],
        baseLayout({
          height: 280,
          margin: { l: 55, r: 16, t: 14, b: 38 },
          showlegend: false,
          xaxis: {
            title: { text: "Inning of Appearance", standoff: 3 },
            type: "linear",
            dtick: 1,
            range: [0.5, maxInning + 0.5],
            gridcolor: "#e8ebee",
          },
          yaxis: {
            title: showChange ? `Change (${measure.unit})` : `Average (${measure.unit})`,
            gridcolor: "#e8ebee",
            zeroline: showChange,
            zerolinecolor: "#9da7b0",
          },
        }),
        "No tracked pitches for this metric.",
      );
    });
    await Promise.all(charts);
  }

  function syncInningData(chart) {
    inningData = chart || { pitch_types: [], rows: [] };
    inningGrid.classList.remove("charts-unavailable");
    return renderInningCharts();
  }

  inningMetricSelect.addEventListener("change", () => {
    void renderInningCharts();
  });
  inningDisplayMode.addEventListener("change", () => {
    void renderInningCharts();
  });

  async function render(payload) {
    if (!window.Plotly) {
      showError("Plotly could not load. Check the internet connection and refresh the page.");
      return;
    }
    status.hidden = true;
    chartGrid.classList.remove("charts-unavailable");
    const charts = payload.charts;
    const zone = charts.location.strike_zone;
    const releaseXRange = paddedRange(charts.release_point.points, "release_pos_x", 2.4, 0.35);
    const releaseYRange = paddedRange(charts.release_point.points, "release_pos_z", 2.4, 0.35);
    await Promise.all([
      syncInningData(charts.inning_progression),
      draw(
        containers.movement,
        movementTraces(charts.movement),
        baseLayout({
          xaxis: { title: "Glove Side (−) / Arm Side (+), in.", gridcolor: "#e8ebee", zerolinecolor: "#9da7b0" },
          yaxis: { title: "Induced Vertical Break (in.)", gridcolor: "#e8ebee", zerolinecolor: "#9da7b0" },
        }),
        "No movement data are available for this sample.",
      ),
      draw(
        containers.velocity,
        velocityTraces(charts.velocity_trend),
        baseLayout({
          hovermode: "x unified",
          xaxis: { title: "Game Date", gridcolor: "#e8ebee", type: "date" },
          yaxis: { title: "Average Velocity (mph)", gridcolor: "#e8ebee" },
        }),
        "No velocity data are available for this sample.",
      ),
      draw(
        containers.release,
        releaseTraces(charts.release_point),
        baseLayout({
          xaxis: { title: "Horizontal Release (ft.)", range: releaseXRange, gridcolor: "#e8ebee" },
          yaxis: { title: "Release Height (ft.)", range: releaseYRange, gridcolor: "#e8ebee", scaleanchor: "x", scaleratio: 1 },
        }),
        "No release-point data are available for this sample.",
      ),
      draw(
        containers.location,
        locationTraces(charts.location),
        baseLayout({
          showlegend: true,
          shapes: [
            {
              type: "rect",
              x0: zone.left,
              x1: zone.right,
              y0: zone.bottom,
              y1: zone.top,
              line: { color: "#17202a", width: 3 },
              fillcolor: "rgba(122,0,25,0.035)",
              layer: "above",
            },
          ],
          xaxis: { title: "Horizontal Location (ft.)", range: [-3, 3], gridcolor: "#e8ebee" },
          yaxis: { title: "Vertical Location (ft.)", range: [0, 5.5], gridcolor: "#e8ebee", scaleanchor: "x", scaleratio: 1 },
        }),
        "No plate-location data are available for this sample.",
      ),
      draw(
        containers.countUsage,
        countUsageTraces(charts.usage_by_count),
        baseLayout({
          barmode: "stack",
          hovermode: "x unified",
          xaxis: { title: "Count", gridcolor: "#e8ebee", type: "category" },
          yaxis: { title: "Usage (%)", range: [0, 100], ticksuffix: "%", gridcolor: "#e8ebee" },
        }),
        "No count data are available for this sample.",
      ),
    ]);
  }

  function setLoading(isLoading) {
    if (!status) return;
    if (isLoading) {
      status.hidden = false;
      status.className = "chart-status";
      status.textContent = "Updating charts…";
    } else if (!status.classList.contains("chart-status-error")) {
      status.hidden = true;
      status.textContent = "";
    }
  }

  function showError(message) {
    if (!status) return;
    status.hidden = false;
    status.className = "chart-status chart-status-error";
    status.textContent = message;
    chartGrid.classList.add("charts-unavailable");
    inningGrid.classList.add("charts-unavailable");
  }

  window.SavantCharts = { render, setLoading, showError };
})();
