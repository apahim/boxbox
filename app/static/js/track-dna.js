/* Track DNA card section (reference-lap methodology).
 *
 * Fetches /api/tracks/<id>/dna and renders the card: the
 * interpretation block (headline, chips, blurb), dimension table,
 * DNA corner table, braking zones on the page's single MapKit map
 * (overlays added through the BBTrackMap handshake in detail.html)
 * and the elevation profile (Plotly, loaded on demand).
 * Tracks without a card show nothing — the section starts hidden and
 * is only revealed when a card exists.
 */
window.TrackDNA = (function() {
    var container = null;
    var trackId = null;
    var card = null;

    var PLOTLY_SRC = "https://cdn.plot.ly/plotly-3.4.0.min.js";
    var PLOTLY_INTEGRITY = "sha384-pFOQ7loGBChmUyS4Tszy+he8OWeYkwTFjc2xii4aJUWWiGwf2u2OEc04T5iDRpMp";

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
            + "<th>Character</th><th>Score</th></tr>";
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
            + "<th>Heading change</th><th>Side</th>"
            + "<th class='d-none d-md-table-cell'>Zone (m)</th></tr>";
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
            tr.appendChild(el("td", "d-none d-md-table-cell",
                c.s_start + "–" + c.s_end + " m"));
            tbody.appendChild(tr);
        });
        table.appendChild(tbody);
        wrap.appendChild(table);
        holder.appendChild(wrap);
    }

    // ---- map overlays: trajectory + braking zones on the page map -----------------
    //
    // The page has ONE map (detail.html's #map-container, showing the
    // S/F gate and corner trap lines). The DNA card adds its overlays
    // to it through the BBTrackMap handshake; without a map (no MapKit
    // token) the card renders fine, just without map layers.

    function addDnaOverlays(card) {
        var traj = card.support && card.support.trajectory;
        if (!traj || !traj.points || !traj.points.length) return;
        if (!window.BBTrackMapPromise) return;
        window.BBTrackMapPromise.then(function(tm) {
            // trajectory (the reference lap's line), loop closed
            // implicitly
            var coords = traj.points.map(function(p) {
                return new mapkit.Coordinate(p[1], p[2]);
            });
            coords.push(coords[0]);
            tm.addPolyline(coords, { lineWidth: 3,
                strokeColor: "#3b82f6", strokeOpacity: 0.95 });

            // braking zones + minor zones at s_trough
            var braking = card.support.braking || {};
            (braking.zones || []).forEach(function(z, i) {
                var pos = trajAt(traj.points, z.s_trough);
                if (!pos) return;
                tm.addLabel(new mapkit.Coordinate(pos.lat, pos.lon),
                    "B" + (i + 1), "#e74c3c",
                    "Braking zone: " + z.reduction_pct
                    + "% speed reduction");
            });
            (braking.minor_zones || []).forEach(function(z, i) {
                var pos = trajAt(traj.points, z.s_trough);
                if (!pos) return;
                tm.addLabel(new mapkit.Coordinate(pos.lat, pos.lon),
                    "b" + (i + 1), "#e67e22",
                    "Minor braking zone: " + z.reduction_pct
                    + "% speed reduction");
            });

            tm.refit(traj.points.map(function(p) {
                return { lat: p[1], lon: p[2] };
            }));
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

    // ---- interpretation block ------------------------------------------------------

    function renderSummary(body, card) {
        var sum = card.summary;
        if (!sum) return;
        var block = el("div", "dna-summary mb-3");
        if (sum.headline) {
            block.appendChild(el("div", "dna-headline", sum.headline));
        }
        if (sum.chips && sum.chips.length) {
            var chips = el("div", "d-flex flex-wrap gap-1 mt-2");
            sum.chips.forEach(function(text) {
                chips.appendChild(el("span",
                    "badge bg-secondary-subtle text-secondary-emphasis "
                    + "border border-secondary-subtle dna-chip", text));
            });
            block.appendChild(chips);
        }
        if (sum.blurb) {
            block.appendChild(el("div", "dna-blurb mt-2", sum.blurb));
        }
        body.appendChild(block);
    }

    // ---- card rendering ---------------------------------------------------------

    function datasetLine(card) {
        var d = card.dataset || {};
        var parts = ["admin-selected reference lap"];
        if (d.lap_number !== null && d.lap_number !== undefined)
            parts.push("lap " + d.lap_number);
        if (d.lap_time_s) parts.push(d.lap_time_s + "s");
        if (d.date) parts.push(d.date);
        if (d.device) parts.push(d.device);
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
        meta.appendChild(el("div", null, datasetLine(card)));
        if (card.reference_ok === false) {
            var broken = el("div", "text-warning");
            broken.textContent = "⚠ reference lap is no longer usable — "
                + (card.reference_error || "it will be re-picked");
            meta.appendChild(broken);
        }
        if (card.computed_at)
            meta.appendChild(el("div", null,
                "computed " + card.computed_at.slice(0, 10)
                + " · methodology v" + card.methodology_version));
        header.appendChild(meta);
        body.appendChild(header);

        renderSummary(body, card);
        renderDimensions(body, card);
        renderCorners(body, card);
        renderElevation(body, card);
        addDnaOverlays(card);
    }

    function render() {
        var block = el("div", "card mb-3");
        var blockBody = el("div", "card-body");
        block.appendChild(blockBody);

        var head = el("div",
            "d-flex flex-wrap justify-content-between "
            + "align-items-center gap-2 mb-3");
        var nameEl = el("h6", "mb-0 d-flex align-items-center gap-2");
        nameEl.appendChild(el("span", null, "Track DNA"));
        if (card.dataset && card.dataset.direction)
            nameEl.appendChild(el("span", "badge bg-secondary",
                card.dataset.direction));
        head.appendChild(nameEl);
        blockBody.appendChild(head);

        var cardBody = el("div");
        blockBody.appendChild(cardBody);
        renderCard(cardBody, card);
        container.appendChild(block);
    }

    function init() {
        container = document.getElementById("track-dna");
        if (!container) return;
        trackId = parseInt(container.dataset.trackId, 10);
        api("/dna").then(function(payload) {
            if (!payload || !payload.card) return;  // stays hidden
            card = payload.card;
            container.hidden = false;
            render();
        });
    }

    return { init: init };
})();

window.TrackDNA.init();
