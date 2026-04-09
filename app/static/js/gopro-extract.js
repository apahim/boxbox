/**
 * GoPro telemetry extraction module.
 *
 * Extracts GPMF telemetry from GoPro MP4 files client-side,
 * converts to RaceChrono-compatible CSV for the existing ingest pipeline.
 *
 * Uses a lightweight MP4 parser that reads only:
 *   1. Box headers (~100 bytes each) to locate the moov atom
 *   2. The moov atom (~1-5MB) to find GPMF track sample table
 *   3. The GPMF samples from mdat (~1-5MB)
 * Total: ~10MB read from an 11GB file. No full-file read.
 *
 * gopro-telemetry (vendored) parses the extracted GPMF binary.
 */

import GoProTelemetry from "./vendor/gopro-telemetry.esm.js";

// ---- Lightweight MP4 parser ----

async function readBytes(file, offset, length) {
    var blob = file.slice(offset, offset + length);
    var buf = await blob.arrayBuffer();
    return new DataView(buf);
}

async function findMoov(file, progressCb) {
    // Scan top-level boxes to find moov and mdat
    var fileSize = file.size;
    var offset = 0;
    var moovOffset = -1, moovSize = 0;

    progressCb(5);

    while (offset < fileSize) {
        var hdr = await readBytes(file, offset, 16);
        var size = hdr.getUint32(0);
        var type = String.fromCharCode(hdr.getUint8(4), hdr.getUint8(5), hdr.getUint8(6), hdr.getUint8(7));

        // Handle 64-bit extended size
        var boxSize = size;
        if (size === 1) {
            // 64-bit size in bytes 8-15
            var hi = hdr.getUint32(8);
            var lo = hdr.getUint32(12);
            boxSize = hi * 0x100000000 + lo;
        } else if (size === 0) {
            // Box extends to end of file
            boxSize = fileSize - offset;
        }

        if (boxSize < 8) break; // invalid

        if (type === "moov") {
            moovOffset = offset;
            moovSize = boxSize;
            break;
        }

        offset += boxSize;

        // Progress: we're scanning box headers, usually just ftyp + mdat header before moov (if at end)
        progressCb(Math.min(15, 5 + Math.round((offset / fileSize) * 10)));
    }

    if (moovOffset < 0) {
        throw new Error("No moov atom found in MP4 file.");
    }

    progressCb(20);

    // Read the full moov box
    var moovBlob = file.slice(moovOffset, moovOffset + moovSize);
    var moovBuf = await moovBlob.arrayBuffer();

    progressCb(30);

    return new Uint8Array(moovBuf);
}

function readBoxHeader(data, offset) {
    if (offset + 8 > data.length) return null;
    var dv = new DataView(data.buffer, data.byteOffset + offset, Math.min(16, data.length - offset));
    var size = dv.getUint32(0);
    var type = String.fromCharCode(data[offset + 4], data[offset + 5], data[offset + 6], data[offset + 7]);
    var headerSize = 8;

    if (size === 1 && offset + 16 <= data.length) {
        var hi = dv.getUint32(8);
        var lo = dv.getUint32(12);
        size = hi * 0x100000000 + lo;
        headerSize = 16;
    } else if (size === 0) {
        size = data.length - offset;
    }

    return { size: size, type: type, headerSize: headerSize, offset: offset, dataOffset: offset + headerSize };
}

function findBox(data, offset, endOffset, type) {
    while (offset < endOffset) {
        var box = readBoxHeader(data, offset);
        if (!box || box.size < 8) break;
        if (box.type === type) return box;
        offset += box.size;
    }
    return null;
}

function parseStco(data, offset, size) {
    // version(1) + flags(3) + entry_count(4) + offsets(4 each)
    var dv = new DataView(data.buffer, data.byteOffset + offset);
    var count = dv.getUint32(4);
    var offsets = [];
    for (var i = 0; i < count; i++) {
        offsets.push(dv.getUint32(8 + i * 4));
    }
    return offsets;
}

function parseCo64(data, offset, size) {
    var dv = new DataView(data.buffer, data.byteOffset + offset);
    var count = dv.getUint32(4);
    var offsets = [];
    for (var i = 0; i < count; i++) {
        var hi = dv.getUint32(8 + i * 8);
        var lo = dv.getUint32(8 + i * 8 + 4);
        offsets.push(hi * 0x100000000 + lo);
    }
    return offsets;
}

function parseStsz(data, offset) {
    var dv = new DataView(data.buffer, data.byteOffset + offset);
    var sampleSize = dv.getUint32(4);
    var count = dv.getUint32(8);
    var sizes = [];
    if (sampleSize !== 0) {
        for (var i = 0; i < count; i++) sizes.push(sampleSize);
    } else {
        for (var j = 0; j < count; j++) {
            sizes.push(dv.getUint32(12 + j * 4));
        }
    }
    return sizes;
}

function parseStsc(data, offset) {
    var dv = new DataView(data.buffer, data.byteOffset + offset);
    var count = dv.getUint32(4);
    var entries = [];
    for (var i = 0; i < count; i++) {
        entries.push({
            firstChunk: dv.getUint32(8 + i * 12),
            samplesPerChunk: dv.getUint32(8 + i * 12 + 4),
            sampleDescIdx: dv.getUint32(8 + i * 12 + 8),
        });
    }
    return entries;
}

function parseStts(data, offset) {
    var dv = new DataView(data.buffer, data.byteOffset + offset);
    var count = dv.getUint32(4);
    var entries = [];
    for (var i = 0; i < count; i++) {
        entries.push({
            sampleCount: dv.getUint32(8 + i * 8),
            sampleDelta: dv.getUint32(8 + i * 8 + 4),
        });
    }
    return entries;
}

function parseMdhd(data, offset) {
    var dv = new DataView(data.buffer, data.byteOffset + offset);
    var version = dv.getUint8(0);
    if (version === 0) {
        var creationTime = dv.getUint32(4);
        var timescale = dv.getUint32(12);
        var duration = dv.getUint32(16);
        return { creationTime: creationTime, timescale: timescale, duration: duration };
    } else {
        var timescale1 = dv.getUint32(20);
        return { creationTime: 0, timescale: timescale1, duration: 0 };
    }
}

function boxEnd(box) {
    return box.offset + box.size;
}

function findGpmfTrack(moovData) {
    var moovBox = readBoxHeader(moovData, 0);
    if (!moovBox || moovBox.type !== "moov") return null;

    var offset = moovBox.dataOffset;
    var end = moovData.length;

    // Iterate all trak boxes
    while (offset < end) {
        var trakBox = findBox(moovData, offset, end, "trak");
        if (!trakBox) break;

        var trakE = boxEnd(trakBox);

        // Navigate: trak -> mdia -> minf -> stbl -> stsd
        var mdia = findBox(moovData, trakBox.dataOffset, trakE, "mdia");
        if (mdia) {
            var minf = findBox(moovData, mdia.dataOffset, boxEnd(mdia), "minf");
            if (minf) {
                var stbl = findBox(moovData, minf.dataOffset, boxEnd(minf), "stbl");
                if (stbl) {
                    var stsd = findBox(moovData, stbl.dataOffset, boxEnd(stbl), "stsd");
                    if (stsd) {
                        // stsd is a FullBox: version(4) + entry_count(4), then sample entries
                        var entryOffset = stsd.dataOffset + 8;
                        if (entryOffset + 8 <= moovData.length) {
                            var entryType = String.fromCharCode(
                                moovData[entryOffset + 4], moovData[entryOffset + 5],
                                moovData[entryOffset + 6], moovData[entryOffset + 7]
                            );

                            if (entryType === "gpmd") {
                                var stblE = boxEnd(stbl);

                                // Parse chunk offsets (stco or co64)
                                var chunkOffsets;
                                var stcoBox = findBox(moovData, stbl.dataOffset, stblE, "stco");
                                if (stcoBox) {
                                    chunkOffsets = parseStco(moovData, stcoBox.dataOffset);
                                } else {
                                    var co64Box = findBox(moovData, stbl.dataOffset, stblE, "co64");
                                    if (co64Box) {
                                        chunkOffsets = parseCo64(moovData, co64Box.dataOffset);
                                    }
                                }

                                var stszBox = findBox(moovData, stbl.dataOffset, stblE, "stsz");
                                var sampleSizes = stszBox ? parseStsz(moovData, stszBox.dataOffset) : [];

                                var stscBox = findBox(moovData, stbl.dataOffset, stblE, "stsc");
                                var stscEntries = stscBox ? parseStsc(moovData, stscBox.dataOffset) : [];

                                var sttsBox = findBox(moovData, stbl.dataOffset, stblE, "stts");
                                var sttsEntries = sttsBox ? parseStts(moovData, sttsBox.dataOffset) : [];

                                var mdhdBox = findBox(moovData, mdia.dataOffset, boxEnd(mdia), "mdhd");
                                var mdhd = mdhdBox ? parseMdhd(moovData, mdhdBox.dataOffset) : { timescale: 1000, creationTime: 0 };

                                return {
                                    chunkOffsets: chunkOffsets,
                                    sampleSizes: sampleSizes,
                                    stscEntries: stscEntries,
                                    sttsEntries: sttsEntries,
                                    timescale: mdhd.timescale,
                                    creationTime: mdhd.creationTime,
                                };
                            }
                        }
                    }
                }
            }
        }

        offset = trakE;
    }

    return null;
}

function buildSampleOffsets(track) {
    // Map each sample to its file offset using stsc + stco + stsz
    var chunkOffsets = track.chunkOffsets;
    var sampleSizes = track.sampleSizes;
    var stsc = track.stscEntries;

    if (!chunkOffsets || !sampleSizes || !stsc || stsc.length === 0) return [];

    var totalChunks = chunkOffsets.length;
    var samples = [];
    var sampleIdx = 0;

    for (var chunkIdx = 0; chunkIdx < totalChunks; chunkIdx++) {
        var chunkNum = chunkIdx + 1; // 1-based

        // Find applicable stsc entry
        var samplesInChunk = stsc[0].samplesPerChunk;
        for (var e = 0; e < stsc.length; e++) {
            if (stsc[e].firstChunk <= chunkNum) {
                samplesInChunk = stsc[e].samplesPerChunk;
            } else {
                break;
            }
        }

        var byteOffset = chunkOffsets[chunkIdx];
        for (var s = 0; s < samplesInChunk && sampleIdx < sampleSizes.length; s++) {
            samples.push({ offset: byteOffset, size: sampleSizes[sampleIdx] });
            byteOffset += sampleSizes[sampleIdx];
            sampleIdx++;
        }
    }

    return samples;
}

async function extractGpmfRaw(file, progressCb) {
    // 1. Find and read moov atom (reads only box headers to locate it)
    var moovData = await findMoov(file, progressCb);

    // 2. Parse moov to find GPMF track sample table
    var track = findGpmfTrack(moovData);
    if (!track) {
        throw new Error("No GoPro GPMF metadata track found in this video.");
    }

    progressCb(40);

    // 3. Build sample offset/size list
    var sampleList = buildSampleOffsets(track);
    if (sampleList.length === 0) {
        throw new Error("GPMF track has no samples.");
    }

    // 4. Read only the GPMF sample bytes from the file (typically 1-5MB total)
    var totalBytes = 0;
    for (var i = 0; i < sampleList.length; i++) totalBytes += sampleList[i].size;

    var rawData = new Uint8Array(totalBytes);
    var writeOffset = 0;
    var samplesRead = 0;

    // Batch nearby reads for efficiency
    for (var j = 0; j < sampleList.length; j++) {
        var sample = sampleList[j];
        var blob = file.slice(sample.offset, sample.offset + sample.size);
        var buf = await blob.arrayBuffer();
        rawData.set(new Uint8Array(buf), writeOffset);
        writeOffset += sample.size;
        samplesRead++;

        if (samplesRead % 50 === 0) {
            progressCb(40 + Math.round((samplesRead / sampleList.length) * 20));
        }
    }

    progressCb(60);

    // 5. Build timing info for gopro-telemetry
    var timing = { samples: [] };

    // Creation time: MP4 epoch is 1904-01-01
    var mp4Epoch = Date.UTC(1904, 0, 1, 0, 0, 0);
    if (track.creationTime > 0) {
        timing.start = new Date(mp4Epoch + track.creationTime * 1000);
    } else {
        timing.start = new Date();
    }

    // Build per-sample timing from stts
    var cts = 0;
    var sttsIdx = 0;
    var sttsRemaining = track.sttsEntries.length > 0 ? track.sttsEntries[0].sampleCount : 0;
    var sttsDelta = track.sttsEntries.length > 0 ? track.sttsEntries[0].sampleDelta : 1;

    for (var k = 0; k < sampleList.length; k++) {
        timing.samples.push({ cts: cts, duration: sttsDelta });
        cts += sttsDelta;

        sttsRemaining--;
        if (sttsRemaining <= 0 && sttsIdx + 1 < track.sttsEntries.length) {
            sttsIdx++;
            sttsRemaining = track.sttsEntries[sttsIdx].sampleCount;
            sttsDelta = track.sttsEntries[sttsIdx].sampleDelta;
        }
    }

    // Compute video duration (approximate)
    timing.videoDuration = cts / track.timescale;
    timing.frameDuration = timing.videoDuration / sampleList.length;

    return { rawData: rawData, timing: timing };
}

// ---- Main extraction ----

/**
 * Extract telemetry from a GoPro MP4 File object.
 * Reads only ~5-10MB from the file regardless of video size.
 * @param {File} file - MP4 file from file input
 * @param {function} onProgress - callback(percent) for extraction progress
 * @returns {Promise<object>} parsed telemetry data
 */
export async function extractGoPro(file, onProgress) {
    var progressCb = onProgress || function() {};

    // Extract raw GPMF data (reads only moov + GPMF samples)
    var extracted = await extractGpmfRaw(file, progressCb);

    progressCb(65);

    // Parse with gopro-telemetry
    // Hero 13 uses GPS9; older models use GPS5
    var telemetry = await GoProTelemetry(extracted, {
        stream: ["GPS5", "GPS9", "ACCL", "GYRO"],
        GPS5Fix: 2,
        GPS5Precision: 500,
    });

    progressCb(75);

    // Find the device stream that contains GPS (GPS9 or GPS5)
    var deviceKey = null;
    var gpsStreamKey = null;
    for (var key in telemetry) {
        if (telemetry[key] && telemetry[key].streams) {
            if (telemetry[key].streams.GPS9) {
                deviceKey = key;
                gpsStreamKey = "GPS9";
                break;
            }
            if (telemetry[key].streams.GPS5) {
                deviceKey = key;
                gpsStreamKey = "GPS5";
                break;
            }
        }
    }
    if (!deviceKey) {
        throw new Error("No GPS data found in video. Ensure GPS was enabled on the GoPro.");
    }

    var streams = telemetry[deviceKey].streams;
    var gps = streams[gpsStreamKey].samples;
    var accl = streams.ACCL ? streams.ACCL.samples : [];
    var gyro = streams.GYRO ? streams.GYRO.samples : [];

    if (gps.length === 0) {
        throw new Error("No GPS samples found. The GPS may not have had a fix during recording.");
    }

    // For GPS9, filter out samples with no fix (fix type at index 8, 0 = no fix)
    if (gpsStreamKey === "GPS9") {
        gps = gps.filter(function(g) {
            return !g.value[8] || g.value[8] >= 2;
        });
        if (gps.length === 0) {
            throw new Error("No GPS samples with valid fix. The GPS may not have had a lock during recording.");
        }
    }

    // Build unified telemetry array at GPS sample rate
    var firstTs = gps[0].date ? gps[0].date.getTime() / 1000 : 0;
    var rows = [];
    var cumDist = 0;
    var acclIdx = 0;
    var gyroIdx = 0;
    var G = 9.80665; // m/s² per G — convert raw ACCL to G-forces for pipeline compatibility

    for (var i = 0; i < gps.length; i++) {
        var g = gps[i];
        var ts = g.date ? g.date.getTime() / 1000 : g.cts / 1000;
        var elapsed = ts - firstTs;
        var lat = g.value[0];
        var lon = g.value[1];
        var alt = g.value[2];
        var speed2d = g.value[3]; // m/s

        // Bearing from consecutive GPS points
        var bearing = 0;
        if (i > 0) {
            var prevLat = gps[i - 1].value[0];
            var prevLon = gps[i - 1].value[1];
            var dLat = lat - prevLat;
            var dLon = (lon - prevLon) * Math.cos(lat * Math.PI / 180);
            bearing = Math.atan2(dLon, dLat) * 180 / Math.PI;
            if (bearing < 0) bearing += 360;
        }

        // Cumulative haversine distance
        if (i > 0) {
            cumDist += haversine(gps[i - 1].value[0], gps[i - 1].value[1], lat, lon);
        }

        // Find nearest ACCL sample
        var ax = 0, ay = 0, az = 0;
        if (accl.length > 0) {
            acclIdx = findNearest(accl, acclIdx, ts);
            var a = accl[acclIdx];
            ax = a.value[1] / G;
            ay = a.value[2] / G;
            az = a.value[0] / G;
        }

        // Find nearest GYRO sample
        var gx = 0, gy = 0, gz = 0;
        if (gyro.length > 0) {
            gyroIdx = findNearest(gyro, gyroIdx, ts);
            var gr = gyro[gyroIdx];
            gx = gr.value[0];
            gy = gr.value[1];
            gz = gr.value[2];
        }

        rows.push({
            timestamp: ts,
            elapsed_time: elapsed,
            latitude: lat,
            longitude: lon,
            altitude: alt,
            speed_gps: speed2d,
            bearing: bearing,
            distance_traveled: cumDist,
            x_acc: ax,
            y_acc: ay,
            z_acc: az,
            lateral_acc: 0,
            longitudinal_acc: 0,
            x_rotation: gx,
            y_rotation: gy,
            z_rotation: gz,
            lap_number: 1,
        });
    }

    computeGpsAcceleration(rows);

    progressCb(90);

    return { rows: rows, fileName: file.name };
}

/**
 * Detect laps from GPS data using start/finish gate crossing.
 */
export function detectLaps(telemetry, sfGate) {
    var rows = telemetry.rows;
    if (!sfGate || rows.length < 2) return telemetry;

    var gateLat1 = sfGate.sf_lat1, gateLon1 = sfGate.sf_lon1;
    var gateLat2 = sfGate.sf_lat2, gateLon2 = sfGate.sf_lon2;

    // Detect crossings with interpolation parameter t
    var crossings = [];
    for (var i = 1; i < rows.length; i++) {
        var t = segmentsIntersect(
            rows[i - 1].latitude, rows[i - 1].longitude,
            rows[i].latitude, rows[i].longitude,
            gateLat1, gateLon1, gateLat2, gateLon2
        );
        if (t !== false) {
            var dx = rows[i].latitude - rows[i - 1].latitude;
            var dy = rows[i].longitude - rows[i - 1].longitude;
            var gateX = gateLat2 - gateLat1;
            var gateY = gateLon2 - gateLon1;
            var cross = dx * gateY - dy * gateX;
            if (cross > 0) {
                var crossTime = rows[i - 1].elapsed_time + t * (rows[i].elapsed_time - rows[i - 1].elapsed_time);
                crossings.push({ idx: i, time: crossTime, t: t });
            }
        }
    }

    // Fallback: accept both directions if fewer than 2 same-direction crossings
    if (crossings.length < 2) {
        crossings = [];
        for (var j = 1; j < rows.length; j++) {
            var t2 = segmentsIntersect(
                rows[j - 1].latitude, rows[j - 1].longitude,
                rows[j].latitude, rows[j].longitude,
                gateLat1, gateLon1, gateLat2, gateLon2
            );
            if (t2 !== false) {
                var crossTime2 = rows[j - 1].elapsed_time + t2 * (rows[j].elapsed_time - rows[j - 1].elapsed_time);
                crossings.push({ idx: j, time: crossTime2, t: t2 });
            }
        }
    }

    if (crossings.length < 2) return telemetry;

    // Debounce: filter crossings closer than 10 seconds
    var filtered = [crossings[0]];
    for (var k = 1; k < crossings.length; k++) {
        if (crossings[k].time - filtered[filtered.length - 1].time > 10) {
            filtered.push(crossings[k]);
        }
    }
    crossings = filtered;

    if (crossings.length < 2) return telemetry;

    // Assign lap numbers
    var lapNum = 0;
    var crossIdx = 0;
    for (var m = 0; m < rows.length; m++) {
        if (crossIdx < crossings.length && m >= crossings[crossIdx].idx) {
            lapNum++;
            crossIdx++;
        }
        rows[m].lap_number = lapNum;
    }

    // Insert synthetic boundary samples at each crossing (reverse order to preserve indices).
    // Each synthetic sample ends the previous lap at the interpolated crossing time.
    // The crossing sample's elapsed_time is adjusted to start the new lap at crossing time.
    for (var c = crossings.length - 1; c >= 0; c--) {
        var ci = crossings[c].idx;
        var ct = crossings[c].time;
        var tParam = crossings[c].t;
        var prev = rows[ci - 1];
        var cur = rows[ci];

        // Synthetic sample: interpolated position/speed, belongs to the ending lap
        var synthetic = {};
        for (var key in cur) synthetic[key] = cur[key];
        synthetic.elapsed_time = ct;
        synthetic.timestamp = prev.timestamp + tParam * (cur.timestamp - prev.timestamp);
        synthetic.lap_number = cur.lap_number - 1;
        synthetic.latitude = prev.latitude + tParam * (cur.latitude - prev.latitude);
        synthetic.longitude = prev.longitude + tParam * (cur.longitude - prev.longitude);
        synthetic.altitude = prev.altitude + tParam * (cur.altitude - prev.altitude);
        synthetic.speed_gps = prev.speed_gps + tParam * (cur.speed_gps - prev.speed_gps);
        synthetic.bearing = cur.bearing;
        synthetic.distance_traveled = prev.distance_traveled + tParam * (cur.distance_traveled - prev.distance_traveled);

        rows.splice(ci, 0, synthetic);
        // Crossing sample is now at ci+1; set its elapsed_time to the crossing time
        rows[ci + 1].elapsed_time = ct;
    }

    telemetry.crossingCount = crossings.length;
    telemetry.lapCount = crossings.length - 1;
    return telemetry;
}

/**
 * Generate a summary of the extracted telemetry.
 */
export function telemetrySummary(telemetry) {
    var rows = telemetry.rows;
    if (!rows || rows.length === 0) return null;

    var duration = rows[rows.length - 1].elapsed_time;
    var maxSpeed = 0;
    for (var i = 0; i < rows.length; i++) {
        if (rows[i].speed_gps > maxSpeed) maxSpeed = rows[i].speed_gps;
    }

    var lapTimes = [];
    if (telemetry.lapCount && telemetry.lapCount > 0) {
        var lapGroups = {};
        for (var k = 0; k < rows.length; k++) {
            var ln = rows[k].lap_number;
            if (!lapGroups[ln]) lapGroups[ln] = { min: rows[k].elapsed_time, max: rows[k].elapsed_time };
            if (rows[k].elapsed_time < lapGroups[ln].min) lapGroups[ln].min = rows[k].elapsed_time;
            if (rows[k].elapsed_time > lapGroups[ln].max) lapGroups[ln].max = rows[k].elapsed_time;
        }
        for (var lap in lapGroups) {
            if (parseInt(lap) >= 1 && parseInt(lap) <= telemetry.lapCount) {
                lapTimes.push(lapGroups[lap].max - lapGroups[lap].min);
            }
        }
    }

    var bestLap = lapTimes.length > 0 ? Math.min.apply(null, lapTimes) : null;

    return {
        sampleCount: rows.length,
        durationSeconds: duration,
        durationFormatted: formatDuration(duration),
        maxSpeedKmh: Math.round(maxSpeed * 3.6 * 10) / 10,
        lapCount: telemetry.lapCount || 0,
        bestLapTime: bestLap,
        bestLapFormatted: bestLap ? formatLapTime(bestLap) : null,
    };
}

/**
 * Convert telemetry to RaceChrono v3 CSV format.
 */
export function telemetryToCSV(telemetry) {
    var columns = [
        "timestamp", "elapsed_time", "lap_number",
        "latitude", "longitude", "altitude",
        "speed", "bearing", "distance_traveled",
        "x_acc", "y_acc", "z_acc",
        "lateral_acc", "longitudinal_acc",
        "x_rotation", "y_rotation", "z_rotation",
    ];

    var header = columns.join(",");
    var units = "s,s,,deg,deg,m,m/s,deg,m,G,G,G,G,G,rad/s,rad/s,rad/s";
    var source = columns.map(function() { return "gopro"; }).join(",");

    var lines = [header, units, source];

    var rows = telemetry.rows;
    for (var i = 0; i < rows.length; i++) {
        var r = rows[i];
        lines.push([
            r.timestamp.toFixed(3),
            r.elapsed_time.toFixed(4),
            r.lap_number,
            r.latitude.toFixed(7),
            r.longitude.toFixed(7),
            r.altitude.toFixed(2),
            r.speed_gps.toFixed(4),
            r.bearing.toFixed(2),
            r.distance_traveled.toFixed(3),
            r.x_acc.toFixed(4),
            r.y_acc.toFixed(4),
            r.z_acc.toFixed(4),
            r.lateral_acc.toFixed(4),
            r.longitudinal_acc.toFixed(4),
            r.x_rotation.toFixed(4),
            r.y_rotation.toFixed(4),
            r.z_rotation.toFixed(4),
        ].join(","));
    }

    return new Blob([lines.join("\n")], { type: "text/csv" });
}


// ---- GPS acceleration ----

/**
 * Compute GPS-derived lateral and longitudinal acceleration for a rows array.
 * Matches RaceChrono Pro's "calc" approach: derive acceleration from GPS speed
 * and bearing changes rather than using noisy raw IMU data.
 */
function computeGpsAcceleration(rows) {
    var G = 9.80665;
    var speeds = rows.map(function(r) { return r.speed_gps; });
    var bearings = rows.map(function(r) { return r.bearing * Math.PI / 180; });
    var times = rows.map(function(r) { return r.elapsed_time; });

    var speedSmooth = movingAverage(speeds, 7);
    var bearingUnwrapped = unwrapRadians(bearings);
    var bearingSmooth = movingAverage(bearingUnwrapped, 7);

    var longAcc = new Array(rows.length);
    var latAcc = new Array(rows.length);
    longAcc[0] = 0;
    latAcc[0] = 0;
    for (var k = 1; k < rows.length; k++) {
        var dt = times[k] - times[k - 1];
        if (dt <= 0) dt = 0.1;
        longAcc[k] = (speedSmooth[k] - speedSmooth[k - 1]) / dt / G;
        latAcc[k] = -speedSmooth[k] * (bearingSmooth[k] - bearingSmooth[k - 1]) / dt / G;
    }

    longAcc = movingAverage(longAcc, 5);
    latAcc = movingAverage(latAcc, 5);

    for (var m = 0; m < rows.length; m++) {
        rows[m].longitudinal_acc = longAcc[m];
        rows[m].lateral_acc = latAcc[m];
    }
}

// ---- Multi-file concatenation ----

/**
 * Concatenate multiple extractGoPro() results into a single telemetry object.
 * Adjusts elapsed_time and distance_traveled for continuity across files.
 * @param {Array} results - Array of { rows, fileName } from extractGoPro()
 * @returns {object} Merged telemetry: { rows, fileName, fileCount }
 */
export function concatenateGoPro(results) {
    if (!results || results.length === 0) {
        throw new Error("No telemetry data to concatenate.");
    }
    if (results.length === 1) {
        results[0].fileCount = 1;
        return results[0];
    }

    // Sort by first GPS timestamp
    results.sort(function(a, b) {
        return a.rows[0].timestamp - b.rows[0].timestamp;
    });

    // Validate: check for duplicate files (same first timestamp within 1 second)
    for (var d = 1; d < results.length; d++) {
        if (Math.abs(results[d].rows[0].timestamp - results[d - 1].rows[0].timestamp) < 1) {
            throw new Error("Duplicate file detected: " + results[d].fileName +
                " has the same start time as " + results[d - 1].fileName + ".");
        }
    }

    // Validate: warn if gap between consecutive files > 60 seconds
    var warnings = [];
    for (var w = 1; w < results.length; w++) {
        var prevLast = results[w - 1].rows[results[w - 1].rows.length - 1];
        var curFirst = results[w].rows[0];
        var gap = curFirst.timestamp - prevLast.timestamp;
        if (gap > 60) {
            warnings.push("Large gap (" + Math.round(gap) + "s) between " +
                results[w - 1].fileName + " and " + results[w].fileName +
                ". These may be from different sessions.");
        }
    }

    // Concatenate with offset adjustments
    var mergedRows = results[0].rows.slice();
    for (var i = 1; i < results.length; i++) {
        var prevRows = results[i - 1].rows;
        var prevLastRow = prevRows[prevRows.length - 1];
        var curRows = results[i].rows;
        var curFirstRow = curRows[0];

        // Elapsed time offset: previous file's last elapsed_time + inter-file gap
        var timeGap = curFirstRow.timestamp - prevLastRow.timestamp;
        if (timeGap < 0) timeGap = 0;
        var elapsedOffset = prevLastRow.elapsed_time + timeGap;

        // Distance offset: previous file's last distance + gap distance
        var gapDist = haversine(
            prevLastRow.latitude, prevLastRow.longitude,
            curFirstRow.latitude, curFirstRow.longitude
        );
        var distanceOffset = prevLastRow.distance_traveled + gapDist;

        for (var j = 0; j < curRows.length; j++) {
            var row = {};
            for (var key in curRows[j]) row[key] = curRows[j][key];
            row.elapsed_time += elapsedOffset;
            row.distance_traveled += distanceOffset;
            mergedRows.push(row);
        }
    }

    // Recompute GPS-derived acceleration across the full merged dataset
    // to avoid smoothing discontinuities at file boundaries
    computeGpsAcceleration(mergedRows);

    var result = { rows: mergedRows, fileName: results[0].fileName, fileCount: results.length };
    if (warnings.length > 0) result.warnings = warnings;
    return result;
}

// ---- Signal processing helpers ----

function movingAverage(arr, window) {
    var half = Math.floor(window / 2);
    var out = new Array(arr.length);
    for (var i = 0; i < arr.length; i++) {
        var sum = 0;
        var count = 0;
        for (var j = Math.max(0, i - half); j <= Math.min(arr.length - 1, i + half); j++) {
            sum += arr[j];
            count++;
        }
        out[i] = sum / count;
    }
    return out;
}

function unwrapRadians(arr) {
    var out = new Array(arr.length);
    out[0] = arr[0];
    for (var i = 1; i < arr.length; i++) {
        var d = arr[i] - arr[i - 1];
        // Wrap delta to [-π, π]
        d = d - Math.round(d / (2 * Math.PI)) * 2 * Math.PI;
        out[i] = out[i - 1] + d;
    }
    return out;
}

// ---- Helpers ----

function haversine(lat1, lon1, lat2, lon2) {
    var R = 6371000;
    var dLat = (lat2 - lat1) * Math.PI / 180;
    var dLon = (lon2 - lon1) * Math.PI / 180;
    var a = Math.sin(dLat / 2) * Math.sin(dLat / 2) +
            Math.cos(lat1 * Math.PI / 180) * Math.cos(lat2 * Math.PI / 180) *
            Math.sin(dLon / 2) * Math.sin(dLon / 2);
    return R * 2 * Math.atan2(Math.sqrt(a), Math.sqrt(1 - a));
}

function findNearest(samples, startIdx, targetTs) {
    var idx = startIdx;
    while (idx < samples.length - 1) {
        var curTs = samples[idx].date ? samples[idx].date.getTime() / 1000 : samples[idx].cts / 1000;
        var nextTs = samples[idx + 1].date ? samples[idx + 1].date.getTime() / 1000 : samples[idx + 1].cts / 1000;
        if (Math.abs(nextTs - targetTs) < Math.abs(curTs - targetTs)) {
            idx++;
        } else {
            break;
        }
    }
    return idx;
}

function segmentsIntersect(ax1, ay1, ax2, ay2, bx1, by1, bx2, by2) {
    var d1x = ax2 - ax1, d1y = ay2 - ay1;
    var d2x = bx2 - bx1, d2y = by2 - by1;
    var cross = d1x * d2y - d1y * d2x;
    if (Math.abs(cross) < 1e-12) return false;

    var dx = bx1 - ax1, dy = by1 - ay1;
    var t = (dx * d2y - dy * d2x) / cross;
    var u = (dx * d1y - dy * d1x) / cross;
    if (t >= 0 && t <= 1 && u >= 0 && u <= 1) return t;
    return false;
}

function formatDuration(seconds) {
    var m = Math.floor(seconds / 60);
    var s = Math.floor(seconds % 60);
    return m + "m " + s + "s";
}

function formatLapTime(seconds) {
    var m = Math.floor(seconds / 60);
    var s = (seconds % 60).toFixed(3);
    if (m > 0) return m + ":" + (s < 10 ? "0" : "") + s;
    return s + "s";
}
