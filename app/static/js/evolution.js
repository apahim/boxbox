/* Evolution page — cross-session trends and comparisons */
(function() {
    var meta = document.getElementById("evo-meta");
    if (!meta) return;
    var apiBase = meta.dataset.apiBase;
    var mapkitToken = meta.dataset.mapkitToken;

    var COLORS = ["#e74c3c", "#3498db", "#2ecc71", "#f39c12", "#9b59b6", "#1abc9c", "#e67e22", "#34495e"];
    var sessionsData = [];

    function api(path) {
        return fetch(apiBase + path, { credentials: "same-origin" })
            .then(function(r) { return r.ok ? r.json() : null; })
            .catch(function() { return null; });
    }

    function formatLaptime(seconds) {
        if (!seconds) return "--";
        var mins = Math.floor(seconds / 60);
        var secs = (seconds % 60).toFixed(3);
        if (secs < 10) secs = "0" + secs;
        return mins + ":" + secs;
    }

    // Load track list
    api("/tracks").then(function(tracks) {
        if (!tracks || tracks.length === 0) return;
        var select = document.getElementById("trackSelect");
        select.innerHTML = "";
        tracks.forEach(function(t, i) {
            var opt = document.createElement("option");
            opt.value = t.id;
            opt.textContent = t.name;
            if (i === 0) opt.selected = true;
            select.appendChild(opt);
        });
        select.addEventListener("change", function() { loadTrack(this.value); });
        loadTrack(tracks[0].id);
    });

    function loadTrack(trackId) {
        api("/evolution?track_id=" + trackId).then(function(data) {
            if (!data) return;
            sessionsData = data;
            renderTrendChart(data);
            renderSessionTable(data);
        });
        api("/evolution/corners?track_id=" + trackId).then(function(data) {
            if (data) renderCornerEvolution(data);
        });
        if (mapkitToken) {
            api("/evolution?track_id=" + trackId).then(function(data) {
                if (data && data.length > 0) renderRacelineSelectors(data);
            });
        }
    }

    function renderTrendChart(data) {
        if (data.length === 0) {
            Plotly.purge("trendChartDiv");
            return;
        }
        var dates = data.map(function(s) { return s.date; });
        var traces = [
            {
                x: dates,
                y: data.map(function(s) { return s.best_lap_time; }),
                name: "Best Lap",
                mode: "lines+markers",
                line: { color: "#2ecc71", width: 2 },
                marker: { size: 8 }
            },
            {
                x: dates,
                y: data.map(function(s) { return s.average_time; }),
                name: "Average",
                mode: "lines+markers",
                line: { color: "#3498db", width: 2, dash: "dot" },
                marker: { size: 6 }
            },
            {
                x: dates,
                y: data.map(function(s) { return s.median_time; }),
                name: "Median",
                mode: "lines+markers",
                line: { color: "#f39c12", width: 2, dash: "dash" },
                marker: { size: 6 }
            }
        ];
        var layout = {
            title: "Lap Time Trend",
            xaxis: { title: "Date" },
            yaxis: { title: "Time (s)", autorange: "reversed" },
            legend: { orientation: "h", y: -0.15 },
            margin: { t: 40, b: 60 },
            hovermode: "x unified"
        };
        Plotly.react("trendChartDiv", traces, layout, { responsive: true });
    }

    function renderSessionTable(data) {
        var tbody = document.getElementById("sessionTableBody");
        tbody.innerHTML = "";
        data.forEach(function(s) {
            var weather = "";
            if (s.weather) {
                weather = (s.weather.condition || "") + " " + (s.weather.temp_c || "") + "\u00B0C";
            }
            var row = document.createElement("tr");
            row.innerHTML = '<td>' + s.date + '</td>'
                + '<td class="fw-bold">' + formatLaptime(s.best_lap_time) + '</td>'
                + '<td>' + formatLaptime(s.average_time) + '</td>'
                + '<td>' + (s.consistency_pct || "--") + '%</td>'
                + '<td>' + (s.clean_laps || "--") + '/' + (s.total_laps || "--") + '</td>'
                + '<td>' + (s.top_speed_kmh || "--") + ' km/h</td>'
                + '<td><span class="badge bg-info metadata-badge">' + weather + '</span></td>'
                + '<td><a href="/dashboard/' + s.id + '" class="btn btn-sm btn-outline-primary">View</a></td>';
            tbody.appendChild(row);
        });
    }

    function renderCornerEvolution(corners) {
        if (!corners || corners.length === 0) {
            Plotly.purge("cornerEvoDiv");
            return;
        }
        var traces = [];
        corners.forEach(function(corner, i) {
            if (!corner.sessions || corner.sessions.length === 0) return;
            traces.push({
                x: corner.sessions.map(function(s) { return s.date; }),
                y: corner.sessions.map(function(s) { return s.avg_time_loss; }),
                name: corner.corner_name,
                mode: "lines+markers",
                line: { color: COLORS[i % COLORS.length], width: 2 },
                marker: { size: 6 }
            });
        });
        var layout = {
            title: "Corner Time Loss Evolution",
            xaxis: { title: "Date" },
            yaxis: { title: "Avg Time Loss (s)" },
            legend: { orientation: "h", y: -0.15 },
            margin: { t: 40, b: 60 },
            hovermode: "x unified"
        };
        Plotly.react("cornerEvoDiv", traces, layout, { responsive: true });
    }

    // Cross-session raceline
    var evoRlMap = null, evoRlOverlays = [];

    function renderRacelineSelectors(sessions) {
        var container = document.getElementById("rlSessionSelectors");
        if (!container) return;
        container.innerHTML = "";

        sessions.forEach(function(s, i) {
            var check = document.createElement("div");
            check.className = "form-check form-check-inline";
            check.innerHTML = '<input class="form-check-input rl-session-check" type="checkbox" value="' + s.id + '" id="rlSess' + s.id + '" ' + (i < 3 ? 'checked' : '') + '>'
                + '<label class="form-check-label" for="rlSess' + s.id + '" style="font-size:0.85rem;">'
                + '<span style="display:inline-block;width:10px;height:10px;border-radius:50%;background:' + COLORS[i % COLORS.length] + ';margin-right:4px;"></span>'
                + s.date + '</label>';
            container.appendChild(check);
        });

        container.querySelectorAll(".rl-session-check").forEach(function(cb) {
            cb.addEventListener("change", function() { loadEvoRaceline(sessions); });
        });

        loadEvoRaceline(sessions);
    }

    function loadEvoRaceline(sessions) {
        var checks = document.querySelectorAll(".rl-session-check:checked");
        var selectedIds = [];
        checks.forEach(function(cb) { selectedIds.push(cb.value); });

        if (selectedIds.length === 0) return;

        // Request best laps from each session's raceline data
        api("/evolution/raceline?session_ids=" + selectedIds.join(",")).then(function(data) {
            if (!data || !data.sessions) return;
            renderEvoRaceline(data.sessions, sessions);
        });
    }

    function renderEvoRaceline(racelineSessions, allSessions) {
        // Build color map from allSessions
        var colorMap = {};
        allSessions.forEach(function(s, i) { colorMap[s.id] = COLORS[i % COLORS.length]; });

        if (evoRlMap) {
            evoRlMap.removeOverlays(evoRlOverlays);
            evoRlOverlays = [];
        }

        var allLat = [], allLon = [];
        var legendItems = [];

        racelineSessions.forEach(function(session) {
            // Find best lap
            var bestLap = null;
            session.laps.forEach(function(l) {
                if (l.is_best) bestLap = l;
            });
            if (!bestLap && session.laps.length > 0) bestLap = session.laps[0];
            if (!bestLap) return;

            allLat = allLat.concat(bestLap.lat);
            allLon = allLon.concat(bestLap.lon);

            var color = colorMap[session.session_id] || "#888";
            legendItems.push({ date: session.date, color: color, time: bestLap.time_fmt });

            if (evoRlMap) {
                addEvoPolyline(bestLap, color);
            }
        });

        if (!evoRlMap && allLat.length > 0) {
            MapHelpers.waitForMapKit(function() {
                evoRlMap = MapHelpers.initSatMap("evoRacelineMap", allLat, allLon);
                racelineSessions.forEach(function(session) {
                    var bestLap = null;
                    session.laps.forEach(function(l) { if (l.is_best) bestLap = l; });
                    if (!bestLap && session.laps.length > 0) bestLap = session.laps[0];
                    if (bestLap) addEvoPolyline(bestLap, colorMap[session.session_id] || "#888");
                });
            });
        }

        // Legend
        var legendEl = document.getElementById("evoRacelineLegend");
        if (legendEl) {
            legendEl.innerHTML = "";
            legendItems.forEach(function(item) {
                var span = document.createElement("span");
                span.style.cssText = "display:inline-flex;align-items:center;gap:4px;";
                var dot = document.createElement("span");
                dot.style.cssText = "width:8px;height:8px;border-radius:50%;flex-shrink:0;background:" + item.color + ";";
                span.appendChild(dot);
                span.appendChild(document.createTextNode(item.date + " \u2014 " + item.time));
                legendEl.appendChild(span);
            });
        }
    }

    function addEvoPolyline(lap, color) {
        var coords = lap.lat.map(function(lat, i) {
            return new mapkit.Coordinate(lat, lap.lon[i]);
        });
        var style = new mapkit.Style({ strokeColor: color, lineWidth: 3, strokeOpacity: 0.8 });
        var overlay = new mapkit.PolylineOverlay(coords, { style: style });
        evoRlOverlays.push(overlay);
        evoRlMap.addOverlay(overlay);
    }

    if (mapkitToken) {
        MapHelpers.initMapKit(mapkitToken);
    }
})();
