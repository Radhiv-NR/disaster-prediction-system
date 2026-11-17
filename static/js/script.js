/* Regional disaster monitoring dashboard for live weather risk and operational alerts */

(() => {
  "use strict";

  // -----------------------------------------------------------------------
  // State
  // -----------------------------------------------------------------------
  const PREFS_KEY = "disaster_command_prefs_v2";

  const defaultPrefs = () => ({
    theme: "dark",
    accent: "amber",
    panels: { globe: true, alerts: true, chart: true, sim: true },
    filterRisk: "high",
    filterType: "all",
    filterState: "all",
  });

  const state = {
    regions: [],
    placeForecasts: [],
    placeSearch: "",
    placeState: "all",
    forecastSearchTimer: null,
    placeCatalogOffset: 0,
    placeCatalogTotal: 0,
    placeCatalogAllLoaded: false,
    markers: {},
    chart: null,
    chartMax: 30,
    prefs: defaultPrefs(),
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

    const stateMapGroup = new THREE.Group();
    scene.add(stateMapGroup);

    function latLonToVec(lat, lon, radius) {
      const phi = ((90 - lat) * Math.PI) / 180;
      const theta = ((lon + 180) * Math.PI) / 180;
      return new THREE.Vector3(
        -radius * Math.sin(phi) * Math.cos(theta),
        radius * Math.cos(phi),
        radius * Math.sin(phi) * Math.sin(theta)
      );
    }

    function addStateMap(name, coordinates, color, centerLat, centerLon) {
      const scale = 0.18;
      const center = latLonToVec(centerLat, centerLon, 1.155).normalize();
      const east = new THREE.Vector3(0, 1, 0).cross(center).normalize();
      const north = center.clone().cross(east).normalize();
      const shape = new THREE.Shape();
      coordinates.forEach(([lat, lon], index) => {
        const x = (lon - centerLon) * scale;
        const y = (lat - centerLat) * scale;
        if (index === 0) shape.moveTo(x, y);
        else shape.lineTo(x, y);
      });
      shape.closePath();

      const geometry = new THREE.ExtrudeGeometry(shape, {
        depth: 0.035,
        bevelEnabled: true,
        bevelSegments: 2,
        bevelSize: 0.008,
        bevelThickness: 0.008,
      });
      const basis = new THREE.Matrix4().makeBasis(east, north, center);
      geometry.applyMatrix4(basis);
      const material = new THREE.MeshPhysicalMaterial({
        color,
        emissive: color,
        emissiveIntensity: 0.22,
        metalness: 0.25,
        roughness: 0.3,
        transparent: true,
        opacity: 0.9,
        clearcoat: 0.8,
      });
      const mesh = new THREE.Mesh(geometry, material);
      mesh.position.copy(center.multiplyScalar(1.145));
      stateMapGroup.add(mesh);

      const borderPoints = coordinates.map(([lat, lon]) => {
        return latLonToVec(lat, lon, 1.19);
      });
      borderPoints.push(borderPoints[0].clone());
      const border = new THREE.Line(
        new THREE.BufferGeometry().setFromPoints(borderPoints),
        new THREE.LineBasicMaterial({ color, transparent: true, opacity: 0.95 })
      );
      stateMapGroup.add(border);

      const labelCanvas = document.createElement("canvas");
      labelCanvas.width = 256;
      labelCanvas.height = 64;
      const labelContext = labelCanvas.getContext("2d");
      labelContext.fillStyle = "rgba(7, 11, 20, 0.78)";
      labelContext.fillRect(4, 8, 248, 48);
      labelContext.font = "700 22px Manrope, sans-serif";
      labelContext.fillStyle = "#f2f6ff";
      labelContext.textAlign = "center";
      labelContext.textBaseline = "middle";
      labelContext.fillText(name, 128, 32);
      const label = new THREE.Sprite(
        new THREE.SpriteMaterial({
          map: new THREE.CanvasTexture(labelCanvas),
          transparent: true,
          depthTest: false,
        })
      );
      label.scale.set(0.68, 0.17, 1);
      label.position.copy(latLonToVec(centerLat, centerLon, 1.33));
      label.position.y += name === "TELANGANA" ? 0.16 : -0.16;
      stateMapGroup.add(label);
    }

    addStateMap(
      "ANDHRA PRADESH",
      [[18.4, 83.9], [17.8, 83.2], [17.0, 82.4], [16.1, 81.3], [15.0, 80.0], [14.0, 79.8], [13.5, 80.2], [13.7, 79.0], [15.0, 79.1], [16.2, 79.5], [17.0, 80.2], [18.0, 82.0]],
      0x3ee0c5,
      16.2,
      80.8
    );
    addStateMap(
      "TELANGANA",
      [[19.9, 78.3], [19.4, 79.6], [18.8, 80.4], [18.2, 81.0], [17.1, 81.1], [16.3, 80.3], [16.2, 79.5], [15.9, 78.5], [16.8, 77.2], [17.7, 77.0], [18.4, 77.5], [19.0, 77.8]],
      0xf5b942,
      17.9,
      79.2
    );

    stateMapGroup.rotation.y = Math.PI;
    globe.rotation.y = Math.PI;
    wire.rotation.y = Math.PI;
    atmo.rotation.y = Math.PI;
    markerGroup.rotation.y = Math.PI;

    function upsertMarker(region, risk) {
      const key = region.station_id;
      const color = riskColor(risk || "none");
      if (state.markers[key]) {
        state.markers[key].mesh.material.color.setHex(color);
        state.markers[key].mesh.material.emissive.setHex(color);
        state.markers[key].risk = risk || "none";
        state.markers[key].label.material.color.setHex(color);
        renderGlobePlacesList();
        return;
      }
      const pos = latLonToVec(region.latitude, region.longitude, 1.18);
      const geo = new THREE.SphereGeometry(0.045, 16, 16);
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

      const labelCanvas = document.createElement("canvas");
      labelCanvas.width = 320;
      labelCanvas.height = 48;
      const labelContext = labelCanvas.getContext("2d");
      labelContext.font = "600 18px Manrope, sans-serif";
      labelContext.fillStyle = "#f2f6ff";
      labelContext.textAlign = "center";
      labelContext.textBaseline = "middle";
      labelContext.fillText(region.name, 160, 24);
      const label = new THREE.Sprite(
        new THREE.SpriteMaterial({
          map: new THREE.CanvasTexture(labelCanvas),
          color,
          transparent: true,
          depthTest: false,
        })
      );
      label.scale.set(0.34, 0.052, 1);
      label.position.copy(pos.clone().normalize().multiplyScalar(1.29));
      markerGroup.add(label);

      state.markers[key] = { mesh, ring, label, risk: risk || "none", baseScale: 1 };
      renderGlobePlacesList();
    }

    function renderGlobePlacesList() {
      const list = $("#globePlaceList");
      const count = $("#globePlaceCount");
      if (!list || !state.regions.length) return;
      if (count) count.textContent = String(state.regions.length);
      list.innerHTML = state.regions
        .slice()
        .sort((left, right) => {
          const riskOrder = { critical: 4, high: 3, medium: 2, low: 1, none: 0 };
          const leftRisk = riskOrder[state.markers[left.station_id]?.risk || "none"];
          const rightRisk = riskOrder[state.markers[right.station_id]?.risk || "none"];
          return rightRisk - leftRisk || left.state.localeCompare(right.state) || left.name.localeCompare(right.name);
        })
        .map((region) => {
          const risk = state.markers[region.station_id]?.risk || "none";
          const stateCode = region.state === "Andhra Pradesh" ? "AP" : "TS";
          return `<div class="globe-place-row"><span class="globe-place-dot ${escapeHtml(risk)}"></span><span class="globe-place-name">${escapeHtml(region.name)}</span><span class="globe-place-state">${stateCode}</span><span class="globe-place-risk-text">${escapeHtml(risk)}</span></div>`;
        })
        .join("");
    }

      window.__renderGlobePlacesList = renderGlobePlacesList;

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
      stateMapGroup.rotation.y = globe.rotation.y;

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
              font: { family: "Manrope", size: 11, weight: "500" },
              padding: 16,
            },
          },
          tooltip: {
            backgroundColor: "rgba(12, 18, 32, 0.92)",
            titleFont: { family: "Manrope", size: 12 },
            bodyFont: { family: "IBM Plex Mono", size: 11 },
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
        accent: parsed.accent === "blue" ? "lime" : parsed.accent,
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
    const region = state.regions.find((item) => item.name === regionName);
    if (!region) return true;
    return f === "ap" ? region.state === "Andhra Pradesh" : region.state === "Telangana";
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
    const activeMetric = $("#activeAlertMetric");
    if (activeMetric) activeMetric.textContent = String(visible);
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
    refreshSmsPreview();
  }

  function escapeHtml(s) {
    return String(s)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  async function readJsonResponse(response) {
    const text = await response.text();
    try {
      return text ? JSON.parse(text) : {};
    } catch (_) {
      throw new Error(`Server returned an invalid response (${response.status})`);
    }
  }

  function renderPlaceForecasts(rows) {
    const body = $("#placeForecasts");
    const status = $("#forecastStatus");
    if (!body) return;
    state.placeForecasts = rows;
    const search = state.placeSearch.trim().toLowerCase();
    const filteredRows = rows.filter((row) => {
      const matchesSearch = !search || String(row.region_name || "").toLowerCase().includes(search);
      const matchesState = state.placeState === "all" || row.state === state.placeState;
      return matchesSearch && matchesState;
    });
    if (!filteredRows.length) {
      body.innerHTML = '<tr><td colspan="5" class="table-message">No place data available</td></tr>';
      if (status) status.textContent = `0 of ${rows.length} places`;
      return;
    }
    body.innerHTML = filteredRows.map((row) => {
      const weather = row.weather || {};
      const prediction = row.prediction || {};
      const risk = prediction.risk_level || "unknown";
      const sourceClass = row.weather_source === "live weather" ? "live" : "synthetic";
      const temperature = Number.isFinite(Number(weather.temperature_c)) ? `${Number(weather.temperature_c).toFixed(1)}°C` : "Unavailable";
      const humidity = Number.isFinite(Number(weather.humidity_pct)) ? `${Number(weather.humidity_pct).toFixed(0)}% humidity` : "Humidity unavailable";
      const rainfall = Number.isFinite(Number(weather.rainfall_mm)) ? `${Number(weather.rainfall_mm).toFixed(1)} mm rain` : "Rain unavailable";
      const wind = Number.isFinite(Number(weather.wind_speed_kmh)) ? `${Number(weather.wind_speed_kmh).toFixed(1)} km/h wind` : "Wind unavailable";
      return `<tr>
        <td>${escapeHtml(row.region_name)}<div class="place-state">${escapeHtml(row.state)}</div></td>
        <td class="place-weather"><strong>${temperature}</strong> · ${humidity} · ${rainfall} · ${wind}</td>
        <td><span class="place-prediction">${escapeHtml(prediction.disaster_type || "none")}</span><span class="place-risk ${escapeHtml(risk)}">${escapeHtml(risk)}</span></td>
        <td>${prediction.disaster_type === "unavailable" ? "Unavailable" : `${((prediction.confidence || 0) * 100).toFixed(0)}%`}</td>
        <td class="place-source ${sourceClass}">${escapeHtml(row.weather_source || "unknown")}</td>
      </tr>`;
    }).join("");
    if (status) {
      const total = state.placeCatalogTotal || rows.length;
      status.textContent = `${filteredRows.length} of ${total || rows.length} places · updated ${new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}`;
    }
    $("#loadMorePlaces")?.toggleAttribute("hidden", rows.length >= state.placeCatalogTotal);
  }

  function wirePlaceFilters() {
    $("#placeSearch")?.addEventListener("input", (event) => {
      state.placeSearch = event.target.value;
      state.placeCatalogOffset = 0;
      state.placeCatalogAllLoaded = false;
      $("#clearPlaceSearch")?.classList.toggle("is-visible", Boolean(state.placeSearch));
      window.clearTimeout(state.forecastSearchTimer);
      state.forecastSearchTimer = window.setTimeout(() => {
        refreshPlaceForecasts();
      }, 350);
    });
    $("#placeStateFilter")?.addEventListener("change", (event) => {
      state.placeState = event.target.value;
      state.placeCatalogOffset = 0;
      state.placeCatalogAllLoaded = false;
      refreshPlaceForecasts();
    });
    $("#clearPlaceSearch")?.addEventListener("click", () => {
      const input = $("#placeSearch");
      if (!input) return;
      input.value = "";
      state.placeSearch = "";
      state.placeCatalogOffset = 0;
      state.placeCatalogAllLoaded = false;
      $("#clearPlaceSearch")?.classList.remove("is-visible");
      refreshPlaceForecasts();
      input.focus();
    });
    $("#loadMorePlaces")?.addEventListener("click", () => {
      state.placeCatalogOffset += 100;
      refreshPlaceForecasts(true);
    });
    $("#loadAllPlaces")?.addEventListener("click", async (event) => {
      const button = event.currentTarget;
      button.disabled = true;
      state.placeCatalogOffset = 0;
      state.placeForecasts = [];
      state.placeCatalogAllLoaded = false;
      const status = $("#forecastStatus");
      try {
        while (state.placeCatalogOffset < state.placeCatalogTotal || state.placeCatalogOffset === 0) {
          await refreshPlaceForecasts(Boolean(state.placeForecasts.length));
          if (state.placeCatalogOffset + 100 >= state.placeCatalogTotal) break;
          state.placeCatalogOffset += 100;
          if (status) status.textContent = `Loading live weather · ${state.placeCatalogOffset.toLocaleString()} of ${state.placeCatalogTotal.toLocaleString()} places`;
        }
        if (status) status.textContent = `${state.placeForecasts.length.toLocaleString()} places · live weather loaded`;
        state.placeCatalogAllLoaded = true;
      } finally {
        button.disabled = false;
      }
    });
  }

  async function refreshPlaceForecasts(append = false) {
    try {
      const search = String(state.placeSearch || "").trim();
      const selectedState = state.placeState === "all" ? "" : state.placeState;
      const endpoint = `/api/place-predictions?${search
        ? `q=${encodeURIComponent(search)}&state=${encodeURIComponent(selectedState)}&limit=100&offset=${state.placeCatalogOffset}`
        : `state=${encodeURIComponent(selectedState)}&limit=100&offset=${state.placeCatalogOffset}`}`;
      const response = await fetch(endpoint);
      if (!response.ok) throw new Error("forecast request failed");
      const payload = await response.json();
      if (search) {
        state.placeCatalogTotal = payload.total;
        renderPlaceForecasts(append ? state.placeForecasts.concat(payload.places) : payload.places);
      } else {
        state.placeCatalogTotal = payload.total;
        const places = payload.places;
        renderPlaceForecasts(append ? state.placeForecasts.concat(places) : places);
      }
    } catch (_) {
      const status = $("#forecastStatus");
      if (status) status.textContent = "Forecast unavailable";
    }
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
  // Controls: offline Mac alerts, SMS, language
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
      const label = btn.querySelector(".pill-label");
      if (label) label.textContent = "SMS";
      btn.title = s.ready ? "Toggle SMS alerts" : "SMS setup required: modem and recipients";
      btn.classList.toggle("is-off", !s.enabled);
      btn.setAttribute("aria-pressed", s.enabled ? "true" : "false");
      st.textContent = s.ready ? (s.enabled ? "On" : "Off") : "Setup";
    } catch (_) {}
  }

  async function refreshMacAlerts() {
    try {
      const r = await fetch("/api/macos-notification/status");
      const s = await r.json();
      const btn = $("#macAlertsToggle");
      const st = $("#macAlertsState");
      if (!btn || !st) return;
      btn.title = s.ready ? "Toggle offline Mac alerts" : "Available only on macOS";
      btn.classList.toggle("is-off", !s.enabled);
      btn.setAttribute("aria-pressed", s.enabled ? "true" : "false");
      st.textContent = s.ready ? (s.enabled ? "On" : "Off") : "Unavailable";
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

    $("#macAlertsToggle")?.addEventListener("click", async () => {
      await fetch("/api/macos-notification/toggle", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: "{}",
      });
      refreshMacAlerts();
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

  function wireModuleNavigation() {
    const links = $$(".module-nav a");
    const sections = links
      .map((link) => document.querySelector(link.getAttribute("href")))
      .filter(Boolean);
    if (!links.length || !sections.length) return;

    const showSection = (id, updateUrl = true) => {
      const active = sections.find((section) => section.id === id) || sections[0];
      links.forEach((link) => {
        const selected = link.getAttribute("href") === `#${active.id}`;
        link.classList.toggle("module-nav-active", selected);
        if (selected) link.setAttribute("aria-current", "page");
        else link.removeAttribute("aria-current");
      });
      if (updateUrl && window.location.hash !== `#${active.id}`) {
        window.history.pushState({}, "", `#${active.id}`);
      }
      window.dispatchEvent(new Event("resize"));
      window.setTimeout(() => {
        document.querySelectorAll(".state-map").forEach((container) => {
          container._stateMap?.invalidateSize();
        });
      }, 280);
      if (updateUrl) active.scrollIntoView({ behavior: "smooth", block: "start" });
    };

    links.forEach((link) => link.addEventListener("click", (event) => {
      event.preventDefault();
      showSection(link.getAttribute("href").slice(1));
    }));
    window.addEventListener("popstate", () => showSection(window.location.hash.slice(1), false));
    if (!window.location.hash) window.scrollTo({ top: 0, behavior: "instant" });
    showSection(window.location.hash.slice(1), false);
  }

  async function initStateMaps() {
    const states = [
      { name: "Andhra Pradesh", mapId: "apMap", countId: "apMapCount", labelsId: "apMapLabels" },
      { name: "Telangana", mapId: "tsMap", countId: "tsMapCount", labelsId: "tsMapLabels" },
      { name: "Andhra Pradesh", mapId: "riskApMap", countId: "riskApMapCount", labelsId: "riskApMapLabels" },
      { name: "Telangana", mapId: "riskTsMap", countId: "riskTsMapCount", labelsId: "riskTsMapLabels" },
    ];
    const bounds = {
      "Andhra Pradesh": [[12.5, 76.5], [19.5, 85.5]],
      Telangana: [[15.5, 77.0], [20.2, 81.5]],
    };
    if (!window.L) {
      document.querySelectorAll(".state-map").forEach((container) => {
        container.textContent = "Map library unavailable. Check your internet connection.";
      });
      return;
    }
    try {
      const response = await fetch("/api/place-map");
      const catalog = await response.json();
      for (const stateMap of states) {
        const places = catalog.filter((place) => place.state === stateMap.name);
        try {
        const count = document.getElementById(stateMap.countId);
        if (count) count.textContent = `${places.length.toLocaleString()} places`;
        const labels = document.getElementById(stateMap.labelsId);
        const labelStep = Math.max(1, Math.floor(places.length / 10));
        places.filter((_, index) => index % labelStep === 0).slice(0, 10).forEach((place) => {
          const label = document.createElement("span");
          label.textContent = place.name;
          labels?.appendChild(label);
        });
        const container = document.getElementById(stateMap.mapId);
        if (!container) {
          continue;
        }
        const map = window.L.map(container, { zoomControl: true, scrollWheelZoom: false });
        window.L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
          attribution: "&copy; OpenStreetMap contributors",
          maxZoom: 18,
        }).addTo(map);
        map.fitBounds(bounds[stateMap.name]);
        places.forEach((place) => {
          const marker = window.L.circleMarker([place.latitude, place.longitude], {
            radius: 3,
            color: "#e7a84d",
            fillColor: "#e7a84d",
            fillOpacity: 0.8,
            weight: 0,
          }).addTo(map);
          marker.bindPopup(`<strong>${escapeHtml(place.name)}</strong><div>Loading live weather...</div>`);
          marker.on("click", async () => {
            marker.openPopup();
            try {
              const weatherResponse = await fetch(`/api/weather?place_id=${encodeURIComponent(place.geoname_id)}`);
              const weather = await weatherResponse.json();
              if (!weatherResponse.ok) throw new Error(weather.error || "Weather unavailable");
              marker.setPopupContent(`<strong>${escapeHtml(place.name)}</strong><div>${weather.temperature_c.toFixed(1)}°C · ${weather.humidity_pct.toFixed(0)}% humidity · ${weather.wind_speed_kmh.toFixed(1)} km/h wind</div>`);
            } catch (_) {
              marker.setPopupContent(`<strong>${escapeHtml(place.name)}</strong><div>Live weather unavailable</div>`);
            }
          });
        });
        container._stateMap = map;
        } catch (_) {
          const count = document.getElementById(stateMap.countId);
          if (count) count.textContent = "Unavailable";
        }
      }
    } catch (_) {
      states.forEach((stateMap) => {
        const count = document.getElementById(stateMap.countId);
        if (count) count.textContent = "Unavailable";
      });
    }
  }

  function wireSmsBroadcast() {
    const form = $("#smsBroadcastForm");
    if (!form) return;
    form.addEventListener("submit", async (event) => {
      event.preventDefault();
      const status = $("#smsBroadcastStatus");
      const button = form.querySelector("button[type=submit]");
      if (status) status.textContent = "Sending...";
      if (button) button.disabled = true;
      try {
        const response = await fetch("/api/sms/upload", {
          method: "POST",
          body: new FormData(form),
        });
        const data = await readJsonResponse(response);
        if (!response.ok) throw new Error(data.error || "SMS upload failed");
        const result = data.message || {};
        if (status) {
          status.textContent = result.sent != null
            ? `${data.uploaded} recipients saved · ${result.sent} messages sent`
            : "Recipients saved; SMS could not be sent";
        }
        form.reset();
        loadSmsRecipients();
      } catch (error) {
        if (status) status.textContent = error.message;
      } finally {
        if (button) button.disabled = false;
      }
    });

    $("#smsDemoForm")?.addEventListener("submit", async (event) => {
      event.preventDefault();
      const messageInput = $("#smsDemoMessage");
      const status = $("#smsDemoStatus");
      const button = event.currentTarget.querySelector("button[type=submit]");
      if (status) status.textContent = "Sending test...";
      if (button) button.disabled = true;
      try {
        const response = await fetch("/api/sms/demo", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ message: messageInput.value.trim() }),
        });
        const data = await readJsonResponse(response);
        if (!response.ok) throw new Error(data.error || "Test SMS failed");
        const result = data.message || {};
        if (status) {
          status.textContent = result.sent > 0
            ? `${result.sent} of ${data.recipients} test messages sent`
            : result.reason === "modem_not_connected"
              ? "Modem not connected: plug in the SIM7600 and check GSM_PORT"
              : result.reason === "modem_connection_failed"
              ? `Modem connection failed: ${result.error || "check the USB modem"}`
              : `Test not sent: ${result.reason || "modem unavailable"}`;
        }
      } catch (error) {
        if (status) status.textContent = error.message;
      } finally {
        if (button) button.disabled = false;
      }
    });

    $("#smsRecipientForm")?.addEventListener("submit", async (event) => {
      event.preventDefault();
      const input = $("#smsRecipientNumber");
      const number = input?.value.trim();
      if (!number) return;
      const response = await fetch("/api/sms/recipients", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ phone_number: number }),
      });
      const data = await response.json();
      if (!response.ok) {
        const demoStatus = $("#smsDemoStatus");
        if (demoStatus) demoStatus.textContent = data.error || "Unable to add number";
        return;
      }
      input.value = "";
      loadSmsRecipients();
    });
  }

  async function loadSmsRecipients() {
    const list = $("#smsRecipientList");
    const count = $("#smsRecipientCount");
    if (!list) return;
    try {
      const response = await fetch("/api/sms/recipients");
      const data = await response.json();
      const recipients = data.recipients || [];
      if (count) count.textContent = `${recipients.length} number${recipients.length === 1 ? "" : "s"}`;
      list.innerHTML = recipients.length
        ? recipients.map((number) => `<div class="sms-recipient"><span>${escapeHtml(number)}</span><button type="button" data-remove-number="${escapeHtml(number)}" aria-label="Remove ${escapeHtml(number)}" title="Remove number">×</button></div>`).join("")
        : '<span class="panel-meta">No saved numbers</span>';
      list.querySelectorAll("[data-remove-number]").forEach((button) => {
        button.addEventListener("click", async () => {
          await fetch(`/api/sms/recipients/${encodeURIComponent(button.dataset.removeNumber)}`, { method: "DELETE" });
          loadSmsRecipients();
        });
      });
    } catch (_) {
      list.innerHTML = '<span class="panel-meta">Recipients unavailable</span>';
    }
  }

  async function refreshSmsPreview() {
    const preview = $("#smsAutoMessage");
    if (!preview) return;
    try {
      const response = await fetch("/api/sms/preview");
      const data = await response.json();
      preview.textContent = response.ok ? data.message : "No active disaster alert";
    } catch (_) {
      preview.textContent = "Alert message unavailable";
    }
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
    wireModuleNavigation();
    initStateMaps();
    wireSmsBroadcast();
    wireSimulator();
    wirePlaceFilters();
    refreshTts();
    refreshSms();
    refreshMacAlerts();
    refreshSmsPreview();
    loadSmsRecipients();
    refreshPlaceForecasts();
    window.setInterval(() => {
      if (!state.placeCatalogAllLoaded) refreshPlaceForecasts();
    }, 5 * 60 * 1000);

    try {
      const r = await fetch("/api/regions");
      state.regions = await r.json();
      if (window.__renderGlobePlacesList) window.__renderGlobePlacesList();
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
