/* Racing Line A/B comparison on MapKit JS */
window.Raceline = (function() {
    var rlColorA = "#22c55e", rlColorB = "#3b82f6";
    var rlMap = null, rlOverlays = [];
    var animPlaying = false, animTime = 0, animMaxTime = 0;
    var animRAF = null, animLastTS = null, animSpeed = 2;
    var markerMeta = [];
    var rlData = null;

    function interpPos(lap, t) {
        if (!lap.t || lap.t.length === 0) return null;
        if (t <= lap.t[0]) return {lat: lap.lat[0], lon: lap.lon[0]};
        if (t >= lap.t[lap.t.length - 1]) return {lat: lap.lat[lap.lat.length - 1], lon: lap.lon[lap.lon.length - 1]};
        var lo = 0, hi = lap.t.length - 1;
        while (hi - lo > 1) { var mid = (lo + hi) >> 1; if (lap.t[mid] <= t) lo = mid; else hi = mid; }
        var frac = (t - lap.t[lo]) / (lap.t[hi] - lap.t[lo]);
        return {
            lat: lap.lat[lo] + frac * (lap.lat[hi] - lap.lat[lo]),
            lon: lap.lon[lo] + frac * (lap.lon[hi] - lap.lon[lo])
        };
    }

    function drawMarkers() {
        var canvas = document.getElementById("racelineCanvas");
        if (!canvas || !rlMap) return;
        var dpr = window.devicePixelRatio || 1;
        var rect = canvas.getBoundingClientRect();
        if (rect.width === 0 || rect.height === 0) return;
        canvas.width = rect.width * dpr;
        canvas.height = rect.height * dpr;
        var ctx = canvas.getContext("2d");
        ctx.scale(dpr, dpr);
        ctx.clearRect(0, 0, rect.width, rect.height);
        for (var i = 0; i < markerMeta.length; i++) {
            var mt = markerMeta[i];
            var pos = interpPos(mt.lap, animTime);
            if (!pos) continue;
            var pt = rlMap.convertCoordinateToPointOnPage(new mapkit.Coordinate(pos.lat, pos.lon));
            if (!pt) continue;
            var x = pt.x - rect.left - window.scrollX, y = pt.y - rect.top - window.scrollY;
            ctx.fillStyle = mt.color;
            ctx.beginPath();
            ctx.arc(x, y, 5, 0, 6.283);
            ctx.fill();
        }
    }

    function parseLapRef(val) {
        if (!val) return null;
        var parts = val.split("-");
        var si = parseInt(parts[0]), li = parseInt(parts[1]);
        return rlData.sessions[si] ? rlData.sessions[si].laps[li] || null : null;
    }

    function addPolyline(lap, color, opacity) {
        var coords = lap.lat.map(function(lat, i) {
            return new mapkit.Coordinate(lat, lap.lon[i]);
        });
        var style = new mapkit.Style({ strokeColor: color, lineWidth: 3, strokeOpacity: opacity });
        var overlay = new mapkit.PolylineOverlay(coords, { style: style });
        rlOverlays.push(overlay);
        rlMap.addOverlay(overlay);
        if (lap.t && lap.t.length > 0) {
            markerMeta.push({lap: lap, color: color});
            var lapEnd = lap.t[lap.t.length - 1];
            if (lapEnd > animMaxTime) animMaxTime = lapEnd;
        }
    }

    function setMapInteraction(enabled) {
        if (!rlMap) return;
        rlMap.isScrollEnabled = enabled;
        rlMap.isZoomEnabled = enabled;
        rlMap.isRotationEnabled = enabled;
    }

    function panToMarkers() {
        if (!rlMap || markerMeta.length === 0) return;
        var sumLat = 0, sumLon = 0, n = 0;
        for (var i = 0; i < markerMeta.length; i++) {
            var pos = interpPos(markerMeta[i].lap, animTime);
            if (!pos) continue;
            sumLat += pos.lat;
            sumLon += pos.lon;
            n++;
        }
        if (n === 0) return;
        rlMap.setCenterAnimated(new mapkit.Coordinate(sumLat / n, sumLon / n), false);
    }

    function stopAnim() {
        animPlaying = false;
        var btn = document.getElementById("rlPlayBtn");
        if (btn) btn.innerHTML = "&#9654;";
        if (animRAF) cancelAnimationFrame(animRAF);
        animRAF = null;
        setMapInteraction(true);
    }

    function updateMarkers() {
        if (animPlaying) panToMarkers();
        drawMarkers();
        var slider = document.getElementById("rlTimeline");
        var display = document.getElementById("rlTimeDisplay");
        if (slider) slider.value = animTime.toFixed(1);
        if (display) display.textContent = animTime.toFixed(1) + "s";
    }

    function animFrame(timestamp) {
        if (!animPlaying) return;
        if (animLastTS === null) animLastTS = timestamp;
        var dt = (timestamp - animLastTS) / 1000.0;
        animLastTS = timestamp;
        animTime += dt * animSpeed;
        if (animTime >= animMaxTime) { animTime = animMaxTime; updateMarkers(); stopAnim(); return; }
        updateMarkers();
        animRAF = requestAnimationFrame(animFrame);
    }

    function startAnim() {
        if (markerMeta.length === 0) return;
        setMapInteraction(false);
        animPlaying = true; animLastTS = null;
        var btn = document.getElementById("rlPlayBtn");
        if (btn) btn.innerHTML = "&#9646;&#9646;";
        animRAF = requestAnimationFrame(animFrame);
    }

    function renderRaceline() {
        stopAnim();
        animTime = 0; animMaxTime = 0; markerMeta = [];
        if (rlMap) rlMap.removeOverlays(rlOverlays);
        rlOverlays = [];

        var lapA = parseLapRef(document.getElementById("rlSelectA").value);
        var lapB = parseLapRef(document.getElementById("rlSelectB").value);
        if (!lapA) return;

        var allLat = [].concat(lapA.lat), allLon = [].concat(lapA.lon);
        if (lapB) { allLat = allLat.concat(lapB.lat); allLon = allLon.concat(lapB.lon); }

        if (!rlMap) {
            rlMap = MapHelpers.initSatMap("racelineMap", allLat, allLon);
            rlMap.isScrollEnabled = true;
            rlMap.isZoomEnabled = true;
            rlMap.isRotationEnabled = true;
            rlMap.showsZoomControl = true;
            rlMap.addEventListener("region-change-start", function() {
                if (!animPlaying) document.getElementById("racelineCanvas").style.visibility = "hidden";
            });
            rlMap.addEventListener("region-change-end", function() {
                document.getElementById("racelineCanvas").style.visibility = "visible";
                drawMarkers();
            });
        }

        addPolyline(lapA, rlColorA, 1.0);
        if (lapB) addPolyline(lapB, rlColorB, 0.6);

        // Legend
        var legendEl = document.getElementById("racelineLegend");
        legendEl.innerHTML = "";
        [{label: "Lap A", lap: lapA, color: rlColorA}, {label: "Lap B", lap: lapB, color: rlColorB}].forEach(function(entry) {
            if (!entry.lap) return;
            var item = document.createElement("span");
            item.style.cssText = "display:inline-flex;align-items:center;gap:4px;";
            var dot = document.createElement("span");
            dot.style.cssText = "width:8px;height:8px;border-radius:50%;flex-shrink:0;background:" + entry.color + ";";
            item.appendChild(dot);
            item.appendChild(document.createTextNode(entry.label + ": " + entry.lap.time_fmt));
            legendEl.appendChild(item);
        });

        // Delta display
        var deltaEl = document.getElementById("rlDeltaDisplay");
        if (lapA && lapB) {
            var delta = lapB.seconds - lapA.seconds;
            var absDelta = Math.abs(delta).toFixed(3);
            if (delta > 0.001) {
                deltaEl.innerHTML = '<span style="background:#22c55e22;color:#22c55e;padding:2px 8px;border-radius:12px;font-weight:600;">A faster by ' + absDelta + 's</span>';
            } else if (delta < -0.001) {
                deltaEl.innerHTML = '<span style="background:#3b82f622;color:#3b82f6;padding:2px 8px;border-radius:12px;font-weight:600;">B faster by ' + absDelta + 's</span>';
            } else {
                deltaEl.innerHTML = '<span style="background:#88888822;color:#888;padding:2px 8px;border-radius:12px;">Equal</span>';
            }
        } else {
            deltaEl.innerHTML = "";
        }

        var slider = document.getElementById("rlTimeline");
        slider.max = animMaxTime > 0 ? animMaxTime.toFixed(1) : "100";
        slider.value = "0";
        document.getElementById("rlTimeDisplay").textContent = "0.0s";
        drawMarkers();
    }

    function init(data) {
        rlData = data;
        if (!rlData) return;
        if (!rlData.sessions && (!rlData.laps || rlData.laps.length === 0)) return;

        // Wrap single-session raceline into sessions format
        if (!rlData.sessions) {
            rlData = { sessions: [{ laps: rlData.laps, is_current: true, date: "", session_type: "" }] };
        }

        // Populate Lap A selector
        var selA = document.getElementById("rlSelectA");
        selA.innerHTML = "";
        rlData.sessions.forEach(function(session, si) {
            if (!session.is_current) return;
            session.laps.forEach(function(lap, li) {
                if (lap.is_outlier) return;
                var opt = document.createElement("option");
                opt.value = si + "-" + li;
                opt.textContent = "Lap " + lap.lap + " \u2014 " + lap.time_fmt + (lap.is_best ? " (best)" : "");
                if (lap.is_best) opt.selected = true;
                selA.appendChild(opt);
            });
        });

        // Populate session B selector
        var selBS = document.getElementById("rlSelectBSession");
        selBS.innerHTML = '<option value="">&mdash; Session &mdash;</option>';
        rlData.sessions.forEach(function(session, si) {
            var opt = document.createElement("option");
            opt.value = si;
            opt.textContent = (session.date || "Current") + (session.session_type ? " \u2014 " + session.session_type : "") + (session.is_current ? " (current)" : "");
            selBS.appendChild(opt);
        });

        // Events
        document.getElementById("rlPlayBtn").addEventListener("click", function() {
            if (animPlaying) stopAnim();
            else { if (animTime >= animMaxTime) animTime = 0; startAnim(); }
        });
        document.getElementById("rlTimeline").addEventListener("input", function() {
            animTime = parseFloat(this.value); if (animPlaying) stopAnim(); updateMarkers();
        });
        document.getElementById("rlSpeedSelect").addEventListener("change", function() { animSpeed = parseFloat(this.value); });
        selA.addEventListener("change", renderRaceline);
        document.getElementById("rlSelectB").addEventListener("change", renderRaceline);

        selBS.addEventListener("change", function() {
            var si = this.value;
            var selB = document.getElementById("rlSelectB");
            selB.innerHTML = '<option value="">&mdash; Lap &mdash;</option>';
            if (si === "") { selB.disabled = true; renderRaceline(); return; }
            var session = rlData.sessions[parseInt(si)];
            if (!session) { selB.disabled = true; renderRaceline(); return; }
            session.laps.forEach(function(lap, li) {
                if (lap.is_outlier) return;
                var opt = document.createElement("option");
                opt.value = si + "-" + li;
                opt.textContent = "Lap " + lap.lap + " \u2014 " + lap.time_fmt + (lap.is_best ? " (best)" : "");
                selB.appendChild(opt);
            });
            selB.disabled = false;
            renderRaceline();
        });

        // Pre-select Lap B: current session, first clean lap that isn't Lap A
        for (var si = 0; si < rlData.sessions.length; si++) {
            if (rlData.sessions[si].is_current) {
                selBS.value = String(si);
                selBS.dispatchEvent(new Event("change"));
                var selB = document.getElementById("rlSelectB");
                for (var i = 1; i < selB.options.length; i++) {
                    if (selB.options[i].value !== selA.value) {
                        selB.value = selB.options[i].value;
                        break;
                    }
                }
                break;
            }
        }
        renderRaceline();
    }

    return { init: init };
})();
