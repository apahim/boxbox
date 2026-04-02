"""Ingest pipeline: parse CSV → run analysis → store in database.

Mirrors scripts/generate_dashboard.py but writes to the database instead of
generating HTML files. All existing analysis modules are called exactly as
they are in the static pipeline.
"""

import gzip
import os
import traceback

import numpy as np

from app import db
from app.models import (
    Lap, Telemetry, CornerRecord, CornerSummary,
    SectorTime, ChartData, SessionUpload,
)

from scripts.load_data import load_racechrono_session, extract_laptimes_from_telemetry
from scripts.analysis.outliers import filter_non_race_laps, detect_outliers
from scripts.analysis.summary import generate_summary
from scripts.analysis.weather import fetch_weather
from scripts.analysis.utils import format_laptime, fig_to_json
from scripts.analysis.laptimes import create_laptime_bar_chart, create_delta_to_best_chart
from scripts.analysis.track_map import (
    create_speed_track_map, create_all_laps_speed_map,
    create_all_laps_sector_delta_map,
)
from scripts.analysis.speed import (
    create_cumulative_time_delta, create_throttle_brake_phases,
    create_all_laps_cumulative_delta, create_all_laps_throttle_brake,
)
from scripts.analysis.braking import (
    create_braking_consistency_chart, create_all_laps_braking_map,
)
from scripts.analysis.sectors import create_sector_times_table
from scripts.analysis.coaching import generate_coaching_summary
from scripts.analysis.corner_model import (
    build_corner_analysis, build_corner_map_data, corner_analysis_to_template,
)


def ingest_session(csv_path, session, track_coords, track_corners):
    """Run full ingest pipeline for a CSV file and populate the database.

    Args:
        csv_path: Path to the RaceChrono CSV file.
        session: Session model instance (already has metadata set, added to db session).
        track_coords: Tuple of (lat, lon, timezone) for the track.
        track_corners: List of corner dicts [{"name", "lat", "lon"}, ...] or None.

    Returns:
        The session object with all computed fields populated.
    """
    # 1. Parse CSV
    telemetry_df = load_racechrono_session(csv_path)
    print(f"  Loaded telemetry: {len(telemetry_df)} rows")

    # 2. Extract lap times
    laptimes_df = extract_laptimes_from_telemetry(telemetry_df)
    laptimes_df = filter_non_race_laps(laptimes_df)
    print(f"  Extracted {len(laptimes_df)} race laps")

    # 3. Generate summary
    summary = generate_summary(laptimes_df, telemetry_df)

    # Store summary stats on session
    session.total_laps = summary.get("total_laps")
    session.clean_laps = summary.get("clean_laps")
    session.best_lap_time = summary["best_lap"]["time"] if summary.get("best_lap") else None
    session.average_time = summary.get("average")
    session.median_time = summary.get("median")
    session.std_dev = summary.get("std_dev")
    session.consistency_pct = summary.get("consistency_pct")
    session.top_speed_kmh = summary.get("top_speed_kmh")
    session.max_lateral_g = summary.get("max_lateral_g")
    session.max_braking_g = summary.get("max_braking_g")
    session.max_accel_g = summary.get("max_acceleration_g")

    # 4. Fetch weather
    if track_coords and session.date and session.session_start:
        lat, lon, tz = track_coords
        try:
            weather = fetch_weather(
                str(session.date), str(session.session_start), lat, lon, tz
            )
            if weather:
                session.weather = weather
                summary["weather"] = weather
                print(f"  Weather: {weather['condition']}, {weather['temp_c']}C")
        except Exception as e:
            print(f"  Warning: weather fetch failed: {e}")

    # 5. Store laps with outlier detection
    clean_df, excluded = detect_outliers(laptimes_df)
    excluded_laps = {e["lap"] for e in excluded}

    for _, row in laptimes_df.iterrows():
        lap_num = int(row["lap"])
        is_outlier = lap_num in excluded_laps
        reason = None
        if is_outlier:
            for e in excluded:
                if e["lap"] == lap_num:
                    reason = e.get("reason", "IQR outlier")
                    break
        lap = Lap(
            session_id=session.id,
            lap_number=lap_num,
            seconds=float(row["seconds"]),
            is_outlier=is_outlier,
            outlier_reason=reason,
        )
        db.session.add(lap)

    # 6. Bulk-insert telemetry
    _insert_telemetry(session.id, telemetry_df)

    # Find best lap
    best_lap = summary["best_lap"]["lap"] if summary.get("best_lap") else None
    weather_data = summary.get("weather")

    # 7. Corner analysis
    corner_analysis_raw = None
    try:
        corner_analysis_raw = build_corner_analysis(
            telemetry_df, laptimes_df, track_corners=track_corners
        )
        if corner_analysis_raw:
            _store_corner_analysis(session.id, corner_analysis_raw)
            print(f"  Corner analysis: {len(corner_analysis_raw.get('summaries', []))} corners")
    except Exception as e:
        print(f"  Warning: corner analysis failed: {e}")

    # 8. Sector analysis
    sector_data = None
    try:
        sector_data = create_sector_times_table(
            telemetry_df, laptimes_df, metadata={}, track_corners=track_corners
        )
        if sector_data:
            _store_sector_times(session.id, sector_data)
            print(f"  Sectors stored")
    except Exception as e:
        print(f"  Warning: sector analysis failed: {e}")

    # 9. Precompute all chart data
    _precompute_charts(
        session.id, telemetry_df, laptimes_df, clean_df,
        best_lap, weather_data, track_corners, sector_data,
        corner_analysis_raw,
    )

    # 10. Coaching
    try:
        coaching = generate_coaching_summary(
            telemetry_df, laptimes_df,
            sector_data=sector_data,
            track_corners=track_corners,
            corner_analysis=corner_analysis_raw,
        )
        if coaching:
            session.coaching = coaching
    except Exception as e:
        print(f"  Warning: coaching failed: {e}")

    # 11. Store compressed CSV
    try:
        with open(csv_path, 'rb') as f:
            raw_csv = f.read()
        upload = SessionUpload(
            session_id=session.id,
            original_filename=os.path.basename(csv_path),
            csv_compressed=gzip.compress(raw_csv),
        )
        db.session.add(upload)
    except Exception as e:
        print(f"  Warning: CSV backup failed: {e}")

    db.session.commit()
    print(f"  Ingest complete: {session.total_laps} laps, {session.clean_laps} clean, best {session.best_lap_time}")
    return session


def _insert_telemetry(session_id, telemetry_df):
    """Bulk-insert telemetry rows from DataFrame."""
    # Map DataFrame columns to model columns
    col_map = {
        'lap_number': 'lap_number',
        'timestamp': 'timestamp',
        'elapsed_time': 'elapsed_time',
        'distance_traveled': 'distance_traveled',
        'altitude': 'altitude',
        'bearing': 'bearing',
    }

    # GPS columns (may have suffixes)
    lat_col = lon_col = speed_gps_col = speed_calc_col = None
    lat_acc_col = lon_acc_col = None
    for col in telemetry_df.columns:
        cl = col.lower()
        if 'latitude' in cl:
            lat_col = col
        elif 'longitude' in cl:
            lon_col = col
        elif cl in ('speed_gps', 'speed'):
            speed_gps_col = col
        elif cl == 'speed_calc':
            speed_calc_col = col
        elif cl in ('lateral_acceleration', 'lateral_acc'):
            lat_acc_col = col
        elif cl in ('longitudinal_acceleration', 'longitudinal_acc'):
            lon_acc_col = col

    records = []
    for i, (_, row) in enumerate(telemetry_df.iterrows()):
        rec = {
            'session_id': session_id,
            'sample_index': i,
        }
        # Standard columns
        for df_col, model_col in col_map.items():
            if df_col in telemetry_df.columns:
                val = row[df_col]
                rec[model_col] = None if _is_nan(val) else float(val) if model_col != 'lap_number' else int(val)

        # GPS
        if lat_col:
            val = row[lat_col]
            rec['latitude'] = None if _is_nan(val) else float(val)
        if lon_col:
            val = row[lon_col]
            rec['longitude'] = None if _is_nan(val) else float(val)

        # Speed
        if speed_gps_col:
            val = row[speed_gps_col]
            rec['speed_gps'] = None if _is_nan(val) else float(val)
        if speed_calc_col:
            val = row[speed_calc_col]
            rec['speed_calc'] = None if _is_nan(val) else float(val)

        # Accelerations
        if lat_acc_col:
            val = row[lat_acc_col]
            rec['lateral_acc'] = None if _is_nan(val) else float(val)
        if lon_acc_col:
            val = row[lon_acc_col]
            rec['longitudinal_acc'] = None if _is_nan(val) else float(val)

        # Additional acc/rotation columns
        for df_col, model_col in [
            ('x_acc', 'x_acc'), ('y_acc', 'y_acc'), ('z_acc', 'z_acc'),
            ('x_rotation', 'x_rotation'), ('y_rotation', 'y_rotation'),
            ('z_rotation', 'z_rotation'), ('lean_angle', 'lean_angle'),
        ]:
            if df_col in telemetry_df.columns:
                val = row[df_col]
                rec[model_col] = None if _is_nan(val) else float(val)

        records.append(rec)

    # Bulk insert in batches to manage memory
    batch_size = 5000
    for start in range(0, len(records), batch_size):
        db.session.bulk_insert_mappings(Telemetry, records[start:start + batch_size])
    db.session.flush()
    print(f"  Telemetry: {len(records)} rows inserted")


def _is_nan(val):
    """Check if a value is NaN (works for float and numpy types)."""
    try:
        return val is None or (isinstance(val, float) and val != val) or (hasattr(val, 'item') and np.isnan(val))
    except (TypeError, ValueError):
        return False


def _to_native(val):
    """Convert numpy types to Python native types for SQLAlchemy/PostgreSQL."""
    if val is None:
        return None
    if isinstance(val, (np.integer,)):
        return int(val)
    if isinstance(val, (np.floating,)):
        return float(val)
    if isinstance(val, np.bool_):
        return bool(val)
    if isinstance(val, str):
        return val
    return val


def _store_corner_analysis(session_id, corner_analysis):
    """Store corner records and summaries from build_corner_analysis() output."""
    records = corner_analysis.get("records", {})
    for lap_num, lap_records in records.items():
        for rec in lap_records:
            cr = CornerRecord(
                session_id=session_id,
                corner_name=rec.corner_name,
                corner_index=_to_native(rec.corner_index),
                lap_number=_to_native(rec.lap),
                lat=_to_native(rec.lat),
                lon=_to_native(rec.lon),
                distance=_to_native(rec.distance),
                corner_frac=_to_native(rec.corner_frac),
                entry_speed=_to_native(rec.entry_speed),
                min_speed=_to_native(rec.min_speed),
                exit_speed=_to_native(rec.exit_speed),
                time_loss=_to_native(rec.time_loss),
                braking_point=_to_native(rec.braking_point),
                braking_distance=_to_native(rec.braking_distance),
                trail_braking_depth=_to_native(rec.trail_braking_depth),
                root_cause=rec.root_cause,
            )
            db.session.add(cr)

    summaries = corner_analysis.get("summaries", [])
    for s in summaries:
        cs = CornerSummary(
            session_id=session_id,
            corner_name=s.corner_name,
            corner_index=_to_native(s.corner_index),
            lat=_to_native(s.lat),
            lon=_to_native(s.lon),
            distance=_to_native(s.distance),
            archetype=s.archetype,
            avg_time_loss=_to_native(s.avg_time_loss),
            total_time_loss=_to_native(s.total_time_loss),
            best_min_speed=_to_native(s.best_min_speed),
            avg_min_speed=_to_native(s.avg_min_speed),
            std_min_speed=_to_native(s.std_min_speed),
            best_entry_speed=_to_native(s.best_entry_speed),
            best_exit_speed=_to_native(s.best_exit_speed),
            braking_spread=_to_native(s.braking_spread),
            dominant_root_cause=s.dominant_root_cause,
        )
        db.session.add(cs)

    db.session.flush()


def _store_sector_times(session_id, sector_data):
    """Store sector times from create_sector_times_table() output."""
    sector_times = sector_data.get("sector_times", {})
    headers = sector_data.get("headers", [])
    sector_names = headers

    for lap_num, times in sector_times.items():
        for i, seconds in enumerate(times):
            st = SectorTime(
                session_id=session_id,
                lap_number=int(lap_num),
                sector_index=i,
                sector_name=sector_names[i] if i < len(sector_names) else f"S{i+1}",
                seconds=_to_native(seconds),
            )
            db.session.add(st)

    db.session.flush()


def _store_chart(session_id, chart_type, chart_key, data):
    """Store a single chart data entry if data is not None."""
    if data is None:
        return
    cd = ChartData(
        session_id=session_id,
        chart_type=chart_type,
        chart_key=chart_key,
        data=data,
    )
    db.session.add(cd)


def _precompute_charts(session_id, telemetry_df, laptimes_df, clean_df,
                       best_lap, weather, track_corners, sector_data,
                       corner_analysis_raw):
    """Precompute all chart data and store in chart_data table."""
    clean_laps = sorted(clean_df["lap"].astype(int).tolist())

    # Overview charts (Plotly figures → JSON)
    _store_chart_from_fig(session_id, "laptime_bar", "overview",
                          create_laptime_bar_chart, laptimes_df)
    _store_chart_from_fig(session_id, "delta_to_best", "overview",
                          create_delta_to_best_chart, laptimes_df)
    _store_chart_from_fig(session_id, "braking_consistency", "overview",
                          create_braking_consistency_chart, telemetry_df, laptimes_df,
                          track_corners=track_corners)

    # Per-lap charts
    # Speed maps
    try:
        speed_maps = create_all_laps_speed_map(
            telemetry_df, clean_laps, weather=weather, track_corners=track_corners
        )
        for lap, data in speed_maps.items():
            _store_chart(session_id, "speed_map", str(lap), data)
    except Exception as e:
        print(f"  Warning: speed maps failed: {e}")

    # Braking maps
    try:
        braking_maps = create_all_laps_braking_map(
            telemetry_df, clean_laps, weather=weather, track_corners=track_corners
        )
        for lap, data in braking_maps.items():
            _store_chart(session_id, "braking_map", str(lap), data)
    except Exception as e:
        print(f"  Warning: braking maps failed: {e}")

    # Sector delta maps
    if sector_data:
        try:
            sector_maps = create_all_laps_sector_delta_map(
                telemetry_df, clean_laps, sector_data,
                weather=weather, track_corners=track_corners
            )
            for lap, data in sector_maps.items():
                _store_chart(session_id, "sector_map", str(lap), data)
        except Exception as e:
            print(f"  Warning: sector maps failed: {e}")

    # Cumulative delta charts (Plotly → JSON)
    try:
        cum_delta = create_all_laps_cumulative_delta(
            telemetry_df, laptimes_df, clean_laps, track_corners=track_corners
        )
        for lap, fig_json in cum_delta.items():
            _store_chart(session_id, "cumulative_delta", str(lap), fig_json)
    except Exception as e:
        print(f"  Warning: cumulative delta failed: {e}")

    # Throttle/brake charts (Plotly → JSON)
    try:
        tb = create_all_laps_throttle_brake(telemetry_df, laptimes_df, clean_laps)
        for lap, fig_json in tb.items():
            _store_chart(session_id, "throttle_brake", str(lap), fig_json)
    except Exception as e:
        print(f"  Warning: throttle/brake failed: {e}")

    # Corner map data
    if corner_analysis_raw:
        try:
            corner_map = build_corner_map_data(telemetry_df, corner_analysis_raw)
            if corner_map:
                _store_chart(session_id, "corner_map", "overview", corner_map)
            # Also store template-formatted corner analysis
            corner_template = corner_analysis_to_template(corner_analysis_raw, laptimes_df=laptimes_df)
            if corner_template:
                _store_chart(session_id, "corner_analysis", "overview", corner_template)
        except Exception as e:
            print(f"  Warning: corner map/template failed: {e}")

    # Raceline data (single-session, computed from in-memory DataFrame)
    try:
        raceline = _build_raceline_data(telemetry_df, laptimes_df, clean_df)
        if raceline:
            _store_chart(session_id, "raceline", "overview", raceline)
    except Exception as e:
        print(f"  Warning: raceline data failed: {e}")

    # Sector data for the sectors tab
    if sector_data:
        _store_chart(session_id, "sector_table", "overview", _sector_data_to_json(sector_data))

    # Lap list for the dashboard
    lap_list = []
    for _, row in clean_df.sort_values("lap").iterrows():
        lap_num = int(row["lap"])
        lap_list.append({
            "lap": lap_num,
            "time_fmt": format_laptime(row["seconds"]),
            "seconds": round(float(row["seconds"]), 3),
            "is_best": lap_num == best_lap,
        })
    _store_chart(session_id, "lap_list", "overview", lap_list)

    db.session.flush()
    print(f"  Charts precomputed for {len(clean_laps)} clean laps")


def _store_chart_from_fig(session_id, chart_type, chart_key, func, *args, **kwargs):
    """Call a chart function, convert figure to JSON, store in chart_data."""
    try:
        fig = func(*args, **kwargs)
        json_data = fig_to_json(fig)
        _store_chart(session_id, chart_type, chart_key, json_data)
    except Exception as e:
        print(f"  Warning: {chart_type} failed: {e}")


def _build_raceline_data(telemetry_df, laptimes_df, clean_df):
    """Build raceline data from in-memory telemetry (no filesystem access)."""
    lat_col = lon_col = None
    for col in telemetry_df.columns:
        cl = col.lower()
        if 'latitude' in cl:
            lat_col = col
        elif 'longitude' in cl:
            lon_col = col

    if not lat_col or not lon_col:
        return None

    best_idx = clean_df["seconds"].idxmin() if not clean_df.empty else None
    best_lap_num = int(clean_df.loc[best_idx, "lap"]) if best_idx is not None else None
    clean_indices = set(clean_df.index)

    laps = []
    for _, row in laptimes_df.iterrows():
        lap_num = int(row["lap"])
        lap_data = telemetry_df[telemetry_df["lap_number"] == lap_num].copy()
        lap_data = lap_data.dropna(subset=[lat_col, lon_col])
        if len(lap_data) < 20:
            continue

        lat_vals = lap_data[lat_col].values
        lon_vals = lap_data[lon_col].values

        t_vals = None
        if "elapsed_time" in lap_data.columns:
            t_vals = lap_data["elapsed_time"].values.copy()
            t_vals = t_vals - t_vals[0]

        # Downsample to ~200 points
        if len(lat_vals) > 200:
            indices = np.linspace(0, len(lat_vals) - 1, 200, dtype=int)
            lat_vals = lat_vals[indices]
            lon_vals = lon_vals[indices]
            if t_vals is not None:
                t_vals = t_vals[indices]

        seconds = float(row["seconds"])
        laps.append({
            "lap": lap_num,
            "time_fmt": format_laptime(seconds),
            "seconds": round(seconds, 3),
            "is_best": lap_num == best_lap_num,
            "is_outlier": row.name not in clean_indices,
            "lat": [round(float(v), 6) for v in lat_vals],
            "lon": [round(float(v), 6) for v in lon_vals],
            "t": [round(float(v), 3) for v in t_vals] if t_vals is not None else None,
        })

    if not laps:
        return None

    return {"laps": laps}


def _sector_data_to_json(sector_data):
    """Convert sector_data dict to JSON-serializable format."""
    result = {}
    for key, val in sector_data.items():
        if key == "sector_times":
            # Convert int keys to strings
            result[key] = {str(k): v for k, v in val.items()}
        elif key == "sector_boundaries":
            result[key] = [float(b) for b in val] if val else []
        else:
            result[key] = val
    return result
