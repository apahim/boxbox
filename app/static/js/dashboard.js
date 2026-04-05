/* Dashboard — fetches data from API and renders charts/maps/tables */
(function() {
    var meta = document.getElementById("session-meta");
    if (!meta) return;
    var apiBase = meta.dataset.apiBase;
    var mapkitToken = meta.dataset.mapkitToken;
    var shareToken = meta.dataset.shareToken || "";

    function api(path) {
        var url = apiBase + path;
        if (shareToken) url += (url.indexOf("?") !== -1 ? "&" : "?") + "share_token=" + shareToken;
        return fetch(url, { credentials: "same-origin" })
            .then(function(r) {
                if (!r.ok) return null;
                return r.json();
            })
            .catch(function() { return null; });
    }

    function formatLaptime(seconds) {
        var mins = Math.floor(seconds / 60);
        var secs = (seconds % 60).toFixed(3);
        if (secs < 10) secs = "0" + secs;
        return mins + ":" + secs;
    }

    // Weather icon from WMO code
    function weatherIcon(code) {
        if (code === 0) return "bi-sun";
        if (code <= 2) return "bi-cloud-sun";
        if (code === 3) return "bi-clouds";
        if (code === 45 || code === 48) return "bi-cloud-fog";
        if (code >= 51 && code <= 57) return "bi-cloud-drizzle";
        if (code >= 80 && code <= 82) return "bi-cloud-rain-heavy";
        if (code >= 61 && code <= 67) return "bi-cloud-rain";
        if (code >= 71 && code <= 86) return "bi-cloud-snow";
        if (code >= 95) return "bi-cloud-lightning-rain";
        return "bi-cloud";
    }

    // Icon map for coaching action items
    var ICON_MAP = {
        target: "&#9678;", consistency: "&#8651;", "trending-up": "&#9650;",
        "trending-down": "&#9660;", zap: "&#9889;", brake: "&#9632;", check: "&#10003;"
    };

    // ---- Tab lazy loading ----
    var tabsLoaded = { overview: false, deepdive: false, raceline: false, corners: false };
    var speedMapRef = null, brakingMapRef = null, sectorMapRef = null;
    var lapList = [];

    // Load overview immediately
    loadOverview();

    // Tab change handler
    var tabs = document.getElementById("dashboardTabs");
    if (tabs) {
        tabs.addEventListener("shown.bs.tab", function(event) {
            var target = event.target.id;
            if (target === "deepdive-tab" && !tabsLoaded.deepdive) loadDeepDive();
            if (target === "raceline-tab" && !tabsLoaded.raceline) loadRaceline();
            if (target === "corners-tab" && !tabsLoaded.corners) loadCorners();

            // Resize Plotly charts in newly shown tab
            var pane = document.querySelector(event.target.dataset.bsTarget);
            if (pane) {
                var plots = pane.querySelectorAll(".js-plotly-plot");
                plots.forEach(function(div) { Plotly.Plots.resize(div); });
                setTimeout(function() { window.dispatchEvent(new Event("resize")); }, 100);
            }
            history.replaceState(null, null, event.target.dataset.bsTarget);
        });

        // Activate tab from URL hash
        var hash = window.location.hash;
        if (hash) {
            var tabBtn = tabs.querySelector('button[data-bs-target="' + hash + '"]');
            if (tabBtn) new bootstrap.Tab(tabBtn).show();
        }
    }

    // ---- Overview ----
    function loadOverview() {
        tabsLoaded.overview = true;
        api("/summary").then(function(data) {
            if (!data) return;
            document.getElementById("statBestLap").textContent = data.best_lap_time ? formatLaptime(data.best_lap_time) : "--";
            document.getElementById("statAverage").textContent = data.average_time ? formatLaptime(data.average_time) : "--";
            document.getElementById("statConsistency").textContent = data.consistency_pct ? data.consistency_pct + "%" : "--";
            document.getElementById("statTotalLaps").textContent = data.total_laps || "--";

            // Weather strip
            if (data.weather) {
                var strip = document.createElement("div");
                strip.className = "weather-strip";
                var icon = weatherIcon(data.weather.weathercode);
                var html = '<span class="weather-condition"><i class="bi ' + icon + '"></i> ' + (data.weather.condition || "") + '</span>';
                if (data.weather.temp_c !== null && data.weather.temp_c !== undefined) {
                    html += '<span class="weather-temp">' + data.weather.temp_c + '\u00B0C</span>';
                }
                if (data.weather.wind_kmh) {
                    html += '<span class="weather-wind"><i class="bi bi-wind"></i> ' + (data.weather.wind_direction || "") + ' ' + data.weather.wind_kmh + ' km/h</span>';
                }
                strip.innerHTML = html;
                var badges = document.getElementById("dashBadges");
                badges.parentNode.insertBefore(strip, badges);
            }

            // Excluded laps alert
            if (data.excluded_laps && data.excluded_laps.length > 0) {
                var el = document.getElementById("excludedLapsAlert");
                var laps = data.excluded_laps.map(function(l) {
                    return "Lap " + l.lap + " (" + formatLaptime(l.seconds) + (l.reason ? " \u2014 " + l.reason : "") + ")";
                });
                el.innerHTML = '<div class="alert alert-warning alert-dismissible fade show" role="alert">'
                    + '<strong>Excluded Laps:</strong> ' + laps.join(", ")
                    + '<button type="button" class="btn-close" data-bs-dismiss="alert"></button></div>';
            }

            // Coaching action plan
            if (data.coaching && data.coaching.action_items && data.coaching.action_items.length > 0) {
                var cp = document.getElementById("coachingPlan");
                var html = '<div class="card border-primary action-plan"><div class="card-header bg-primary text-white"><strong>Your Action Plan</strong></div><div class="card-body p-0">';
                data.coaching.action_items.forEach(function(item) {
                    var icon = ICON_MAP[item.icon] || "";
                    html += '<div class="action-item d-flex align-items-start"><span class="action-icon ' + item.icon + '">' + icon + '</span><div><strong>' + item.title + '</strong><br><span class="text-muted">' + item.detail + '</span></div></div>';
                });
                html += '</div></div>';
                cp.innerHTML = html;
            }
        });

        // Overview charts
        api("/charts/laptime_bar").then(function(data) {
            if (data) Plotly.react("laptimeBarDiv", data.data, data.layout, {responsive: true});
        });
        api("/charts/delta_to_best").then(function(data) {
            if (data) Plotly.react("deltaTobestDiv", data.data, data.layout, {responsive: true});
        });

        // Sector table
        api("/sectors").then(function(data) {
            if (!data || !data.rows) {
                if (meta.dataset.hasCorners !== "true" && meta.dataset.trackId) {
                    var sc = document.getElementById("sectorTableContainer");
                    sc.innerHTML = '<div class="card p-3 text-center text-muted mt-3"><i class="bi bi-pie-chart" style="font-size:1.5rem;"></i><p class="mt-2 mb-0">Add corners to the track to see sector times.</p></div>';
                }
                return;
            }
            var container = document.getElementById("sectorTableContainer");
            var headers = data.headers || [];
            var sectorNames = headers;

            var html = '<div class="row mt-3"><div class="col-12"><div class="card p-2">';
            html += '<h6 class="card-title text-center mb-2">Sector Times</h6>';
            html += '<div class="table-responsive"><table class="table table-sm table-hover text-center mb-0" style="font-size:0.85rem;">';
            html += '<thead><tr><th>Lap</th>';
            sectorNames.forEach(function(h) { html += '<th>' + h + '</th>'; });
            html += '<th>Total</th><th>Delta</th></tr></thead><tbody>';

            if (data.rows) {
                data.rows.forEach(function(row) {
                    html += '<tr' + (row.is_best ? ' class="fw-bold"' : '') + '><td>L' + row.lap + '</td>';
                    row.sectors.forEach(function(s) {
                        html += '<td class="' + (s.css_class || '') + '">' + s.value + '</td>';
                    });
                    html += '<td>' + row.total + '</td><td>' + row.delta + '</td></tr>';
                });
            }

            if (data.theoretical_row) {
                html += '<tr class="row-ideal fw-bold"><td>Ideal</td>';
                data.theoretical_row.sectors.forEach(function(s) { html += '<td>' + s.value + '</td>'; });
                html += '<td>' + data.theoretical_row.total + '</td><td>-</td></tr>';
            }

            html += '</tbody></table></div></div></div></div>';
            container.innerHTML = html;
        });
    }

    // ---- Deep Dive ----
    function loadDeepDive() {
        tabsLoaded.deepdive = true;
        api("/laps").then(function(laps) {
            if (!laps || laps.length === 0) return;
            lapList = laps;
            var select = document.getElementById("lapDeepDiveSelect");
            select.innerHTML = "";
            var bestLap = null;
            laps.forEach(function(l) {
                var opt = document.createElement("option");
                opt.value = l.lap;
                opt.textContent = "Lap " + l.lap + " \u2014 " + l.time_fmt + (l.is_best ? " (best)" : "");
                if (l.is_best) { opt.selected = true; bestLap = l.lap; }
                select.appendChild(opt);
            });

            select.addEventListener("change", function() { loadLapData(this.value); });
            if (bestLap) loadLapData(bestLap);
        });
    }

    function loadLapData(lap) {
        // Maps (if MapKit available)
        if (mapkitToken) {
            MapHelpers.waitForMapKit(function() {
                api("/charts/speed_map/" + lap).then(function(data) {
                    if (!data) return;
                    if (speedMapRef) speedMapRef.update(data);
                    else speedMapRef = MapHelpers.setupTrackMap("speedMap", "speedCanvas", "speedMapWrap", data);
                });
                api("/charts/braking_map/" + lap).then(function(data) {
                    if (!data) return;
                    if (brakingMapRef) brakingMapRef.update(data);
                    else brakingMapRef = MapHelpers.setupTrackMap("brakingMap", "brakingCanvas", "brakingMapWrap", data);
                });
                api("/charts/sector_map/" + lap).then(function(data) {
                    if (!data) {
                        if (meta.dataset.hasCorners !== "true") {
                            var wrap = document.getElementById("sectorMapWrap");
                            if (wrap) wrap.innerHTML = '<div style="display:flex;align-items:center;justify-content:center;height:100%;color:var(--bb-text-muted);font-size:0.85rem;text-align:center;padding:1rem;"><div><i class="bi bi-signpost-split" style="font-size:1.5rem;display:block;margin-bottom:0.5rem;"></i>Add corners to the track to see sector maps</div></div>';
                        }
                        return;
                    }
                    if (sectorMapRef) sectorMapRef.update(data);
                    else sectorMapRef = MapHelpers.setupTrackMap("sectorMap", "sectorCanvas", "sectorMapWrap", data);
                });
            });
        }

        // Plotly charts
        api("/charts/cumulative_delta/" + lap).then(function(data) {
            if (data) Plotly.react("cumulativeDeltaDiv", data.data, data.layout, {responsive: true});
            else Plotly.purge("cumulativeDeltaDiv");
        });
        api("/charts/throttle_brake/" + lap).then(function(data) {
            if (data) Plotly.react("throttleBrakeDiv", data.data, data.layout, {responsive: true});
            else Plotly.purge("throttleBrakeDiv");
        });
    }

    // ---- Racing Line ----
    function loadRaceline() {
        tabsLoaded.raceline = true;
        if (!mapkitToken) return;
        var trackId = meta.dataset.trackId;
        var currentSessionId = parseInt(meta.dataset.sessionIdVal);

        // Fetch current session raceline + sibling sessions at the same track
        Promise.all([
            api("/raceline"),
            trackId && !shareToken ? fetch("/api/evolution?track_id=" + trackId, { credentials: "same-origin" })
                .then(function(r) { return r.ok ? r.json() : []; }).catch(function() { return []; }) : Promise.resolve([])
        ]).then(function(results) {
            var currentData = results[0];
            var allSessions = results[1];
            if (!currentData) return;

            // Filter to sessions that aren't the current one
            var otherIds = [];
            var currentMeta = null;
            for (var i = 0; i < allSessions.length; i++) {
                if (allSessions[i].id !== currentSessionId) {
                    otherIds.push(allSessions[i].id);
                } else {
                    currentMeta = allSessions[i];
                }
            }

            if (otherIds.length === 0) {
                // No other sessions, just init with current data
                MapHelpers.waitForMapKit(function() { Raceline.init(currentData); });
                return;
            }

            // Fetch raceline data for sibling sessions
            fetch("/api/evolution/raceline?session_ids=" + otherIds.join(","), { credentials: "same-origin" })
                .then(function(r) { return r.ok ? r.json() : null; })
                .then(function(evoData) {
                    // Build combined sessions array: current first, then others
                    var sessions = [{
                        laps: currentData.laps,
                        is_current: true,
                        session_id: currentSessionId,
                        date: currentMeta ? currentMeta.date : "",
                        labels: currentMeta ? (currentMeta.labels || []) : []
                    }];

                    if (evoData && evoData.sessions) {
                        for (var j = 0; j < evoData.sessions.length; j++) {
                            var s = evoData.sessions[j];
                            s.is_current = false;
                            sessions.push(s);
                        }
                    }

                    MapHelpers.waitForMapKit(function() {
                        Raceline.init({ sessions: sessions });
                    });
                })
                .catch(function() {
                    MapHelpers.waitForMapKit(function() { Raceline.init(currentData); });
                });
        });
    }

    // ---- Corner Analysis ----
    function loadCorners() {
        tabsLoaded.corners = true;
        var hasCorners = meta.dataset.hasCorners === "true";

        if (!hasCorners) {
            var container = document.getElementById("cornerTableContainer");
            var trackId = meta.dataset.trackId;
            var msg = trackId
                ? "No corners defined for this track. Add corners in the track editor to unlock corner-by-corner analysis, sector breakdown, and braking consistency."
                : "No track assigned. Add a track and define its corners to unlock corner analysis.";
            container.innerHTML = '<div class="card p-4 text-center text-muted"><i class="bi bi-signpost-split" style="font-size:2rem;"></i><p class="mt-2 mb-0">' + msg + '</p></div>';
            return;
        }

        // Corner map
        if (mapkitToken) {
            api("/corners/map").then(function(data) {
                if (!data) return;
                MapHelpers.waitForMapKit(function() {
                    var container = document.getElementById("cornerMapContainer");
                    container.innerHTML = '<div class="row mb-3"><div class="col-12"><div class="card p-2"><div class="mapkit-wrap" id="cornerMapWrap" style="height:450px;"><div class="mk-map" id="cornerMap"></div><canvas id="cornerCanvas"></canvas></div></div></div></div>';
                    MapHelpers.setupTrackMap("cornerMap", "cornerCanvas", "cornerMapWrap", data);
                });
            });
        }

        // Corner analysis table
        api("/corners").then(function(data) {
            if (!data) return;
            var container = document.getElementById("cornerTableContainer");
            var html = '';

            // Summary table
            if (data.summary_rows && data.summary_rows.length > 0) {
                html += '<div class="row"><div class="col-12"><div class="card p-2">';
                html += '<h6 class="card-title text-center mb-2">Corner Ranking (Worst First)</h6>';
                html += '<div class="table-responsive"><table class="table table-sm table-hover text-center mb-0" style="font-size:0.85rem;">';
                html += '<thead><tr><th>Corner</th><th>Type</th><th>Avg Time Loss</th><th>Best Min Speed</th><th>Avg Min Speed</th><th>Consistency</th><th>Main Issue</th></tr></thead><tbody>';
                data.summary_rows.forEach(function(row) {
                    var archBadge = row.archetype === "entry-dependent" ? '<span class="badge bg-danger">Entry</span>' :
                                    row.archetype === "exit-dependent" ? '<span class="badge bg-success">Exit</span>' :
                                    '<span class="badge bg-secondary">Flow</span>';
                    var tlClass = row.avg_time_loss > 0.05 ? 'text-danger fw-bold' : row.avg_time_loss < -0.02 ? 'text-success' : '';
                    var rcBadge = row.dominant_root_cause === "entry" ? '<span class="badge" style="background-color:#e67e22;">Entry</span>' :
                                  row.dominant_root_cause === "mid" ? '<span class="badge" style="background-color:#f1c40f;color:#333;">Mid</span>' :
                                  row.dominant_root_cause === "exit" ? '<span class="badge" style="background-color:#3498db;">Exit</span>' :
                                  '<span class="text-muted">-</span>';
                    html += '<tr><td class="fw-bold">' + row.corner + '</td><td>' + archBadge + '</td><td class="' + tlClass + '">' + row.avg_time_loss_fmt + '</td><td>' + row.best_min_speed + ' km/h</td><td>' + row.avg_min_speed + ' km/h</td><td>' + row.std_min_speed + ' km/h</td><td>' + rcBadge + '</td></tr>';
                });
                html += '</tbody></table></div></div></div></div>';
            }

            // Per-lap breakdown
            if (data.lap_breakdowns) {
                html += '<div class="row mt-3"><div class="col-12"><div class="card p-3">';
                html += '<div class="d-flex align-items-center justify-content-between mb-2"><h6 class="card-title mb-0">Lap Time Attribution</h6>';
                html += '<select id="cornerLapSelect" class="form-select form-select-sm" style="width:auto;">';
                if (data.laps) {
                    data.laps.forEach(function(l) {
                        html += '<option value="' + l.lap + '"' + (l.is_best ? ' selected' : '') + '>Lap ' + l.lap + (l.time_fmt ? ' \u2014 ' + l.time_fmt : '') + (l.is_best ? ' (Best)' : '') + '</option>';
                    });
                }
                html += '</select></div>';

                for (var lapKey in data.lap_breakdowns) {
                    var isVisible = data.best_lap && String(lapKey) === String(data.best_lap);
                    html += '<div class="corner-lap-breakdown" id="corner-lap-' + lapKey + '" style="' + (isVisible ? '' : 'display:none;') + '">';
                    html += '<div class="table-responsive"><table class="table table-sm table-hover text-center mb-0" style="font-size:0.85rem;">';
                    html += '<thead><tr><th>Corner</th><th>Time Loss</th><th>Root Cause</th><th>Entry</th><th>Min Speed</th><th>Exit</th><th>Braking Dist</th></tr></thead><tbody>';
                    data.lap_breakdowns[lapKey].forEach(function(r) {
                        var rcBadge = r.root_cause === "entry" ? '<span class="badge" style="background-color:#e67e22;">Entry</span>' :
                                      r.root_cause === "mid" ? '<span class="badge" style="background-color:#f1c40f;color:#333;">Mid</span>' :
                                      r.root_cause === "exit" ? '<span class="badge" style="background-color:#3498db;">Exit</span>' :
                                      '<span class="text-muted">-</span>';
                        var tlClass = r.time_loss > 0.05 ? 'text-danger fw-bold' : r.time_loss < -0.02 ? 'text-success' : '';
                        html += '<tr class="' + (r.is_worst ? 'table-danger' : '') + '"><td class="fw-bold">' + r.corner + '</td><td class="' + tlClass + '">' + r.time_loss_fmt + '</td><td>' + rcBadge + '</td><td>' + r.entry_speed + ' km/h</td><td>' + r.min_speed + ' km/h</td><td>' + r.exit_speed + ' km/h</td><td>' + (r.braking_distance !== null && r.braking_distance !== undefined ? r.braking_distance + 'm' : '-') + '</td></tr>';
                    });
                    html += '</tbody></table></div></div>';
                }
                html += '</div></div></div>';
            }

            container.innerHTML = html;

            // Lap selector
            var lapSelect = document.getElementById("cornerLapSelect");
            if (lapSelect) {
                lapSelect.addEventListener("change", function() {
                    document.querySelectorAll(".corner-lap-breakdown").forEach(function(p) { p.style.display = "none"; });
                    var target = document.getElementById("corner-lap-" + this.value);
                    if (target) target.style.display = "";
                });
            }
        });

        // Braking consistency chart
        api("/charts/braking_consistency").then(function(data) {
            if (data) Plotly.react("brakingConsistencyDiv", data.data, data.layout, {responsive: true});
        });

    }

    // Init MapKit if token present
    if (mapkitToken) {
        MapHelpers.initMapKit(mapkitToken);
    }
})();
