/* Track DNA card section (reference-lap methodology).
 *
 * Fetches /api/tracks/<id>/dna and renders the card for someone
 * learning the track: the interpretation block (headline, chips,
 * blurb), driving notes (corner-by-corner, human units), the lap
 * strip (the circuit unrolled) and the corner table (apex speeds).
 * The technical layers — DNA fingerprint radar and the full
 * dimension table — live in a collapsed Details section.
 *
 * The reference lap replays as a sighting lap: a marker on the
 * page's single MapKit map at lap-time pace (camera follows when
 * zoomed in), a synced cursor sweeping the lap strip, corner blocks
 * lighting as they are passed, and a live callout naming the current
 * or next turn with BRAKE flashes before braking zones.
 *
 * Cross-linking: hovering a driving note, lap-strip segment or
 * corner-table row pulses the matching point on the map and
 * highlights the same turn everywhere it appears.
 *
 * Tracks without a card show nothing — the section reveals a loading
 * skeleton after 200ms and is removed again if no card exists.
 */
window.TrackDNA = (function() {
    var container = null;
    var trackId = null;
    var card = null;
    var userBestLap = null;
    var compareSessionId = null;   // user's best session here -> raceline

    var stripCursor = null;      // lap-strip replay cursor element
    var replay = { raf: null, playing: false, speed: 1, marker: null,
                   played: 0, t0: 0, btn: null, map: null };

    var PLOTLY_SRC = "https://cdn.plot.ly/plotly-3.4.0.min.js";
    var PLOTLY_INTEGRITY = "sha384-pFOQ7loGBChmUyS4Tszy+he8OWeYkwTFjc2xii4aJUWWiGwf2u2OEc04T5iDRpMp";

    var STRIP_W = 1000;          // strip viewBox width
    var CORNER_COLORS = { slow: "#e74c3c", medium: "#f39c12",
                          fast: "#2ecc71" };

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

    function svgEl(tag, attrs) {
        var node = document.createElementNS(
            "http://www.w3.org/2000/svg", tag);
        for (var k in attrs) node.setAttribute(k, attrs[k]);
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

    function fmtLap(t) {
        if (t === null || t === undefined) return "—";
        var m = Math.floor(t / 60);
        var s = t - 60 * m;
        return m + ":" + (s < 10 ? "0" : "") + s.toFixed(3);
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

    function withTrackMap(fn) {
        if (!window.BBTrackMapPromise) return;
        window.BBTrackMapPromise.then(function(tm) { fn(tm); });
    }

    function pulseAt(pos) {
        if (!pos) return;
        withTrackMap(function(tm) {
            if (tm.pulse) tm.pulse(pos.lat, pos.lon);
        });
    }

    // highlight one turn everywhere it appears: corner-table row,
    // lap-strip segment, driving note
    function highlightTurn(turn, on) {
        var row = document.getElementById("dna-corner-" + turn);
        if (row) row.classList.toggle("table-active", on);
        var note = document.getElementById("dna-note-" + turn);
        if (note) note.classList.toggle("dna-note-active", on);
        document.querySelectorAll(
            '.strip-seg[data-type="corner"][data-index="' + turn + '"]')
            .forEach(function(seg) {
                seg.classList.toggle("strip-hi", on);
            });
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

    // ---- you vs the reference lap --------------------------------------------------

    function renderComparison(meta, card) {
        var lap = card.dataset && card.dataset.lap_time_s;
        if (!lap || !userBestLap) return;
        var deltaPct = (userBestLap - lap) / lap * 100.0;
        var line = el("div",
            deltaPct <= 0 ? "text-success" : "text-warning");
        line.textContent = "Reference " + lap.toFixed(2) + "s · your best "
            + fmtLap(userBestLap) + " ("
            + (deltaPct <= 0 ? "" : "+") + deltaPct.toFixed(1) + "%)";
        meta.appendChild(line);
    }

    // ---- driving notes: the track, taught corner by corner --------------------------

    function renderDrivingNotes(body, card) {
        var notes = card.driving_notes || [];
        var traj = card.support && card.support.trajectory;
        if (!notes.length || !traj || !traj.points) return;

        var holder = el("div");
        body.appendChild(holder);
        holder.appendChild(el("h6", "mt-3 mb-2", "Driving notes"));

        var list = el("div", "dna-notes");
        holder.appendChild(list);
        notes.forEach(function(n) {
            var item = el("div", "dna-note");
            item.id = "dna-note-" + n.turn;
            item.appendChild(el("div", "dna-note-title", n.title));
            if (n.note) {
                item.appendChild(el("div", "dna-note-text", n.note));
            }
            item.addEventListener("mouseenter", function() {
                pulseAt(trajAt(traj.points, n.s_apex));
                highlightTurn(n.turn, true);
            });
            item.addEventListener("mouseleave", function() {
                highlightTurn(n.turn, false);
            });
            list.appendChild(item);
        });
    }

    // ---- lap strip: the circuit unrolled --------------------------------------------

    function stripX(s, lengthM) {
        var wrapped = ((s % lengthM) + lengthM) % lengthM;
        return wrapped / lengthM * STRIP_W;
    }

    function stripRect(svg, x1, x2, y, h, fill, opacity, data) {
        // a segment may wrap s=0: split into [x1, W] and [0, x2]
        var spans = x2 > x1 ? [[x1, x2]] : [[x1, STRIP_W], [0, x2]];
        var rects = [];
        spans.forEach(function(span) {
            if (span[1] - span[0] < 0.5) return;
            var rect = svgEl("rect", {
                x: span[0].toFixed(1), y: y,
                width: (span[1] - span[0]).toFixed(1),
                height: h, rx: 2, fill: fill, opacity: opacity,
                "class": "strip-seg" });
            for (var k in data) rect.dataset[k] = data[k];
            svg.appendChild(rect);
            rects.push(rect);
        });
        return rects;
    }

    function renderLapStrip(body, card) {
        var traj = card.support && card.support.trajectory;
        var corners = (card.support.consensus
            && card.support.consensus.corners) || [];
        var braking = card.support.braking || {};
        var zones = braking.zones || [];
        var minors = braking.minor_zones || [];
        if (!traj || !traj.points || !traj.points.length
            || !(traj.length_m > 0)) return;
        var L = traj.length_m;

        var holder = el("div");
        body.appendChild(holder);
        holder.appendChild(el("h6", "mt-3 mb-2", "Lap"));

        var strip = el("div", "dna-strip");
        holder.appendChild(strip);

        var svg = svgEl("svg", { viewBox: "0 0 " + STRIP_W + " 60",
            preserveAspectRatio: "none" });
        strip.appendChild(svg);

        // base band: the straights
        svg.appendChild(svgEl("rect", {
            x: 0, y: 24, width: STRIP_W, height: 12, rx: 3,
            fill: "rgba(128,128,128,0.22)" }));

        // S/F line at s=0
        svg.appendChild(svgEl("line", {
            x1: 0.5, y1: 12, x2: 0.5, y2: 48,
            stroke: "#2ecc71", "stroke-width": 2, "stroke-dasharray": "4 3",
            "vector-effect": "non-scaling-stroke" }));

        var labels = el("div");
        labels.style.position = "absolute";
        labels.style.inset = "0";
        strip.appendChild(labels);

        function label(text, s, cls) {
            var node = el("span", "strip-label " + cls, text);
            node.style.left = (stripX(s, L) / STRIP_W * 100) + "%";
            labels.appendChild(node);
        }

        function wireHover(node, type, idx, pos) {
            node.addEventListener("mouseenter", function() {
                pulseAt(pos);
                if (type === "corner") highlightTurn(idx, true);
            });
            node.addEventListener("mouseleave", function() {
                if (type === "corner") highlightTurn(idx, false);
            });
        }

        // corner blocks, colored by class
        corners.forEach(function(c, i) {
            var color = CORNER_COLORS[c.class] || "#f39c12";
            var x1 = stripX(c.s_start, L), x2 = stripX(c.s_end, L);
            var apex = trajAt(traj.points, c.s_apex);
            var blocks = stripRect(svg, x1, x2, 20, 20, color, 0.8,
                { type: "corner", index: i + 1 });
            blocks.forEach(function(node) {
                wireHover(node, "corner", i + 1, apex);
            });
            label("T" + (i + 1), c.s_apex, "corner d-none d-sm-block");
        });

        // braking zones: intensity markers at s_trough
        function zoneMarker(z, i, minor) {
            var x = stripX(z.s_trough, L);
            var w = Math.max(5, (z.reduction_pct || 30) / 100 * 22);
            var pos = trajAt(traj.points, z.s_trough);
            var rect = svgEl("rect", {
                x: (x - w / 2).toFixed(1), y: 8, width: w.toFixed(1),
                height: 44, rx: 3,
                fill: minor ? "#e67e22" : "#e74c3c",
                opacity: minor ? 0.35 : 0.55,
                "class": "strip-seg" });
            rect.dataset.type = "zone";
            svg.appendChild(rect);
            wireHover(rect, "zone", 0, pos);
            if (!minor) label("B" + (i + 1), z.s_trough, "zone");
        }
        zones.forEach(function(z, i) { zoneMarker(z, i, false); });
        minors.forEach(function(z) { zoneMarker(z, -1, true); });

        // replay cursor (positioned by the replay loop)
        stripCursor = el("div", "dna-strip-cursor");
        strip.appendChild(stripCursor);
    }

    // ---- DNA fingerprint radar -------------------------------------------------------

    function renderRadar(body, card) {
        var dims = (card.dimensions || []).filter(function(d) {
            return d.score !== null && d.score !== undefined;
        });
        if (dims.length < 3) return;      // not enough axes to read
        var chartDiv = el("div", "dna-radar");
        chartDiv.style.height = "300px";
        body.appendChild(chartDiv);
        var r = dims.map(function(d) { return d.score; });
        var theta = dims.map(function(d) { return d.display; });
        r.push(r[0]); theta.push(theta[0]);
        Plotly.react(chartDiv, [{
            type: "scatterpolar", r: r, theta: theta, fill: "toself",
            line: { color: "#3b82f6", width: 2 },
            marker: { size: 4, color: "#3b82f6" },
            hovertemplate: "%{theta}: %{r:.1f}/10<extra></extra>"
        }], {
            polar: {
                bgcolor: "transparent",
                radialaxis: { range: [0, 10], showticklabels: false,
                              gridcolor: "rgba(128,128,128,0.15)" },
                angularaxis: { direction: "clockwise", rotation: 90,
                               gridcolor: "rgba(128,128,128,0.15)",
                               tickfont: { size: 9 } }
            },
            margin: { l: 70, r: 70, t: 30, b: 30 },
            paper_bgcolor: "transparent",
            font: { size: 10, color: "#adb5bd" },
            showlegend: false
        }, { displayModeBar: false, responsive: true });
    }

    // ---- Details (collapsed): fingerprint radar + full dimension table ---------------

    function renderDetails(body, card) {
        var toggle = el("button",
            "btn btn-sm btn-outline-secondary mt-3 mb-2");
        toggle.type = "button";
        toggle.setAttribute("data-bs-toggle", "collapse");
        toggle.setAttribute("data-bs-target", "#dna-details");
        toggle.setAttribute("aria-expanded", "false");
        toggle.innerHTML = '<i class="bi bi-sliders"></i> Details';
        body.appendChild(toggle);

        var col = el("div", "collapse");
        col.id = "dna-details";
        body.appendChild(col);

        // the fingerprint radar lives in here — analyst material,
        // out of the learner's way
        loadPlotly(function() { renderRadar(col, card); }, col);

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
        col.appendChild(wrap);
    }

    // ---- corner table -----------------------------------------------------------------

    function renderCorners(body, card) {
        var traj = card.support && card.support.trajectory;
        var corners = card.support && card.support.consensus
            && card.support.consensus.corners;
        if (!corners || !corners.length) return;
        var holder = el("div");
        body.appendChild(holder);
        holder.appendChild(el("h6", "mt-3 mb-2", "Corners"));
        var wrap = el("div", "table-responsive");
        var table = el("table", "table table-hover table-sm mb-0");
        var thead = el("thead");
        thead.innerHTML = "<tr><th>Turn</th><th>Type</th>"
            + "<th>Apex speed</th><th>Side</th></tr>";
        table.appendChild(thead);
        var tbody = el("tbody");
        corners.forEach(function(c, i) {
            var tr = el("tr");
            tr.id = "dna-corner-" + (i + 1);
            tr.appendChild(el("td", null, "Turn " + (i + 1)));
            tr.appendChild(el("td", null, c.class || "—"));
            tr.appendChild(el("td", null,
                c.apex_speed_kmh
                    ? "~" + Math.round(c.apex_speed_kmh) + " km/h"
                    : "—"));
            tr.appendChild(el("td", null, c.sign < 0 ? "Right" : "Left"));
            // hovering the row pulses the apex on the map and lights
            // the same turn in the notes and the strip
            tr.addEventListener("mouseenter", function() {
                pulseAt(trajAt(traj && traj.points, c.s_apex));
                highlightTurn(i + 1, true);
            });
            tr.addEventListener("mouseleave", function() {
                highlightTurn(i + 1, false);
            });
            tbody.appendChild(tr);
        });
        table.appendChild(tbody);
        wrap.appendChild(table);
        holder.appendChild(wrap);
    }

    // ---- map overlays: trajectory + braking zones on the page map -----------------

    function addDnaOverlays(card) {
        var traj = card.support && card.support.trajectory;
        if (!traj || !traj.points || !traj.points.length) return;
        withTrackMap(function(tm) {
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

    // ---- reference-lap replay ---------------------------------------------------------

    function renderReplayControls(body, card) {
        var lap = card.dataset && card.dataset.lap_time_s;
        var traj = card.support && card.support.trajectory;
        var canReplay = !!(lap && traj && traj.points.length
            && window.BBTrackMapPromise);

        var wrap = el("div", "d-flex align-items-center gap-2 mb-3");
        var btn = el("button", "btn btn-sm "
            + (canReplay ? "btn-outline-warning" : "btn-outline-secondary"));
        btn.type = "button";
        btn.disabled = !canReplay;
        btn.innerHTML = '<i class="bi bi-play-fill"></i> Replay reference lap';
        if (!canReplay) btn.title = "Needs a map and a stored lap time";
        wrap.appendChild(btn);
        replay.btn = btn;

        var speed = el("select", "form-select form-select-sm");
        speed.style.width = "auto";
        [[1, "1×"], [2, "2×"], [4, "4×"]].forEach(function(opt) {
            var o = el("option", null, opt[1]);
            o.value = String(opt[0]);
            speed.appendChild(o);
        });
        speed.addEventListener("change", function() {
            // restart the elapsed clock at the current position
            if (replay.playing) {
                replay.played = currentReplayElapsed();
                replay.t0 = performance.now();
            }
            replay.speed = parseInt(speed.value, 10);
        });
        wrap.appendChild(speed);
        if (!canReplay) speed.disabled = true;

        // live callout while the sighting lap plays ("Turn 3 —
        // medium left · ~52 km/h", BRAKE before zone troughs)
        var callout = el("div", "dna-callout");
        wrap.appendChild(callout);
        replay.callout = callout;

        // where am I losing time? — straight into the raceline tool
        if (compareSessionId) {
            var link = el("a", "btn btn-sm btn-outline-primary");
            link.href = "/dashboard/" + compareSessionId + "#raceline";
            link.innerHTML = '<i class="bi bi-signpost-split"></i>'
                + ' Compare your laps to this reference';
            wrap.appendChild(link);
        }

        body.appendChild(wrap);

        btn.addEventListener("click", function() { toggleReplay(); });
    }

    function setMapInteraction(map, enabled) {
        if (!map) return;
        map.isScrollEnabled = enabled;
        map.isZoomEnabled = enabled;
        map.isRotationEnabled = enabled;
    }

    function currentReplayElapsed() {
        if (!replay.playing) return replay.played;
        return replay.played + (performance.now() - replay.t0) / 1000
            * replay.speed;
    }

    function toggleReplay() {
        if (replay.playing) {
            replay.played = currentReplayElapsed();
            replay.playing = false;
            cancelAnimationFrame(replay.raf);
            setMapInteraction(replay.map, true);
            replay.btn.innerHTML = '<i class="bi bi-play-fill"></i>'
                + ' Resume';
            return;
        }
        startReplay();
    }

    function setCallout(text, brake) {
        if (!replay.callout) return;
        replay.callout.textContent = text || "";
        replay.callout.classList.toggle("dna-callout-brake", !!brake);
    }

    /* the sighting-lap commentary: name the corner we are in, or the
     * one coming up, with a BRAKE flash when a zone trough is close */
    function updateCallout(s) {
        var support = card.support || {};
        var consensus = support.consensus || {};
        var corners = consensus.corners || [];
        var zones = (support.braking || {}).zones || [];
        var L = (support.trajectory || {}).length_m || 0;
        if (!corners.length || !L) { setCallout(""); return; }

        var wrapped = ((s % L) + L) % L;
        var i, c, start, end, inside;

        // inside a corner right now?
        for (i = 0; i < corners.length; i++) {
            c = corners[i];
            start = ((c.s_start % L) + L) % L;
            end = ((c.s_end % L) + L) % L;
            inside = start <= end
                ? (wrapped >= start && wrapped <= end)
                : (wrapped >= start || wrapped <= end);
            if (inside) {
                var side = c.sign < 0 ? "right" : "left";
                var text = "Turn " + (i + 1) + " — "
                    + (c.class || "corner") + " " + side;
                if (c.apex_speed_kmh)
                    text += " · ~" + Math.round(c.apex_speed_kmh)
                        + " km/h";
                setCallout(text, false);
                return;
            }
        }

        // between corners: the next one by apex
        var best = Infinity, nextIdx = -1;
        for (i = 0; i < corners.length; i++) {
            var d = ((corners[i].s_apex % L) + L) % L - wrapped;
            if (d <= 0) d += L;
            if (d > 0 && d < best) { best = d; nextIdx = i; }
        }
        if (nextIdx < 0) { setCallout(""); return; }
        var nc = corners[nextIdx];
        var nside = nc.sign < 0 ? "right" : "left";

        // brake flash when a zone trough sits just ahead
        var brake = false;
        for (i = 0; i < zones.length; i++) {
            var dz = ((zones[i].s_trough % L) + L) % L - wrapped;
            if (dz <= 0) dz += L;
            if (dz <= 35) { brake = true; break; }
        }
        setCallout(brake
            ? "BRAKE — Turn " + (nextIdx + 1) + " ahead"
            : "Next: Turn " + (nextIdx + 1) + " — "
              + (nc.class || "corner") + " " + nside, brake);
    }

    /* light corner blocks on the strip as the replay passes them */
    function markPassed(s) {
        var corners = ((card.support || {}).consensus || {}).corners || [];
        corners.forEach(function(c, i) {
            var passed = (s > c.s_end)
                && (c.s_start <= c.s_end || s < c.s_start);
            document.querySelectorAll(
                '.strip-seg[data-type="corner"][data-index="'
                + (i + 1) + '"]')
                .forEach(function(seg) {
                    seg.classList.toggle("passed", passed);
                });
        });
    }

    function clearPassed() {
        document.querySelectorAll(".dna-strip .strip-seg.passed")
            .forEach(function(seg) { seg.classList.remove("passed"); });
    }

    function startReplay() {
        var lap = card.dataset && card.dataset.lap_time_s;
        var traj = card.support && card.support.trajectory;
        var L = traj.length_m;
        withTrackMap(function(tm) {
            replay.map = tm.map;
            setMapInteraction(tm.map, false);
            if (!replay.marker) {
                replay.marker = new mapkit.Annotation(
                    new mapkit.Coordinate(traj.points[0][1],
                                          traj.points[0][2]),
                    function() {
                        var node = document.createElement("div");
                        node.className = "dna-replay-marker";
                        return node;
                    },
                    { draggable: false, enabled: false,
                      displayPriority:
                          mapkit.Annotation.DisplayPriority.Required });
                tm.map.addAnnotation(replay.marker);
            }
            replay.marker.visible = true;
            replay.playing = true;
            replay.t0 = performance.now();
            replay.btn.innerHTML = '<i class="bi bi-pause-fill"></i>'
                + ' Pause';
            if (stripCursor) stripCursor.style.display = "block";
            pulseAt({ lat: traj.points[0][1],        // S/F flash
                      lon: traj.points[0][2] });

            function frame(now) {
                if (!replay.playing) return;
                var elapsed = replay.played
                    + (now - replay.t0) / 1000 * replay.speed;
                if (elapsed >= lap) {
                    stopReplay(true);
                    return;
                }
                var s = elapsed * L / lap;
                var pos = trajAt(traj.points, s);
                if (pos) {
                    replay.marker.coordinate =
                        new mapkit.Coordinate(pos.lat, pos.lon);
                    // keep the dot visible when zoomed in: follow it
                    // (same as the race line comparison)
                    tm.map.setCenterAnimated(replay.marker.coordinate,
                                             false);
                }
                if (stripCursor)
                    stripCursor.style.left = (s / L * 100) + "%";
                updateCallout(s);
                markPassed(s);
                replay.raf = requestAnimationFrame(frame);
            }
            replay.raf = requestAnimationFrame(frame);
        });
    }

    function stopReplay(finished) {
        replay.playing = false;
        cancelAnimationFrame(replay.raf);
        replay.played = 0;
        setMapInteraction(replay.map, true);
        if (replay.marker) replay.marker.visible = false;
        if (stripCursor) stripCursor.style.display = "none";
        setCallout("");
        clearPassed();
        replay.btn.innerHTML = '<i class="bi bi-play-fill"></i>'
            + ' Replay reference lap';
        if (finished) {
            var traj = card.support && card.support.trajectory;
            if (traj && traj.points.length)
                pulseAt({ lat: traj.points[0][1],
                          lon: traj.points[0][2] });
        }
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
            if (holder) hint(holder, "Charts unavailable "
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
        renderComparison(meta, card);
        if (card.computed_at)
            meta.appendChild(el("div", null,
                "computed " + card.computed_at.slice(0, 10)
                + " · methodology v" + card.methodology_version));
        header.appendChild(meta);
        body.appendChild(header);

        renderReplayControls(body, card);
        renderSummary(body, card);
        renderDrivingNotes(body, card);
        renderLapStrip(body, card);
        renderCorners(body, card);
        renderDetails(body, card);

        loadPlotly(function() {
            renderElevation(body, card);
        }, body);

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

    // ---- skeleton while loading ----------------------------------------------------

    function showSkeleton() {
        var block = el("div", "card mb-3 dna-skel");
        var body = el("div", "card-body");
        for (var i = 0; i < 3; i++) {
            body.appendChild(el("div", "dna-skel-bar"));
        }
        block.appendChild(body);
        container.appendChild(block);
        return block;
    }

    function init() {
        container = document.getElementById("track-dna");
        if (!container) return;
        trackId = parseInt(container.dataset.trackId, 10);
        var best = parseFloat(container.dataset.userBestLap);
        userBestLap = isFinite(best) ? best : null;
        var cs = parseInt(container.dataset.compareSession, 10);
        compareSessionId = isFinite(cs) ? cs : null;

        var skel = null;
        var timer = setTimeout(function() {
            container.hidden = false;
            skel = showSkeleton();
        }, 200);

        api("/dna").then(function(payload) {
            clearTimeout(timer);
            if (skel) skel.remove();
            if (!payload || !payload.card) {
                container.hidden = true;      // no card: back to hidden
                return;
            }
            card = payload.card;
            container.hidden = false;
            render();
        });
    }

    return { init: init };
})();

window.TrackDNA.init();
