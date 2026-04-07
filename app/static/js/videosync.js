/* Video Sync — GoPro video + racing line dot sync on MapKit JS */
window.VideoSync = (function() {
    var vsMap = null, vsOverlays = [];
    var currentLap = null, currentMapMode = "none";
    var video = null, canvas = null, mapWrap = null;
    var sessionId = null, apiBase = null, shareToken = "", csrfToken = "";
    var trackMapRef = null;
    var mapDataCache = {};
    var rafId = null;
    var racelineLaps = null;
    var lapStart = 0, lapEnd = 0, clamping = false;
    var fullTrackRegion = null, isPlaying = false;

    function api(path) {
        var url = apiBase + path;
        if (shareToken) url += (url.indexOf("?") !== -1 ? "&" : "?") + "share_token=" + shareToken;
        return fetch(url, { credentials: "same-origin" })
            .then(function(r) { return r.ok ? r.json() : null; })
            .catch(function() { return null; });
    }

    function interpPos(lap, t) {
        if (!lap.t || lap.t.length === 0) return null;
        if (t <= lap.t[0]) return { lat: lap.lat[0], lon: lap.lon[0] };
        if (t >= lap.t[lap.t.length - 1]) return { lat: lap.lat[lap.lat.length - 1], lon: lap.lon[lap.lon.length - 1] };
        var lo = 0, hi = lap.t.length - 1;
        while (hi - lo > 1) { var mid = (lo + hi) >> 1; if (lap.t[mid] <= t) lo = mid; else hi = mid; }
        var frac = (t - lap.t[lo]) / (lap.t[hi] - lap.t[lo]);
        return {
            lat: lap.lat[lo] + frac * (lap.lat[hi] - lap.lat[lo]),
            lon: lap.lon[lo] + frac * (lap.lon[hi] - lap.lon[lo])
        };
    }

    function drawPositionDot() {
        if (!canvas || !vsMap || !currentLap || !video) return;
        var dpr = window.devicePixelRatio || 1;
        var rect = canvas.getBoundingClientRect();
        if (rect.width === 0 || rect.height === 0) return;
        canvas.width = rect.width * dpr;
        canvas.height = rect.height * dpr;
        var ctx = canvas.getContext("2d");
        ctx.scale(dpr, dpr);
        ctx.clearRect(0, 0, rect.width, rect.height);

        var tOffset = currentLap.t_offset || 0;
        var t = video.currentTime - tOffset;
        var pos = interpPos(currentLap, t);
        if (!pos) return;

        var pt = vsMap.convertCoordinateToPointOnPage(new mapkit.Coordinate(pos.lat, pos.lon));
        if (!pt) return;
        var x = pt.x - rect.left - window.scrollX;
        var y = pt.y - rect.top - window.scrollY;

        ctx.strokeStyle = "rgba(0,0,0,0.7)";
        ctx.lineWidth = 2;
        ctx.fillStyle = "#ffffff";
        ctx.beginPath();
        ctx.arc(x, y, 7, 0, 6.283);
        ctx.fill();
        ctx.stroke();
    }

    function setMapInteraction(enabled) {
        if (!vsMap) return;
        vsMap.isScrollEnabled = enabled;
        vsMap.isZoomEnabled = enabled;
        vsMap.isRotationEnabled = enabled;
    }

    function panToDot() {
        if (!vsMap || !currentLap || !video) return;
        var tOffset = currentLap.t_offset || 0;
        var t = video.currentTime - tOffset;
        var pos = interpPos(currentLap, t);
        if (!pos) return;
        vsMap.setCenterAnimated(new mapkit.Coordinate(pos.lat, pos.lon), false);
    }

    function zoomToFollow() {
        if (!vsMap) return;
        // Zoom in to ~0.002 degree span for close tracking
        var span = new mapkit.CoordinateSpan(0.002, 0.002);
        var tOffset = currentLap.t_offset || 0;
        var t = video.currentTime - tOffset;
        var pos = interpPos(currentLap, t);
        if (!pos) return;
        var region = new mapkit.CoordinateRegion(
            new mapkit.Coordinate(pos.lat, pos.lon), span
        );
        vsMap.setRegionAnimated(region, true);
    }

    function zoomToFullTrack() {
        if (!vsMap || !fullTrackRegion) return;
        vsMap.setRegionAnimated(fullTrackRegion, true);
    }

    function animLoop() {
        panToDot();
        drawPositionDot();
        if (video && !video.paused && !video.ended) {
            rafId = requestAnimationFrame(animLoop);
        }
    }

    function clearMap() {
        if (vsMap && vsOverlays.length > 0) {
            vsMap.removeOverlays(vsOverlays);
        }
        vsOverlays = [];
        if (trackMapRef) {
            trackMapRef = null;
        }
    }

    function addPolyline(lap, color) {
        if (!vsMap) return;
        var coords = lap.lat.map(function(lat, i) {
            return new mapkit.Coordinate(lat, lap.lon[i]);
        });
        var style = new mapkit.Style({ strokeColor: color, lineWidth: 3, strokeOpacity: 1.0 });
        var overlay = new mapkit.PolylineOverlay(coords, { style: style });
        vsOverlays.push(overlay);
        vsMap.addOverlay(overlay);
    }

    function computeTrackRegion(lap) {
        var latMin = Math.min.apply(null, lap.lat), latMax = Math.max.apply(null, lap.lat);
        var lonMin = Math.min.apply(null, lap.lon), lonMax = Math.max.apply(null, lap.lon);
        var pad = 0.15;
        var latPad = (latMax - latMin) * pad, lonPad = (lonMax - lonMin) * pad;
        return new mapkit.BoundingRegion(latMax + latPad, lonMax + lonPad, latMin - latPad, lonMin - lonPad).toCoordinateRegion();
    }

    function initMap(lap) {
        fullTrackRegion = computeTrackRegion(lap);
        if (!vsMap) {
            vsMap = MapHelpers.initSatMap("vsMap", lap.lat, lap.lon);
            vsMap.isScrollEnabled = true;
            vsMap.isZoomEnabled = true;
            vsMap.isRotationEnabled = true;
            vsMap.showsZoomControl = true;
            vsMap.addEventListener("region-change-start", function() {
                if (!isPlaying) canvas.style.visibility = "hidden";
            });
            vsMap.addEventListener("region-change-end", function() {
                canvas.style.visibility = "visible";
                drawPositionDot();
            });
        } else {
            vsMap.setRegionAnimated(fullTrackRegion, false);
        }
    }

    function applyMapMode(lap, mode) {
        currentMapMode = mode;

        if (mode === "none") {
            clearMap();
            addPolyline(lap, "#22c55e");
            return;
        }

        var chartType = mode === "speed" ? "speed_map" : "braking_map";
        var cacheKey = chartType + "_" + lap.lap;

        if (mapDataCache[cacheKey]) {
            renderHeatmap(lap, mapDataCache[cacheKey]);
            return;
        }

        api("/charts/" + chartType + "/" + lap.lap).then(function(data) {
            if (!data) {
                clearMap();
                addPolyline(lap, "#22c55e");
                return;
            }
            mapDataCache[cacheKey] = data;
            renderHeatmap(lap, data);
        });
    }

    function renderHeatmap(lap, data) {
        clearMap();
        var heatCanvas = document.getElementById("vsHeatCanvas");
        if (!heatCanvas) return;
        MapHelpers.drawDots(heatCanvas, vsMap, data);

        var overlayContainer = mapWrap.querySelector(".vs-map-overlays");
        if (!overlayContainer) {
            overlayContainer = document.createElement("div");
            overlayContainer.className = "vs-map-overlays map-overlays";
            mapWrap.appendChild(overlayContainer);
        }
        overlayContainer.innerHTML = "";

        if (data.title) {
            var titleEl = document.createElement("div");
            titleEl.className = "map-title";
            titleEl.textContent = data.title;
            overlayContainer.appendChild(titleEl);
        }

        if (data.colorbar && data.show_colorbar !== false) {
            var scales = MapHelpers.SCALES;
            var stops = scales[data.colorscale] || scales.RdYlGn;
            var gradStops = stops.map(function(s) { return s[1] + " " + (s[0]*100) + "%"; });
            var bar = document.createElement("div");
            bar.className = "map-colorbar";
            bar.style.background = "linear-gradient(to top," + gradStops.join(",") + ")";
            bar.innerHTML = '<div class="cb-title">' + data.colorbar.title + '</div>'
                + '<div class="cb-label top">' + data.colorbar.max + '</div>'
                + '<div class="cb-label bottom">' + data.colorbar.min + '</div>';
            if (data.cmid !== null && data.cmid !== undefined) {
                bar.innerHTML += '<div class="cb-label mid">' + data.cmid + '</div>';
            }
            overlayContainer.appendChild(bar);
        }

        if (data.corners) {
            data.corners.forEach(function(c) {
                var el = document.createElement("div");
                el.className = "corner-label";
                el.textContent = c.label;
                overlayContainer.appendChild(el);
                var rect = mapWrap.getBoundingClientRect();
                var pt = vsMap.convertCoordinateToPointOnPage(new mapkit.Coordinate(c.lat, c.lon));
                if (pt) {
                    el.style.left = (pt.x - window.scrollX - rect.left) + "px";
                    el.style.top = (pt.y - window.scrollY - rect.top - 8) + "px";
                }
            });
        }

        vsMap.addEventListener("region-change-end", function redrawHeat() {
            if (currentMapMode === "none") {
                vsMap.removeEventListener("region-change-end", redrawHeat);
                return;
            }
            var hc = document.getElementById("vsHeatCanvas");
            if (hc) MapHelpers.drawDots(hc, vsMap, data);
            if (data.corners && overlayContainer.parentNode) {
                var rect = mapWrap.getBoundingClientRect();
                var labels = overlayContainer.querySelectorAll(".corner-label");
                labels.forEach(function(el, i) {
                    if (!data.corners[i]) return;
                    var pt = vsMap.convertCoordinateToPointOnPage(new mapkit.Coordinate(data.corners[i].lat, data.corners[i].lon));
                    if (pt) {
                        el.style.left = (pt.x - window.scrollX - rect.left) + "px";
                        el.style.top = (pt.y - window.scrollY - rect.top - 8) + "px";
                    }
                });
            }
        });
    }

    function selectLap(lap) {
        currentLap = lap;
        if (!lap) return;

        // Compute lap time boundaries in video time
        lapStart = lap.t_offset || 0;
        lapEnd = lapStart + (lap.t && lap.t.length > 0 ? lap.t[lap.t.length - 1] : 0);

        initMap(lap);
        applyMapMode(lap, currentMapMode);

        if (video && video.src && lap.t_offset != null) {
            video.currentTime = lapStart;
        }
        drawPositionDot();
    }

    function clampToLap() {
        if (!video || !currentLap || clamping) return;
        if (video.currentTime < lapStart) {
            clamping = true;
            video.currentTime = lapStart;
            clamping = false;
        } else if (video.currentTime >= lapEnd) {
            clamping = true;
            video.pause();
            video.currentTime = lapEnd;
            clamping = false;
        }
    }

    function saveFilename(filename) {
        fetch(apiBase + "/video-filename", {
            method: "PUT",
            headers: { "Content-Type": "application/json", "X-Requested-With": "fetch", "X-CSRFToken": csrfToken },
            credentials: "same-origin",
            body: JSON.stringify({ filename: filename })
        }).catch(function() {});
    }

    function loadVideo(file) {
        var url = URL.createObjectURL(file);
        var prompt = document.getElementById("vsPrompt");
        var player = document.getElementById("vsPlayer");

        // Transition to player state
        prompt.style.display = "none";
        player.style.display = "";

        // Set up references now that player is visible
        canvas = document.getElementById("vsPositionCanvas");
        mapWrap = document.getElementById("vsMapWrap");
        video = document.getElementById("vsVideo");
        video.src = url;

        document.getElementById("vsFileLabel").textContent = file.name;
        saveFilename(file.name);

        // Populate lap selector
        var lapSelect = document.getElementById("vsLapSelect");
        lapSelect.innerHTML = "";
        var bestLap = null;
        racelineLaps.forEach(function(lap) {
            if (lap.is_outlier) return;
            var opt = document.createElement("option");
            opt.value = lap.lap;
            opt.textContent = "Lap " + lap.lap + " \u2014 " + lap.time_fmt + (lap.is_best ? " (best)" : "");
            if (lap.is_best) { opt.selected = true; bestLap = lap; }
            lapSelect.appendChild(opt);
        });

        lapSelect.addEventListener("change", function() {
            var lapNum = parseInt(this.value);
            var lap = racelineLaps.find(function(l) { return l.lap === lapNum; });
            if (lap) selectLap(lap);
        });

        // Map mode selector
        document.getElementById("vsMapMode").addEventListener("change", function() {
            if (currentLap) applyMapMode(currentLap, this.value);
        });

        // Video sync events
        video.addEventListener("play", function() {
            clampToLap();
            isPlaying = true;
            setMapInteraction(false);
            zoomToFollow();
            if (rafId) cancelAnimationFrame(rafId);
            rafId = requestAnimationFrame(animLoop);
        });
        video.addEventListener("pause", function() {
            isPlaying = false;
            if (rafId) { cancelAnimationFrame(rafId); rafId = null; }
            setMapInteraction(true);
            zoomToFullTrack();
            drawPositionDot();
        });
        video.addEventListener("seeked", function() {
            clampToLap();
            drawPositionDot();
        });
        video.addEventListener("timeupdate", function() {
            clampToLap();
        });
        video.addEventListener("ended", function() {
            isPlaying = false;
            if (rafId) { cancelAnimationFrame(rafId); rafId = null; }
            setMapInteraction(true);
            zoomToFullTrack();
        });

        // Auto-seek to lap start once metadata loads
        video.addEventListener("loadedmetadata", function onMeta() {
            video.removeEventListener("loadedmetadata", onMeta);
            var lap = bestLap || racelineLaps[0];
            if (lap) selectLap(lap);
        });
    }

    function init(racelineData, opts) {
        sessionId = opts.sessionId;
        apiBase = opts.apiBase;
        shareToken = opts.shareToken || "";
        csrfToken = opts.csrfToken || "";
        var videoFilename = opts.videoFilename || "";

        if (!racelineData || !racelineData.laps || racelineData.laps.length === 0) {
            document.getElementById("vsContent").innerHTML =
                '<div class="text-center text-muted p-5"><i class="bi bi-exclamation-circle" style="font-size:2rem;"></i><p class="mt-2">No raceline data available. Try reingesting this session.</p></div>';
            return;
        }

        var hasOffset = racelineData.laps.some(function(l) { return l.t_offset != null; });
        if (!hasOffset) {
            document.getElementById("vsContent").innerHTML =
                '<div class="text-center text-muted p-5"><i class="bi bi-arrow-repeat" style="font-size:2rem;"></i><p class="mt-2">This session needs to be reingested to enable video sync.<br>Go to the session editor and click "Reingest".</p></div>';
            return;
        }

        racelineLaps = racelineData.laps;

        // Set prompt button label
        var promptBtnLabel = document.getElementById("vsPromptBtnLabel");
        if (videoFilename) {
            promptBtnLabel.textContent = "Re-select: " + videoFilename;
        }

        // File input (shared by prompt and change-video link)
        var fileInput = document.getElementById("vsFileInput");
        fileInput.addEventListener("change", function() {
            if (this.files.length === 0) return;
            loadVideo(this.files[0]);
        });

        // Prompt button click
        document.getElementById("vsPromptBtn").addEventListener("click", function() {
            fileInput.click();
        });

        // Clicking the drop zone itself (not the button) also opens picker
        var prompt = document.getElementById("vsPrompt");
        prompt.addEventListener("click", function(e) {
            if (e.target.closest("button")) return;
            fileInput.click();
        });

        // Drag & drop
        prompt.addEventListener("dragover", function(e) {
            e.preventDefault();
            prompt.classList.add("drag-over");
        });
        prompt.addEventListener("dragleave", function() {
            prompt.classList.remove("drag-over");
        });
        prompt.addEventListener("drop", function(e) {
            e.preventDefault();
            prompt.classList.remove("drag-over");
            var files = e.dataTransfer.files;
            if (files.length > 0 && files[0].type.startsWith("video/")) {
                loadVideo(files[0]);
            }
        });

        // Change video link (in player state)
        var changeLink = document.getElementById("vsChangeVideo");
        if (changeLink) {
            changeLink.addEventListener("click", function(e) {
                e.preventDefault();
                fileInput.click();
            });
        }
    }

    return { init: init };
})();
