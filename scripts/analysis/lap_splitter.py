"""Gate-based lap splitting using GPS start/finish line crossing detection."""

import numpy as np
import pandas as pd


def _segments_intersect(ax1, ay1, ax2, ay2, bx1, by1, bx2, by2):
    """Check if two line segments intersect and return the interpolation parameter.

    Segment A: (ax1,ay1)→(ax2,ay2), Segment B: (bx1,by1)→(bx2,by2).
    Returns the parameter t (0–1) along segment A where the intersection
    occurs, or None if the segments do not intersect.
    """
    d1x = ax2 - ax1
    d1y = ay2 - ay1
    d2x = bx2 - bx1
    d2y = by2 - by1
    cross = d1x * d2y - d1y * d2x
    if abs(cross) < 1e-12:
        return None

    dx = bx1 - ax1
    dy = by1 - ay1
    t = (dx * d2y - dy * d2x) / cross
    u = (dx * d1y - dy * d1x) / cross
    if 0 <= t <= 1 and 0 <= u <= 1:
        return t
    return None


def _find_crossings(lat, lon, elapsed, gate_lat1, gate_lon1, gate_lat2, gate_lon2,
                    directional=True):
    """Find indices where the GPS path crosses the gate line.

    Returns list of dicts with keys: idx, time, t (interpolation parameter).
    """
    crossings = []
    for i in range(1, len(lat)):
        t = _segments_intersect(
            lat[i - 1], lon[i - 1], lat[i], lon[i],
            gate_lat1, gate_lon1, gate_lat2, gate_lon2,
        )
        if t is not None:
            if directional:
                # Only count crossings in one direction (cross product > 0)
                dx = lat[i] - lat[i - 1]
                dy = lon[i] - lon[i - 1]
                gate_x = gate_lat2 - gate_lat1
                gate_y = gate_lon2 - gate_lon1
                if dx * gate_y - dy * gate_x <= 0:
                    continue

            cross_time = elapsed[i - 1] + t * (elapsed[i] - elapsed[i - 1])
            crossings.append({'idx': i, 'time': cross_time, 't': t})

    return crossings


def _debounce_crossings(crossings, min_interval=10.0):
    """Filter crossings closer than min_interval seconds apart."""
    if not crossings:
        return crossings
    filtered = [crossings[0]]
    for c in crossings[1:]:
        if c['time'] - filtered[-1]['time'] > min_interval:
            filtered.append(c)
    return filtered


def split_laps_by_gate(telemetry_df, sf_gate):
    """Recompute lap_number using start/finish gate crossing detection.

    Args:
        telemetry_df: DataFrame with latitude/longitude and elapsed_time columns.
        sf_gate: dict with keys sf_lat1, sf_lon1, sf_lat2, sf_lon2.

    Returns:
        DataFrame with lap_number recomputed based on gate crossings.
        If fewer than 2 crossings are detected, returns the original DataFrame.
    """
    # Find lat/lon columns (may have sensor suffixes)
    lat_col = lon_col = None
    for col in telemetry_df.columns:
        cl = col.lower()
        if 'latitude' in cl and lat_col is None:
            lat_col = col
        elif 'longitude' in cl and lon_col is None:
            lon_col = col

    if not lat_col or not lon_col or 'elapsed_time' not in telemetry_df.columns:
        return telemetry_df

    lat = telemetry_df[lat_col].values
    lon = telemetry_df[lon_col].values
    elapsed = telemetry_df['elapsed_time'].values

    gate_lat1 = sf_gate['sf_lat1']
    gate_lon1 = sf_gate['sf_lon1']
    gate_lat2 = sf_gate['sf_lat2']
    gate_lon2 = sf_gate['sf_lon2']

    # Try directional crossings first
    crossings = _find_crossings(lat, lon, elapsed,
                                gate_lat1, gate_lon1, gate_lat2, gate_lon2,
                                directional=True)

    # Fallback: accept both directions if fewer than 2 same-direction crossings
    if len(crossings) < 2:
        crossings = _find_crossings(lat, lon, elapsed,
                                    gate_lat1, gate_lon1, gate_lat2, gate_lon2,
                                    directional=False)

    crossings = _debounce_crossings(crossings)

    if len(crossings) < 2:
        return telemetry_df

    # Work on a copy to avoid mutating the input.
    df = telemetry_df.copy()
    orig_columns = df.columns.tolist()
    numeric_cols = set(df.select_dtypes(include=[np.number]).columns)

    # Build synthetic boundary rows (one per crossing).
    # Insert in reverse order to preserve indices.
    for c in reversed(crossings):
        idx = c['idx']
        t = c['t']
        prev = df.iloc[idx - 1]
        cur = df.iloc[idx]

        synthetic = {}
        for col in orig_columns:
            if col in numeric_cols:
                pv = prev[col]
                cv = cur[col]
                if pd.notna(pv) and pd.notna(cv):
                    synthetic[col] = pv + t * (cv - pv)
                else:
                    synthetic[col] = cv
            else:
                synthetic[col] = cur[col]

        synthetic['elapsed_time'] = c['time']

        new_row = pd.DataFrame([synthetic], columns=orig_columns)
        top = df.iloc[:idx]
        bottom = df.iloc[idx:]
        df = pd.concat([top, new_row, bottom], ignore_index=True)

    # Re-detect crossing positions by finding rows with the exact crossing times.
    # After inserting N synthetic rows in reverse, the crossings are shifted.
    # Simpler: just assign lap numbers by scanning elapsed_time against sorted crossing times.
    crossing_times = sorted(c['time'] for c in crossings)

    lap_num = 0
    cross_ptr = 0
    lap_numbers = []
    elapsed_vals = df['elapsed_time'].values
    for i in range(len(df)):
        if cross_ptr < len(crossing_times) and elapsed_vals[i] >= crossing_times[cross_ptr]:
            # Check if this is past the crossing (not the synthetic row itself)
            # The synthetic row has elapsed_time == crossing_time and belongs to the previous lap.
            if elapsed_vals[i] > crossing_times[cross_ptr]:
                lap_num += 1
                cross_ptr += 1
            elif i > 0 and elapsed_vals[i - 1] < crossing_times[cross_ptr]:
                # This is the synthetic row itself — still on the old lap
                pass
            else:
                lap_num += 1
                cross_ptr += 1
        lap_numbers.append(lap_num)

    df['lap_number'] = lap_numbers

    return df
