/* MapKit JS track map helpers — shared by dashboard and raceline */
window.MapHelpers = (function() {
    var SCALES = {
        RdYlGn: [[0,"#a50026"],[0.1,"#d73027"],[0.2,"#f46d43"],[0.3,"#fdae61"],[0.4,"#fee08b"],[0.5,"#ffffbf"],[0.6,"#d9ef8b"],[0.7,"#a6d96a"],[0.8,"#66bd63"],[0.9,"#1a9850"],[1,"#006837"]],
        RdYlGn_r: [[0,"#006837"],[0.1,"#1a9850"],[0.2,"#66bd63"],[0.3,"#a6d96a"],[0.4,"#d9ef8b"],[0.5,"#ffffbf"],[0.6,"#fee08b"],[0.7,"#fdae61"],[0.8,"#f46d43"],[0.9,"#d73027"],[1,"#a50026"]],
        RdYlBu: [[0,"#a50026"],[0.1,"#d73027"],[0.2,"#f46d43"],[0.3,"#fdae61"],[0.4,"#fee090"],[0.5,"#ffffbf"],[0.6,"#e0f3f8"],[0.7,"#abd9e9"],[0.8,"#74add1"],[0.9,"#4575b4"],[1,"#313695"]]
    };

    function hexToRgb(hex) {
        var r = parseInt(hex.slice(1,3),16), g = parseInt(hex.slice(3,5),16), b = parseInt(hex.slice(5,7),16);
        return [r,g,b];
    }

    function colorscaleRGB(name, frac) {
        frac = Math.max(0, Math.min(1, frac));
        var stops = SCALES[name] || SCALES.RdYlGn;
        if (frac <= stops[0][0]) return hexToRgb(stops[0][1]);
        if (frac >= stops[stops.length-1][0]) return hexToRgb(stops[stops.length-1][1]);
        for (var i = 1; i < stops.length; i++) {
            if (frac <= stops[i][0]) {
                var t = (frac - stops[i-1][0]) / (stops[i][0] - stops[i-1][0]);
                var a = hexToRgb(stops[i-1][1]), b = hexToRgb(stops[i][1]);
                return [Math.round(a[0]+(b[0]-a[0])*t), Math.round(a[1]+(b[1]-a[1])*t), Math.round(a[2]+(b[2]-a[2])*t)];
            }
        }
        return hexToRgb(stops[stops.length-1][1]);
    }

    function valueFrac(val, data) {
        var cb = data.colorbar;
        if (data.cmid !== null && data.cmid !== undefined) {
            var absMax = Math.max(Math.abs(cb.min - data.cmid), Math.abs(cb.max - data.cmid));
            if (absMax === 0) return 0.5;
            return 0.5 + (val - data.cmid) / (2 * absMax);
        }
        if (cb.max === cb.min) return 0.5;
        return (val - cb.min) / (cb.max - cb.min);
    }

    function waitForMapKit(cb) {
        if (typeof mapkit !== "undefined") { cb(); return; }
        var tries = 0;
        var iv = setInterval(function() {
            tries++;
            if (typeof mapkit !== "undefined") { clearInterval(iv); cb(); }
            else if (tries > 100) { clearInterval(iv); console.warn("MapKit JS failed to load"); }
        }, 100);
    }

    function initMapKit(token) {
        if (!token) return;
        waitForMapKit(function() {
            mapkit.init({ authorizationCallback: function(done) { done(token); } });
        });
    }

    function initSatMap(elementId, lat, lon) {
        var latMin = Math.min.apply(null, lat), latMax = Math.max.apply(null, lat);
        var lonMin = Math.min.apply(null, lon), lonMax = Math.max.apply(null, lon);
        var pad = 0.15;
        var latPad = (latMax - latMin) * pad, lonPad = (lonMax - lonMin) * pad;
        var region = new mapkit.BoundingRegion(latMax + latPad, lonMax + lonPad, latMin - latPad, lonMin - lonPad);
        return new mapkit.Map(elementId, {
            mapType: mapkit.Map.MapTypes.Satellite,
            showsCompass: mapkit.FeatureVisibility.Hidden,
            showsMapTypeControl: false,
            showsZoomControl: false,
            isScrollEnabled: false,
            isZoomEnabled: false,
            isRotationEnabled: false,
            region: region.toCoordinateRegion()
        });
    }

    function drawDots(canvas, map, data) {
        var dpr = window.devicePixelRatio || 1;
        var rect = canvas.getBoundingClientRect();
        if (rect.width === 0 || rect.height === 0) return;
        canvas.width = rect.width * dpr;
        canvas.height = rect.height * dpr;
        var ctx = canvas.getContext("2d");
        ctx.scale(dpr, dpr);
        ctx.clearRect(0, 0, rect.width, rect.height);

        var len = data.lat.length;
        var r = 3;
        for (var i = 0; i < len; i++) {
            var pt = map.convertCoordinateToPointOnPage(new mapkit.Coordinate(data.lat[i], data.lon[i]));
            if (!pt) continue;
            var x = pt.x - rect.left - window.scrollX, y = pt.y - rect.top - window.scrollY;
            if (x < -10 || x > rect.width + 10 || y < -10 || y > rect.height + 10) continue;
            var frac = valueFrac(data.values[i], data);
            var rgb = colorscaleRGB(data.colorscale, frac);
            ctx.fillStyle = "rgb(" + rgb[0] + "," + rgb[1] + "," + rgb[2] + ")";
            ctx.beginPath();
            ctx.arc(x, y, r, 0, 6.283);
            ctx.fill();
        }
    }

    function setupTrackMap(mapElId, canvasId, wrapId, data) {
        if (!data) return null;
        var map = initSatMap(mapElId, data.lat, data.lon);
        var canvas = document.getElementById(canvasId);
        var wrap = document.getElementById(wrapId);
        var currentData = data;
        var overlayContainer = document.createElement("div");
        overlayContainer.className = "map-overlays";
        wrap.appendChild(overlayContainer);

        function addOverlayElements(d) {
            overlayContainer.innerHTML = "";
            var titleEl = document.createElement("div");
            titleEl.className = "map-title";
            titleEl.textContent = d.title;
            overlayContainer.appendChild(titleEl);
            var cb = d.colorbar;
            var stops = SCALES[d.colorscale] || SCALES.RdYlGn;
            var gradStops = stops.map(function(s) { return s[1] + " " + (s[0]*100) + "%"; }).reverse();
            var bar = document.createElement("div");
            bar.className = "map-colorbar";
            bar.style.background = "linear-gradient(to bottom," + gradStops.join(",") + ")";
            bar.innerHTML = '<div class="cb-title">' + cb.title + '</div>'
                + '<div class="cb-label top">' + cb.max + '</div>'
                + '<div class="cb-label bottom">' + cb.min + '</div>';
            if (d.cmid !== null && d.cmid !== undefined) {
                bar.innerHTML += '<div class="cb-label mid">' + d.cmid + '</div>';
            }
            overlayContainer.appendChild(bar);
            var labels = [];
            if (d.corners) {
                d.corners.forEach(function(c) {
                    var el = document.createElement("div");
                    el.className = "corner-label";
                    el.textContent = c.label;
                    overlayContainer.appendChild(el);
                    labels.push({ el: el, lat: c.lat, lon: c.lon });
                });
            }
            if (d.wind) {
                var windEl = document.createElement("div");
                windEl.className = "map-wind";
                windEl.innerHTML = '<span class="arrow" style="display:inline-block;transform:rotate(' + d.wind.arrow_deg + 'deg)">&#8593;</span><br>' + d.wind.cardinal + " " + d.wind.speed_kmh + " km/h";
                overlayContainer.appendChild(windEl);
            }
            var tooltip = document.createElement("div");
            tooltip.className = "map-tooltip";
            overlayContainer.appendChild(tooltip);
            return { labels: labels, tooltip: tooltip };
        }

        var overlayState = addOverlayElements(data);
        var screenPts = [];

        function positionLabels() {
            var rect = wrap.getBoundingClientRect();
            overlayState.labels.forEach(function(lb) {
                var pt = map.convertCoordinateToPointOnPage(new mapkit.Coordinate(lb.lat, lb.lon));
                if (!pt) return;
                lb.el.style.left = (pt.x - window.scrollX - rect.left) + "px";
                lb.el.style.top = (pt.y - window.scrollY - rect.top - 8) + "px";
            });
        }

        function redraw() {
            try { drawDots(canvas, map, currentData); } catch(e) { console.warn("drawDots error:", e); }
            positionLabels();
            screenPts = [];
        }
        map.addEventListener("region-change-end", redraw);
        [500, 1000, 2000, 4000].forEach(function(ms) { setTimeout(redraw, ms); });
        window.addEventListener("resize", redraw);
        window.addEventListener("scroll", redraw);

        var unit = data.colorbar.title || "";
        function ensureScreenPts() {
            if (screenPts.length > 0) return;
            var rect = canvas.getBoundingClientRect();
            for (var i = 0; i < currentData.lat.length; i++) {
                var pt = map.convertCoordinateToPointOnPage(new mapkit.Coordinate(currentData.lat[i], currentData.lon[i]));
                if (pt) screenPts.push({ x: pt.x - window.scrollX - rect.left, y: pt.y - window.scrollY - rect.top, idx: i });
            }
        }
        wrap.addEventListener("mousemove", function(e) {
            ensureScreenPts();
            var rect = canvas.getBoundingClientRect();
            var mx = e.clientX - rect.left, my = e.clientY - rect.top;
            var bestDist = 100, bestIdx = -1;
            for (var i = 0; i < screenPts.length; i++) {
                var dx = screenPts[i].x - mx, dy = screenPts[i].y - my;
                var d = dx * dx + dy * dy;
                if (d < bestDist) { bestDist = d; bestIdx = screenPts[i].idx; }
            }
            if (bestIdx >= 0) {
                overlayState.tooltip.textContent = currentData.values[bestIdx] + " " + unit;
                overlayState.tooltip.style.display = "block";
                overlayState.tooltip.style.left = (e.clientX - rect.left + 12) + "px";
                overlayState.tooltip.style.top = (e.clientY - rect.top - 10) + "px";
            } else {
                overlayState.tooltip.style.display = "none";
            }
        });
        wrap.addEventListener("mouseleave", function() { overlayState.tooltip.style.display = "none"; });

        return {
            map: map,
            update: function(newData) {
                if (!newData) return;
                currentData = newData;
                unit = newData.colorbar.title || "";
                overlayState = addOverlayElements(newData);
                screenPts = [];
                redraw();
            }
        };
    }

    return {
        SCALES: SCALES,
        waitForMapKit: waitForMapKit,
        initMapKit: initMapKit,
        initSatMap: initSatMap,
        drawDots: drawDots,
        setupTrackMap: setupTrackMap,
        colorscaleRGB: colorscaleRGB,
        valueFrac: valueFrac
    };
})();
