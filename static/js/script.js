/* Disaster Command — dashboard, SSE, glass globe, what-if simulator */

(() => {
  "use strict";

  // -----------------------------------------------------------------------
  // State
  // -----------------------------------------------------------------------
  const PREFS_KEY = "disaster_command_prefs_v1";

  const defaultPrefs = () => ({
    theme: "dark",
    accent: "blue",
    panels: { globe: true, alerts: true, chart: true, sim: true },
    filterRisk: "high",
    filterType: "all",
    filterState: "all",
  });

  const state = {
    regions: [],
    markers: {},
    chart: null,
    chartMax: 30,
    prefs: defaultPrefs(),
    // AP city names for state filter (matches seeded stations)
    apCities: new Set([
      "Visakhapatnam", "Vijayawada", "Rajahmundry", "Kakinada", "Nellore",
      "Tirupati", "Kurnool", "Anantapur", "Machilipatnam", "Ongole",
      "Srikakulam", "Eluru", "Araku", "Nallamala", "Kadapa", "Bhadrachalam",
    ]),
    tsCities: new Set([
      "Hyderabad", "Warangal", "Khammam", "Nizamabad", "Karimnagar",
      "Adilabad", "Nalgonda", "Bhadrachalam",
    ]),
  };

  // -----------------------------------------------------------------------
  // Helpers
  // -----------------------------------------------------------------------
  const $ = (sel) => document.querySelector(sel);
  const $$ = (sel) => Array.from(document.querySelectorAll(sel));

  function riskColor(risk) {
    const map = {
      critical: 0xff5c7a,
      high: 0xf5b942,
      medium: 0x5b8cff,
      low: 0x3ecf8e,
      none: 0x5a6a86,
    };
    return map[risk] || map.none;
  }

  function riskCss(risk) {
    const map = {
      critical: "#ff5c7a",
      high: "#f5b942",
      medium: "#5b8cff",
      low: "#3ecf8e",
      none: "#5a6a86",
    };
    return map[risk] || map.none;
  }

  // -----------------------------------------------------------------------
  // Three.js glass globe
  // -----------------------------------------------------------------------
  function initGlobe() {
    const container = $("#globeContainer");
    if (!container || typeof THREE === "undefined") return;

    const w = container.clientWidth || 600;
    const h = container.clientHeight || 420;

    const scene = new THREE.Scene();
    const camera = new THREE.PerspectiveCamera(42, w / h, 0.1, 100);
    camera.position.set(0, 0.15, 3.4);

    const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true });
    renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    renderer.setSize(w, h);
    renderer.setClearColor(0x000000, 0);
    container.appendChild(renderer.domElement);

    // Lighting for glass / physical materials
    scene.add(new THREE.AmbientLight(0x6a7aaa, 0.55));
    const key = new THREE.DirectionalLight(0xffffff, 0.95);
    key.position.set(4, 3, 5);
    scene.add(key);
    const rim = new THREE.DirectionalLight(0x7c6cff, 0.45);
    rim.position.set(-3, -1, -4);
    scene.add(rim);
    const fill = new THREE.PointLight(0x3ee0c5, 0.35, 12);
    fill.position.set(-2, 2, 3);
    scene.add(fill);

    // Glass sphere
    const globeGeo = new THREE.SphereGeometry(1.15, 64, 64);
    const globeMat = new THREE.MeshPhysicalMaterial({
      color: 0x1a2a4a,
      metalness: 0.05,
      roughness: 0.15,
      transmission: 0.55,
      transparent: true,
      opacity: 0.92,
      clearcoat: 1.0,
      clearcoatRoughness: 0.12,
      reflectivity: 0.5,
      side: THREE.FrontSide,
    });
    const globe = new THREE.Mesh(globeGeo, globeMat);
    scene.add(globe);

    // Subtle atmosphere shell
    const atmo = new THREE.Mesh(
      new THREE.SphereGeometry(1.2, 48, 48),
      new THREE.MeshBasicMaterial({
        color: 0x5b8cff,
        transparent: true,
        opacity: 0.07,
        side: THREE.BackSide,
      })
    );
    scene.add(atmo);

    // Latitude / longitude wire faint
    const wire = new THREE.Mesh(
      new THREE.SphereGeometry(1.152, 32, 24),
      new THREE.MeshBasicMaterial({
        color: 0x8b9bb8,
        wireframe: true,
        transparent: true,
        opacity: 0.08,
      })
    );
    scene.add(wire);

    const markerGroup = new THREE.Group();
    scene.add(markerGroup);

    function latLonToVec(lat, lon, radius) {
      const phi = ((90 - lat) * Math.PI) / 180;
      const theta = ((lon + 180) * Math.PI) / 180;
      return new THREE.Vector3(
        -radius * Math.sin(phi) * Math.cos(theta),
        radius * Math.cos(phi),
        radius * Math.sin(phi) * Math.sin(theta)
      );
    }

    function upsertMarker(region, risk) {
      const key = region.station_id;
      const color = riskColor(risk || "none");
      if (state.markers[key]) {
        state.markers[key].mesh.material.color.setHex(color);
        state.markers[key].risk = risk || "none";
        return;
      }
      const pos = latLonToVec(region.latitude, region.longitude, 1.18);
      const geo = new THREE.SphereGeometry(0.035, 16, 16);
      const mat = new THREE.MeshStandardMaterial({
        color,
        emissive: color,
        emissiveIntensity: 0.55,
        roughness: 0.35,
        metalness: 0.1,
      });
      const mesh = new THREE.Mesh(geo, mat);
      mesh.position.copy(pos);
      markerGroup.add(mesh);

      // Soft glow ring
      const ring = new THREE.Mesh(
        new THREE.RingGeometry(0.04, 0.07, 24),
        new THREE.MeshBasicMaterial({
          color,
          transparent: true,
          opacity: 0.35,
          side: THREE.DoubleSide,
        })
      );
      ring.position.copy(pos);
      ring.lookAt(0, 0, 0);
      markerGroup.add(ring);

      state.markers[key] = { mesh, ring, risk: risk || "none", baseScale: 1 };
    }

    // Expose for live updates
    window.__globeUpsert = upsertMarker;

    let t = 0;
    function animate() {
      requestAnimationFrame(animate);
      t += 0.008;
      globe.rotation.y += 0.0018;
      wire.rotation.y = globe.rotation.y;
      atmo.rotation.y = globe.rotation.y * 0.7;
      markerGroup.rotation.y = globe.rotation.y;

      // Pulse markers by risk
      Object.values(state.markers).forEach((m) => {
        const speed =
          m.risk === "critical" ? 0.18 : m.risk === "high" ? 0.12 : 0.06;
        const s = 1 + Math.sin(t / speed) * (m.risk === "critical" ? 0.35 : 0.18);
        m.mesh.scale.setScalar(s);
        if (m.ring) m.ring.material.opacity = 0.2 + (s - 1) * 0.8;
      });

      renderer.render(scene, camera);
    }
    animate();

    window.addEventListener("resize", () => {
      const nw = container.clientWidth;
      const nh = container.clientHeight;
      camera.aspect = nw / nh;
      camera.updateProjectionMatrix();
      renderer.setSize(nw, nh);
    });
  }

  // -----------------------------------------------------------------------
  // Chart.js telemetry
  // -----------------------------------------------------------------------
  function initChart() {
    const canvas = $("#telemetryChart");
    if (!canvas || typeof Chart === "undefined") return;

    const ctx = canvas.getContext("2d");
    const gradientRain = ctx.createLinearGradient(0, 0, 0, 220);
    gradientRain.addColorStop(0, "rgba(91, 140, 255, 0.35)");
    gradientRain.addColorStop(1, "rgba(91, 140, 255, 0)");

    const gradientWind = ctx.createLinearGradient(0, 0, 0, 220);
    gradientWind.addColorStop(0, "rgba(62, 224, 197, 0.3)");
    gradientWind.addColorStop(1, "rgba(62, 224, 197, 0)");

    state.chart = new Chart(ctx, {
      type: "line",
      data: {
        labels: [],
        datasets: [
          {
            label: "Rainfall (mm)",
            data: [],
            borderColor: "#5b8cff",
            backgroundColor: gradientRain,
            fill: true,
            tension: 0.35,
            pointRadius: 0,
            borderWidth: 2,
          },
          {
            label: "Wind (km/h)",
            data: [],
            borderColor: "#3ee0c5",
            backgroundColor: gradientWind,
            fill: true,
            tension: 0.35,
            pointRadius: 0,
            borderWidth: 2,
          },
          {
            label: "Seismic (Mw)",
            data: [],
            borderColor: "#f5b942",
            backgroundColor: "transparent",
            fill: false,
            tension: 0.35,
            pointRadius: 0,
            borderWidth: 2,
            yAxisID: "y1",
          },
        ],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        interaction: { mode: "index", intersect: false },
        plugins: {
          legend: {
            labels: {
              color: "#8b9bb8",
              boxWidth: 10,
              boxHeight: 10,
              font: { family: "Inter", size: 11, weight: "500" },
              padding: 16,
            },
          },
          tooltip: {
            backgroundColor: "rgba(12, 18, 32, 0.92)",
            titleFont: { family: "Inter", size: 12 },
            bodyFont: { family: "JetBrains Mono", size: 11 },
            borderColor: "rgba(255,255,255,0.08)",
            borderWidth: 1,
            padding: 10,
          },
        },
        scales: {
          x: {
            ticks: { color: "#5a6a86", font: { size: 10 }, maxTicksLimit: 8 },
            grid: { color: "rgba(255,255,255,0.04)" },
            border: { display: false },
          },
          y: {
            ticks: { color: "#5a6a86", font: { size: 10 } },
            grid: { color: "rgba(255,255,255,0.04)" },
            border: { display: false },
          },
          y1: {
            position: "right",
            ticks: { color: "#5a6a86", font: { size: 10 } },
            grid: { drawOnChartArea: false },
            border: { display: false },
          },
        },
      },
    });
  }

  function pushTelemetry(point) {
    if (!state.chart) return;
    const label = point.recorded_at
      ? new Date(point.recorded_at).toLocaleTimeString([], {
          hour: "2-digit",
          minute: "2-digit",
          second: "2-digit",
        })
      : "";
    const d = state.chart.data;
    d.labels.push(label);
    d.datasets[0].data.push(point.rainfall_mm ?? 0);
    d.datasets[1].data.push(point.wind_speed_kmh ?? 0);
    d.datasets[2].data.push(point.seismic_magnitude ?? 0);
    while (d.labels.length > state.chartMax) {
      d.labels.shift();
      d.datasets.forEach((ds) => ds.data.shift());
    }
    state.chart.update("none");
  }

  // -----------------------------------------------------------------------
  // Preferences (theme, accent, panels, filters) + localStorage
  // -----------------------------------------------------------------------
  function loadPrefs() {
    try {
      const raw = localStorage.getItem(PREFS_KEY);
      if (!raw) return;
      const parsed = JSON.parse(raw);
      state.prefs = {
        ...defaultPrefs(),
        ...parsed,
        panels: { ...defaultPrefs().panels, ...(parsed.panels || {}) },
      };
    } catch (_) {}
  }

  function savePrefs() {
    try {
      localStorage.setItem(PREFS_KEY, JSON.stringify(state.prefs));
    } catch (_) {}
  }

  function applyThemeAccent() {
    document.body.dataset.theme = state.prefs.theme || "dark";
    document.body.dataset.accent = state.prefs.accent || "blue";
    const t = $("#themeSelect");
    const a = $("#accentSelect");
    if (t) t.value = state.prefs.theme;
    if (a) a.value = state.prefs.accent;
  }

  function applyPanelVisibility() {
    const p = state.prefs.panels;
    ["globe", "alerts", "chart", "sim"].forEach((id) => {
      const el = document.querySelector(`[data-panel-id="${id}"]`);
      if (!el) return;
      el.classList.toggle("is-hidden", !p[id]);
      const cb = document.querySelector(`input[data-panel="${id}"]`);
      if (cb) cb.checked = !!p[id];
    });
    const layout = $("#mainLayout");
    if (layout) layout.classList.toggle("hide-globe", !p.globe);
  }

  function riskPassesFilter(risk) {
    const order = { none: 0, low: 1, medium: 2, high: 3, critical: 4 };
    const min = state.prefs.filterRisk;
    if (min === "all") return true;
    return (order[risk] || 0) >= (order[min] || 0);
  }

  function statePassesFilter(regionName) {
    const f = state.prefs.filterState;
    if (f === "all") return true;
    if (f === "ap") return state.apCities.has(regionName);
    if (f === "ts") return state.tsCities.has(regionName);
    return true;
  }

  function alertPassesFilters(a) {
    if (!riskPassesFilter(a.risk_level || "none")) return false;
    if (state.prefs.filterType !== "all" && a.disaster_type !== state.prefs.filterType) {
      return false;
    }
    if (!statePassesFilter(a.region_name || "")) return false;
    return true;
  }

  function reapplyAlertFilters() {
    const feed = $("#alertFeed");
    if (!feed) return;
    let visible = 0;
    feed.querySelectorAll(".alert-card").forEach((card) => {
      const a = {
        risk_level: card.dataset.risk,
        disaster_type: card.dataset.type,
        region_name: card.dataset.region,
      };
      const ok = alertPassesFilters(a);
      card.classList.toggle("is-filtered-out", !ok);
      if (ok) visible += 1;
    });
    const count = $("#alertCount");
    if (count) count.textContent = String(visible);
    // Empty state if nothing visible
    const anyCard = feed.querySelector(".alert-card");
    let empty = feed.querySelector(".empty-state");
    if (!anyCard || visible === 0) {
      if (!empty) {
        empty = document.createElement("div");
        empty.className = "empty-state";
        empty.innerHTML =
          "<p>No matching alerts</p><span>Adjust filters in Customize, or wait for new events</span>";
        feed.appendChild(empty);
      }
    } else if (empty) {
      empty.remove();
    }
  }

  function wirePrefs() {
    applyThemeAccent();
    applyPanelVisibility();

    const risk = $("#filterRisk");
    const type = $("#filterType");
    const st = $("#filterState");
    if (risk) risk.value = state.prefs.filterRisk;
    if (type) type.value = state.prefs.filterType;
    if (st) st.value = state.prefs.filterState;

    $("#themeSelect")?.addEventListener("change", (e) => {
      state.prefs.theme = e.target.value;
      applyThemeAccent();
      savePrefs();
    });
    $("#accentSelect")?.addEventListener("change", (e) => {
      state.prefs.accent = e.target.value;
      applyThemeAccent();
      savePrefs();
    });

    $$("input[data-panel]").forEach((cb) => {
      cb.addEventListener("change", () => {
        state.prefs.panels[cb.dataset.panel] = cb.checked;
        applyPanelVisibility();
        savePrefs();
      });
    });

    ["filterRisk", "filterType", "filterState"].forEach((id) => {
      $(`#${id}`)?.addEventListener("change", (e) => {
        const key = id === "filterRisk" ? "filterRisk" : id === "filterType" ? "filterType" : "filterState";
        state.prefs[key] = e.target.value;
        savePrefs();
        reapplyAlertFilters();
      });
    });

    const drawer = $("#prefsDrawer");
    const toggle = $("#prefsToggle");
    const close = $("#prefsClose");
    const openDrawer = (open) => {
      if (!drawer || !toggle) return;
      drawer.hidden = !open;
      toggle.setAttribute("aria-expanded", open ? "true" : "false");
    };
    toggle?.addEventListener("click", () => openDrawer(drawer.hidden));
    close?.addEventListener("click", () => openDrawer(false));
    document.addEventListener("keydown", (e) => {
      if (e.key === "Escape") openDrawer(false);
    });
  }

  // -----------------------------------------------------------------------
  // Alerts UI
  // -----------------------------------------------------------------------
  function renderAlert(a) {
    const feed = $("#alertFeed");
    if (!feed) return;
    const empty = feed.querySelector(".empty-state");
    if (empty) empty.remove();

    const card = document.createElement("article");
    card.className = "alert-card";
    card.dataset.risk = a.risk_level || "medium";
    card.dataset.type = a.disaster_type || "";
    card.dataset.region = a.region_name || "";
    if (!alertPassesFilters(a)) card.classList.add("is-filtered-out");

    const time = a.created_at
      ? new Date(a.created_at).toLocaleTimeString([], {
          hour: "2-digit",
          minute: "2-digit",
        })
      : "";
    card.innerHTML = `
      <div class="alert-bar"></div>
      <div class="alert-body">
        <h3>${escapeHtml(a.region_name)} · ${escapeHtml(a.disaster_type)}</h3>
        <p>${escapeHtml(a.message || "")}</p>
      </div>
      <div class="alert-meta">
        <span class="risk-badge ${escapeHtml(a.risk_level || "")}">${escapeHtml(a.risk_level || "")}</span>
        <span>${time}</span>
      </div>
    `;
    feed.prepend(card);
    while (feed.querySelectorAll(".alert-card").length > 20) {
      const cards = feed.querySelectorAll(".alert-card");
      cards[cards.length - 1].remove();
    }
    reapplyAlertFilters();
  }

  function escapeHtml(s) {
    return String(s)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  // -----------------------------------------------------------------------
  // SSE
  // -----------------------------------------------------------------------
  function connectSSE() {
    const indicator = $("#liveIndicator");
    const text = indicator?.querySelector(".live-text");
    const es = new EventSource("/stream/live");

    es.addEventListener("connected", () => {
      indicator?.classList.add("is-live");
      if (text) text.textContent = "Live";
    });

    es.addEventListener("sensor", (ev) => {
      try {
        const data = JSON.parse(ev.data);
        const region = state.regions.find((r) => r.station_id === data.station_id);
        const risk = data.prediction?.risk_level || "none";
        if (region && window.__globeUpsert) window.__globeUpsert(region, risk);
        pushTelemetry({
          recorded_at: data.recorded_at,
          rainfall_mm: data.features?.rainfall_mm,
          wind_speed_kmh: data.features?.wind_speed_kmh,
          seismic_magnitude: data.features?.seismic_magnitude,
        });
      } catch (_) {}
    });

    es.addEventListener("alert", (ev) => {
      try {
        renderAlert(JSON.parse(ev.data));
      } catch (_) {}
    });

    es.onerror = () => {
      indicator?.classList.remove("is-live");
      if (text) text.textContent = "Reconnecting";
    };
  }

  // -----------------------------------------------------------------------
  // Controls: voice, SMS, language
  // -----------------------------------------------------------------------
  async function refreshTts() {
    try {
      const r = await fetch("/api/tts/status");
      const s = await r.json();
      const btn = $("#voiceToggle");
      const st = $("#voiceState");
      if (!btn || !st) return;
      btn.classList.toggle("is-off", !s.enabled);
      btn.setAttribute("aria-pressed", s.enabled ? "true" : "false");
      st.textContent = s.enabled ? "On" : "Off";
      const sel = $("#langSelect");
      if (sel && s.language) sel.value = s.language;
    } catch (_) {}
  }

  async function refreshSms() {
    try {
      const r = await fetch("/api/sms/status");
      const s = await r.json();
      const btn = $("#smsToggle");
      const st = $("#smsState");
      if (!btn || !st) return;
      btn.classList.toggle("is-off", !s.enabled);
      btn.setAttribute("aria-pressed", s.enabled ? "true" : "false");
      st.textContent = s.enabled ? "On" : "Off";
    } catch (_) {}
  }

  function wireControls() {
    $("#voiceToggle")?.addEventListener("click", async () => {
      await fetch("/api/tts/toggle", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: "{}",
      });
      refreshTts();
    });

    $("#smsToggle")?.addEventListener("click", async () => {
      await fetch("/api/sms/toggle", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: "{}",
      });
      refreshSms();
    });

    $("#langSelect")?.addEventListener("change", async (e) => {
      await fetch("/api/tts/language", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ language: e.target.value }),
      });
      refreshTts();
    });
  }

  // -----------------------------------------------------------------------
  // What-if form
  // -----------------------------------------------------------------------
  function wireSimulator() {
    const form = $("#simForm");
    if (!form) return;

    const map = {
      rainfall_mm: "v_rain",
      wind_speed_kmh: "v_wind",
      seismic_magnitude: "v_seis",
      river_level_m: "v_river",
      temperature_c: "v_temp",
      humidity_pct: "v_hum",
      pressure_hpa: "v_pres",
      soil_moisture_pct: "v_soil",
    };

    form.querySelectorAll("input[type=range]").forEach((input) => {
      const id = map[input.name];
      const el = id ? document.getElementById(id) : null;
      const sync = () => {
        if (el) el.textContent = input.value;
      };
      input.addEventListener("input", sync);
      sync();
    });

    form.addEventListener("submit", async (e) => {
      e.preventDefault();
      const payload = {};
      form.querySelectorAll("input[type=range]").forEach((input) => {
        payload[input.name] = parseFloat(input.value);
      });
      const res = await fetch("/api/predict", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      const data = await res.json();
      const box = $("#simResult");
      if (!box) return;
      box.hidden = false;
      const conf = ((data.confidence || 0) * 100).toFixed(0);
      box.innerHTML = `Predicted <strong>${escapeHtml(
        data.disaster_type
      )}</strong> · risk <strong style="color:${riskCss(
        data.risk_level
      )}">${escapeHtml(data.risk_level)}</strong> · confidence ${conf}%`;
    });
  }

  // -----------------------------------------------------------------------
  // Bootstrap
  // -----------------------------------------------------------------------
  async function boot() {
    loadPrefs();
    wirePrefs();
    initGlobe();
    initChart();
    wireControls();
    wireSimulator();
    refreshTts();
    refreshSms();

    try {
      const r = await fetch("/api/regions");
      state.regions = await r.json();
      const rc = $("#regionCount");
      if (rc) rc.textContent = `${state.regions.length} stations`;
      state.regions.forEach((reg) => {
        if (window.__globeUpsert) window.__globeUpsert(reg, "none");
      });
    } catch (_) {}

    try {
      const r = await fetch("/api/alerts");
      const alerts = await r.json();
      alerts.reverse().forEach(renderAlert);
    } catch (_) {}

    try {
      const r = await fetch("/api/telemetry");
      const rows = await r.json();
      rows.forEach(pushTelemetry);
    } catch (_) {}

    connectSSE();
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", boot);
  } else {
    boot();
  }
})();
