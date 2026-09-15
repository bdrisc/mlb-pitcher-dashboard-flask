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
    performance: document.querySelector("#performance-chart"),
  };
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
    return [...pitchGroups(chart.rows).entries()].map(([pitchType, rows]) => ({
      type: "scatter",
      mode: "lines+markers",
      name: pitchType,
      x: rows.map((row) => row.game_date),
      y: rows.map((row) => row.avg_velocity),
      customdata: rows.map((row) => [
        row.pitch_name,
        row.pitch_count,
        row.min_velocity,
        row.max_velocity,
      ]),
      line: { color: pitchColor(pitchType), width: 2.3 },
      marker: { color: pitchColor(pitchType), size: 7 },
      hovertemplate:
        "<b>%{customdata[0]}</b><br>%{x|%b %d, %Y}<br>Average: %{y:.1f} mph" +
        "<br>Range: %{customdata[2]:.1f}–%{customdata[3]:.1f} mph" +
        "<br>Pitches: %{customdata[1]}<extra></extra>",
    }));
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

  function performanceTraces(chart) {
    const metrics = [
      ["Whiff%", "whiff_pct", "#7a0019"],
      ["CSW%", "csw_pct", "#b59a57"],
      ["Zone%", "zone_pct", "#18775a"],
      ["Chase%", "chase_pct", "#2f6fed"],
    ];
    const labels = chart.rows.map((row) => row.pitch_type);
    return metrics.map(([label, key, color]) => ({
      type: "bar",
      name: label,
      x: labels,
      y: chart.rows.map((row) => row[key]),
      customdata: chart.rows.map((row) => [row.pitch_name, row.pitch_count]),
      marker: { color },
      hovertemplate:
        `<b>%{customdata[0]}</b><br>${label}: %{y:.1f}%` +
        "<br>Pitches: %{customdata[1]}<extra></extra>",
    }));
  }

  async function render(payload) {
    if (!window.Plotly) {
      showError("Plotly could not load. Check the internet connection and refresh the page.");
      return;
    }
    status.hidden = true;
    chartGrid.classList.remove("charts-unavailable");
    const charts = payload.charts;
    const zone = charts.location.strike_zone;
    await Promise.all([
      draw(
        containers.movement,
        movementTraces(charts.movement),
        baseLayout({
          xaxis: { title: "Horizontal break (in.)", gridcolor: "#e8ebee", zerolinecolor: "#9da7b0" },
          yaxis: { title: "Induced vertical break (in.)", gridcolor: "#e8ebee", zerolinecolor: "#9da7b0" },
        }),
        "No movement data are available for this sample.",
      ),
      draw(
        containers.velocity,
        velocityTraces(charts.velocity_trend),
        baseLayout({
          hovermode: "x unified",
          xaxis: { title: "Game date", gridcolor: "#e8ebee", type: "date" },
          yaxis: { title: "Average velocity (mph)", gridcolor: "#e8ebee" },
        }),
        "No velocity data are available for this sample.",
      ),
      draw(
        containers.release,
        releaseTraces(charts.release_point),
        baseLayout({
          xaxis: { title: "Horizontal release (ft.)", gridcolor: "#e8ebee" },
          yaxis: { title: "Release height (ft.)", gridcolor: "#e8ebee", scaleanchor: "x", scaleratio: 1 },
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
              line: { color: "#17202a", width: 2 },
              fillcolor: "rgba(122,0,25,0.025)",
              layer: "below",
            },
          ],
          xaxis: { title: "Horizontal location (ft.)", range: [-2.2, 2.2], gridcolor: "#e8ebee" },
          yaxis: { title: "Vertical location (ft.)", range: [0.5, 4.8], gridcolor: "#e8ebee", scaleanchor: "x", scaleratio: 1 },
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
      draw(
        containers.performance,
        performanceTraces(charts.pitch_performance),
        baseLayout({
          barmode: "group",
          hovermode: "x unified",
          xaxis: { title: "Pitch type", gridcolor: "#e8ebee", type: "category" },
          yaxis: { title: "Rate (%)", rangemode: "tozero", ticksuffix: "%", gridcolor: "#e8ebee" },
        }),
        "No performance data are available for this sample.",
      ),
    ]);
  }

  function setLoading(isLoading) {
    if (!status) return;
    if (isLoading) {
      status.hidden = false;
      status.className = "chart-status";
      status.textContent = "Updating all six charts…";
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
  }

  window.SavantCharts = { render, setLoading, showError };
})();
