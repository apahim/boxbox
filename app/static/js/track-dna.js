/* Track DNA scorecard section (plan Phase 9).
 *
 * Fetches /api/tracks/<id>/dna and renders the scorecard: dimension
 * table with quality classes, DNA corner table, braking zones + minor
 * zones + DNA corners on a MapKit map (via the stored consensus
 * trajectory), the elevation profile (Plotly, loaded on demand) and
 * the similarity section. Tracks without scorecards show nothing —
 * the section starts hidden and is only revealed when cards exist.
 */
window.TrackDNA = (function() {
    var container = null;
    var trackId = null;
    var cards = null;
    var activeCondition = {};

    var PLOTLY_SRC = "https://cdn.plot.ly/plotly-3.4.0.min.js";
    var PLOTLY_INTEGRITY = "sha384-pFOQ7loGBChmUyS4Tszy+he8OWeYkwTFjc2xii4aJUWWiGwf2u2OEc04T5iDRpMp";

    var QUALITY_BADGE = {
        Measured: "bg-success",
        Estimated: "bg-warning text-dark",
        Unavailable: "bg-secondary"
    };

    function api(path) {
        return fetch("/api/tracks/" + trackId + path,
                     { credentials: "same-origin" })
            .then(function(r) { return r.ok ? r.json() : null; });
    }

    function el(tag, className, text) {
        var node = document.createElement(tag);
        if (className) node.className = className;
        if (text !== undefined && text !== null) node.textContent = text;
        return node;
    }

    function hint(parent, text) {
        parent.appendChild(el("div", "text-muted", text));
    }

    function fmt(value, unit) {
        if (value === null || value === undefined) return "—";
        return (typeof value === "number" ? +value.toFixed(2) : value)
            + (unit || "");
    }

    /* s -> {lat, lon} by linear interpolation on the stored trajectory
     * (points are [[s, lat, lon], ...], monotone s). */
    function trajAt(points, s) {
        if (!points || !points.length) return null;
        var last = points[points.length - 1];
        if (s <= points[0][0])
            return { lat: points[0][1], lon: points[0][2] };
        if (s >= last[0]) return { lat: last[1], lon: last[2] };
        var lo = 0, hi = points.length - 1;
        while (hi - lo > 1) {
            var mid = (lo + hi) >> 1;
            if (points[mid][0] <= s) lo = mid; else hi = mid;
        }
        var a = points[lo], b = points[hi];
        var frac = (s - a[0]) / (b[0] - a[0]);
        return { lat: a[1] + frac * (b[1] - a[1]),
                 lon: a[2] + frac * (b[2] - a[2]) };
    }

    // ---- dimension table --------------------------------------------------------

    function renderDimensions(holder, card) {
        var wrap = el("div", "table-responsive");
        var table = el("table", "table table-hover table-sm mb-0");
        var thead = el("thead");
        thead.innerHTML = "<tr><th>Dimension</th><th>Value</th>"
            + "<th>Character</th><th>Score</th><th>Quality</th></tr>";
        table.appendChild(thead);
        var tbody = el("tbody");
        card.dimensions.forEach(function(dim) {
            var tr = el("tr");
            tr.appendChild(el("td", null, dim.display));
            tr.appendChild(el("td", null, fmt(dim.value, dim.unit)));
            tr.appendChild(el("td", "text-muted", dim.class || "—"));
            var score = dim.score === null || dim.score === undefined
                ? "—" : dim.score.toFixed(1) + "/10";
            tr.appendChild(el("td", null, score));
            var badge = el("span",
                "badge " + (QUALITY_BADGE[dim.quality] || "bg-secondary"),
                dim.quality || "—");
            if (dim.warnings && dim.warnings.length) {
                badge.title = dim.warnings.join("; ");
                var td = el("td");
                td.appendChild(badge);
                td.appendChild(el("span", "ms-1 text-muted", "⚠"));
                tr.appendChild(td);
            } else {
                var td2 = el("td");
                td2.appendChild(badge);
                tr.appendChild(td2);
            }
            tbody.appendChild(tr);
        });
        table.appendChild(tbody);
        wrap.appendChild(table);
        holder.appendChild(wrap);
    }

    // ---- corner table -----------------------------------------------------------

    function renderCorners(holder, card) {
        var corners = card.support && card.support.consensus
            && card.support.consensus.corners;
        if (!corners || !corners.length) return;
        holder.appendChild(el("h6", "mt-3 mb-2", "Corners"));
        var wrap = el("div", "table-responsive");
        var table = el("table", "table table-hover table-sm mb-0");
        var thead = el("thead");
        thead.innerHTML = "<tr><th>#</th><th>Type</th><th>Radius</th>"
            + "<th>Heading change</th><th>Side</th><th>Recurrence</th>"
            + "<th>Laps</th><th class='d-none d-md-table-cell'>Zone (m)</th></tr>";
        table.appendChild(thead);
        var tbody = el("tbody");
        corners.forEach(function(c, i) {
            var tr = el("tr");
            tr.appendChild(el("td", null, "C" + (i + 1)));
            tr.appendChild(el("td", null, c.class || "—"));
            tr.appendChild(el("td", null, c.radius_m === null
                ? "—" : c.radius_m + " m"));
            tr.appendChild(el("td", null, Math.abs(c.delta_theta_deg) + "°"));
            tr.appendChild(el("td", null, c.sign < 0 ? "Right" : "Left"));
            tr.appendChild(el("td", null,
                Math.round(100 * c.recurrence) + "%"));
            tr.appendChild(el("td", null, c.n_laps));
            tr.appendChild(el("td", "d-none d-md-table-cell",
                c.s_start + "–" + c.s_end + " m"));
            tbody.appendChild(tr);
        });
        table.appendChild(tbody);
        wrap.appendChild(table);
        holder.appendChild(wrap);
    }

    // ---- MapKit map: trajectory + zones + corners --------------------------------

    function addMapLabel(map, coord, text, bg, title) {
        var ann = new mapkit.Annotation(coord, function() {
            var node = document.createElement("div");
            node.textContent = text;
            node.style.cssText = "font-size:11px;font-weight:bold;color:#fff;"
                + "background:" + bg + ";padding:1px 6px;border-radius:10px;"
                + "white-space:nowrap;pointer-events:none;";
            return node;
        }, { draggable: false, enabled: false,
             displayPriority: mapkit.Annotation.DisplayPriority.Required });
        if (title) ann.title = title;
        map.addAnnotation(ann);
    }

    function buildMap(holder, card) {
        var traj = card.support && card.support.trajectory;
        if (!traj || !traj.points || !traj.points.length) {
            hint(holder, "Map overlay needs a recomputed scorecard "
                + "(no stored trajectory).");
            return;
        }
        if (!window.BB_MAPKIT_TOKEN || !window.MapHelpers) return;
        MapHelpers.waitForMapKit(function() {
            mapkit.init({ authorizationCallback: function(done) {
                done(window.BB_MAPKIT_TOKEN);
            } });

            var mapDiv = el("div", "dna-map");
            var mapHolder = el("div", "dna-map-container mb-3");
            mapHolder.appendChild(mapDiv);
            holder.insertBefore(mapHolder, holder.firstChild);

            var lats = traj.points.map(function(p) { return p[1]; });
            var lons = traj.points.map(function(p) { return p[2]; });
            var map = new mapkit.Map(mapDiv, {
                center: new mapkit.Coordinate(
                    (Math.min.apply(null, lats) + Math.max.apply(null, lats)) / 2,
                    (Math.min.apply(null, lons) + Math.max.apply(null, lons)) / 2),
                mapType: mapkit.Map.MapTypes.Satellite,
                showsCompass: mapkit.FeatureVisibility.Hidden,
                showsMapTypeControl: false,
                showsZoomControl: true,
                isRotationEnabled: false
            });
            var pad = 0.001;
            map.region = new mapkit.BoundingRegion(
                Math.max.apply(null, lats) + pad,
                Math.max.apply(null, lons) + pad,
                Math.min.apply(null, lats) - pad,
                Math.min.apply(null, lons) - pad
            ).toCoordinateRegion();

            // consensus trajectory (median line), loop closed implicitly
            var coords = traj.points.map(function(p) {
                return new mapkit.Coordinate(p[1], p[2]);
            });
            coords.push(coords[0]);
            map.addOverlay(new mapkit.PolylineOverlay(coords, {
                style: new mapkit.Style({ lineWidth: 3,
                    strokeColor: "#3b82f6", strokeOpacity: 0.95 })
            }));

            // DNA corners at s_apex
            var corners = (card.support.consensus
                && card.support.consensus.corners) || [];
            corners.forEach(function(c, i) {
                var pos = trajAt(traj.points, c.s_apex);
                if (!pos) return;
                addMapLabel(map, new mapkit.Coordinate(pos.lat, pos.lon),
                    "C" + (i + 1), "#3498db",
                    (c.class || "corner") + ", radius "
                    + (c.radius_m === null ? "—" : c.radius_m + " m")
                    + ", " + Math.round(100 * c.recurrence) + "% of laps");
            });

            // braking zones + minor zones at s_trough
            var braking = card.support.braking || {};
            (braking.zones || []).forEach(function(z, i) {
                var pos = trajAt(traj.points, z.s_trough);
                if (!pos) return;
                addMapLabel(map, new mapkit.Coordinate(pos.lat, pos.lon),
                    "B" + (i + 1), "#e74c3c",
                    "Braking zone: " + z.reduction_pct + "% speed reduction, "
                    + Math.round(100 * z.recurrence) + "% of laps");
            });
            (braking.minor_zones || []).forEach(function(z, i) {
                var pos = trajAt(traj.points, z.s_trough);
                if (!pos) return;
                addMapLabel(map, new mapkit.Coordinate(pos.lat, pos.lon),
                    "b" + (i + 1), "#e67e22",
                    "Minor braking zone: " + z.reduction_pct
                    + "% speed reduction, "
                    + Math.round(100 * z.recurrence) + "% of laps");
            });
        });
    }

    // ---- elevation profile --------------------------------------------------------

    function loadPlotly(cb, holder) {
        if (window.Plotly) return cb();
        var script = document.createElement("script");
        script.src = PLOTLY_SRC;
        script.integrity = PLOTLY_INTEGRITY;
        script.crossOrigin = "anonymous";
        script.onload = cb;
        script.onerror = function() {
            if (holder) hint(holder, "Elevation chart unavailable "
                + "(Plotly failed to load).");
        };
        document.head.appendChild(script);
    }

    function renderElevation(holder, card) {
        var profile = card.support && card.support.elevation
            && card.support.elevation.profile;
        if (!profile || !profile.points || profile.points.length < 2) return;
        holder.appendChild(el("h6", "mt-3 mb-2", "Elevation Profile"));
        var chartDiv = el("div", "dna-elevation");
        holder.appendChild(chartDiv);
        loadPlotly(function() {
            var xs = profile.points.map(function(p) { return p[0]; });
            var ys = profile.points.map(function(p) { return p[1]; });
            Plotly.react(chartDiv, [{
                x: xs, y: ys, mode: "lines",
                line: { color: "#3b82f6", width: 2, shape: "spline" },
                fill: "tozeroy", fillcolor: "rgba(59,130,246,0.08)"
            }], {
                margin: { l: 45, r: 10, t: 10, b: 32 },
                xaxis: { title: { text: "Distance (m)" },
                         gridcolor: "rgba(128,128,128,0.15)" },
                yaxis: { title: { text: "Elevation (m)" },
                         gridcolor: "rgba(128,128,128,0.15)" },
                paper_bgcolor: "transparent",
                plot_bgcolor: "transparent",
                font: { size: 11 },
                showlegend: false
            }, { displayModeBar: false, responsive: true });
        }, holder);
    }

    // ---- similarity ----------------------------------------------------------------

    function renderSimilarity(holder, condition) {
        api("/dna/similar?condition=" + condition).then(function(payload) {
            if (!payload || !payload.configs) return;
            payload.configs.forEach(function(cfg) {
                if (!cfg.comparisons || !cfg.comparisons.length) return;
                var title = payload.configs.length > 1
                    ? "Similar Tracks — " + cfg.config_name : "Similar Tracks";
                holder.appendChild(el("h6", "mt-3 mb-2", title));
                var wrap = el("div", "table-responsive");
                var table = el("table",
                    "table table-hover table-sm mb-0 dna-similarity");
                var thead = el("thead");
                thead.innerHTML = "<tr><th>Track</th><th>Layout</th>"
                    + "<th>Similarity</th><th>Coverage</th></tr>";
                table.appendChild(thead);
                var tbody = el("tbody");
                cfg.comparisons.forEach(function(cmp) {
                    var tr = el("tr");
                    var tdName = el("td");
                    var link = el("a", null, cmp.track_name);
                    link.href = "/tracks/" + cmp.track_id;
                    tdName.appendChild(link);
                    tr.appendChild(tdName);
                    tr.appendChild(el("td", "text-muted", cmp.config_name));
                    var tdSim = el("td");
                    tdSim.appendChild(el("strong", null,
                        cmp.similarity_pct.toFixed(1) + "%"));
                    var top = Object.keys(cmp.contributions || {})
                        .map(function(k) { return [k, cmp.contributions[k]]; })
                        .sort(function(a, b) { return b[1] - a[1]; })
                        .slice(0, 3)
                        .map(function(kv) {
                            return kv[0].replace(/_/g, " ") + " "
                                + kv[1].toFixed(1) + " pp";
                        }).join(", ");
                    if (top) {
                        tdSim.appendChild(el("div", "text-muted",
                            "differs on: " + top));
                    }
                    tr.appendChild(tdSim);
                    tr.appendChild(el("td", null,
                        Math.round(100 * cmp.coverage) + "%"));
                    tbody.appendChild(tr);
                });
                table.appendChild(tbody);
                wrap.appendChild(table);
                holder.appendChild(wrap);
            });
        });
    }

    // ---- card rendering ---------------------------------------------------------

    function qualitySummary(card) {
        var counts = {};
        card.dimensions.forEach(function(dim) {
            counts[dim.quality] = (counts[dim.quality] || 0) + 1;
        });
        var parts = [];
        if (counts.Measured) parts.push(counts.Measured + " measured");
        if (counts.Estimated) parts.push(counts.Estimated + " estimated");
        if (counts.Unavailable)
            parts.push(counts.Unavailable + " unavailable");
        return parts.join(" · ");
    }

    function datasetLine(card) {
        var d = card.dataset || {};
        var laps = d.laps && d.laps.valid;
        var users = d.users ? Object.keys(d.users).length : null;
        var devices = (d.devices || []).join(", ");
        var parts = [];
        if (users !== null) parts.push(users + " user"
            + (users === 1 ? "" : "s"));
        if (laps !== null && laps !== undefined)
            parts.push(laps + " valid laps");
        if (d.date_range && d.date_range[0])
            parts.push(d.date_range[0]
                + (d.date_range[1] && d.date_range[1] !== d.date_range[0]
                    ? " to " + d.date_range[1] : ""));
        if (devices) parts.push(devices);
        var conf = d.confidence;
        if (conf && conf.convergence && conf.convergence.demonstrated_n)
            parts.push("convergence demonstrated at n="
                + conf.convergence.demonstrated_n);
        return parts.join(" · ");
    }

    function renderCard(body, card) {
        body.innerHTML = "";
        var header = el("div",
            "d-flex flex-wrap justify-content-between align-items-baseline "
            + "gap-2 mb-2");
        var scoreEl = el("div");
        var strong = el("strong", null,
            card.overall_score === null || card.overall_score === undefined
                ? "—" : card.overall_score.toFixed(2));
        strong.style.fontSize = "1.4rem";
        scoreEl.appendChild(strong);
        scoreEl.appendChild(el("span", "text-muted", "/10"));
        header.appendChild(scoreEl);
        var meta = el("div", "text-muted");
        meta.style.fontSize = "0.8rem";
        meta.appendChild(el("div", null, qualitySummary(card)));
        meta.appendChild(el("div", null, datasetLine(card)));
        if (card.computed_at)
            meta.appendChild(el("div", null,
                "computed " + card.computed_at.slice(0, 10)
                + " · methodology v" + card.methodology_version));
        header.appendChild(meta);
        body.appendChild(header);

        renderDimensions(body, card);
        buildMap(body, card);
        renderCorners(body, card);
        renderElevation(body, card);
        renderSimilarity(body, card.condition);
    }

    // ---- config blocks ----------------------------------------------------------

    function render() {
        var groups = {};
        var order = [];
        cards.forEach(function(card) {
            if (!groups[card.track_config_id]) {
                groups[card.track_config_id] = [];
                order.push(card.track_config_id);
            }
            groups[card.track_config_id].push(card);
        });

        order.forEach(function(configId) {
            var configCards = groups[configId];
            var block = el("div", "card mb-3");
            var blockBody = el("div", "card-body");
            block.appendChild(blockBody);

            // header: config name + direction + condition pills
            var head = el("div",
                "d-flex flex-wrap justify-content-between "
                + "align-items-center gap-2 mb-3");
            var nameEl = el("h6", "mb-0 d-flex align-items-center gap-2");
            nameEl.appendChild(el("span", null,
                configCards[0].config_name));
            nameEl.appendChild(el("span", "badge bg-secondary",
                configCards[0].direction));
            head.appendChild(nameEl);

            var conditions = configCards.map(function(c) {
                return c.condition;
            });
            if (conditions.length > 1) {
                var group = el("div", "btn-group btn-group-sm");
                group.setAttribute("role", "group");
                conditions.forEach(function(condition) {
                    var btn = el("button",
                        "btn btn-outline-secondary"
                        + (condition === activeCondition[configId]
                            ? " active" : ""), condition);
                    btn.type = "button";
                    btn.addEventListener("click", function() {
                        activeCondition[configId] = condition;
                        render();
                    });
                    group.appendChild(btn);
                });
                head.appendChild(group);
            }
            blockBody.appendChild(head);

            var card = configCards.filter(function(c) {
                return c.condition === activeCondition[configId];
            })[0] || configCards[0];
            activeCondition[configId] = card.condition;

            var cardBody = el("div");
            blockBody.appendChild(cardBody);
            renderCard(cardBody, card);
            container.appendChild(block);
        });
    }

    function init() {
        container = document.getElementById("track-dna");
        if (!container) return;
        trackId = parseInt(container.dataset.trackId, 10);
        api("/dna").then(function(payload) {
            if (!payload || !payload.scorecards
                || !payload.scorecards.length) return;  // stays hidden
            cards = payload.scorecards;
            container.hidden = false;
            render();
        });
    }

    return { init: init };
})();

window.TrackDNA.init();
