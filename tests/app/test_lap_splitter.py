"""Unit tests for GPS gate-based lap splitting."""

import numpy as np
import pandas as pd
import pytest

from scripts.analysis.lap_splitter import (
    _segments_intersect,
    _find_crossings,
    _debounce_crossings,
    split_laps_by_gate,
)


# ---- Helper to build a simple telemetry DataFrame ----

def _make_telemetry(lats, lons, elapsed_times, lap_numbers=None):
    """Build a minimal telemetry DataFrame from coordinate arrays."""
    df = pd.DataFrame({
        'latitude': lats,
        'longitude': lons,
        'elapsed_time': elapsed_times,
        'lap_number': lap_numbers if lap_numbers is not None else [1] * len(lats),
        'speed_gps': [10.0] * len(lats),
        'altitude': [100.0] * len(lats),
        'distance_traveled': elapsed_times,
    })
    return df


def _oval_path(n_laps=3, points_per_lap=20):
    """Generate a simple oval GPS path that crosses a horizontal gate line multiple times.

    The path goes: right along y=0.001, turns up, left along y=-0.001, turns down.
    The gate is a horizontal line at y=0 crossing x=0.
    Each lap takes ~60 seconds.
    """
    lats = []
    lons = []
    times = []

    # Gate will be at lon=0, from lat=-0.001 to lat=0.001
    # Path oscillates in longitude crossing lon=0 repeatedly

    total_points = n_laps * points_per_lap + points_per_lap  # extra for pre-lap
    for i in range(total_points):
        # Sinusoidal path in longitude, linear in latitude progress
        frac = i / points_per_lap
        # Longitude oscillates: crosses 0 twice per cycle (going right, going left)
        lon = 0.002 * np.sin(2 * np.pi * frac)
        # Latitude drifts slightly so path doesn't perfectly overlap
        lat = 0.0001 * np.sin(2 * np.pi * frac * 0.1)
        lats.append(lat)
        lons.append(lon)
        times.append(i * 3.0)  # 3 seconds between points

    return lats, lons, times


# ---- Tests for _segments_intersect ----

class TestSegmentsIntersect:
    def test_crossing_segments(self):
        # X pattern: (0,0)→(1,1) crosses (0,1)→(1,0)
        t = _segments_intersect(0, 0, 1, 1, 0, 1, 1, 0)
        assert t is not None
        assert 0 <= t <= 1

    def test_parallel_segments(self):
        # Parallel horizontal lines
        t = _segments_intersect(0, 0, 1, 0, 0, 1, 1, 1)
        assert t is None

    def test_non_crossing_segments(self):
        # Segments that don't reach each other
        t = _segments_intersect(0, 0, 0.3, 0.3, 0.7, 0.7, 1, 1)
        assert t is None

    def test_t_value_midpoint(self):
        # (0,0)→(2,0) crosses (1,-1)→(1,1) at t=0.5
        t = _segments_intersect(0, 0, 2, 0, 1, -1, 1, 1)
        assert t is not None
        assert abs(t - 0.5) < 1e-6


# ---- Tests for _find_crossings ----

class TestFindCrossings:
    def test_detects_crossings(self):
        # Path crosses a vertical gate at lon=0
        lat = [0.0, 0.0, 0.0, 0.0]
        lon = [-0.001, 0.001, -0.001, 0.001]
        elapsed = [0.0, 30.0, 60.0, 90.0]
        gate = (-.001, 0.0, 0.001, 0.0)  # horizontal gate at lon=0

        crossings = _find_crossings(lat, lon, elapsed, *gate, directional=False)
        assert len(crossings) == 3  # crosses at each step

    def test_directional_filtering(self):
        # Same path, but only one direction should match
        lat = [0.0, 0.0, 0.0, 0.0, 0.0]
        lon = [-0.001, 0.001, -0.001, 0.001, -0.001]
        elapsed = [0.0, 30.0, 60.0, 90.0, 120.0]
        gate = (-0.001, 0.0, 0.001, 0.0)

        crossings_dir = _find_crossings(lat, lon, elapsed, *gate, directional=True)
        crossings_all = _find_crossings(lat, lon, elapsed, *gate, directional=False)
        # Directional should find fewer crossings than bidirectional
        assert len(crossings_dir) < len(crossings_all)

    def test_no_crossings(self):
        # Path never crosses the gate
        lat = [0.0, 0.0, 0.0]
        lon = [0.001, 0.002, 0.003]
        elapsed = [0.0, 30.0, 60.0]
        gate = (-0.001, -0.01, 0.001, -0.01)  # gate far from path

        crossings = _find_crossings(lat, lon, elapsed, *gate, directional=False)
        assert len(crossings) == 0


# ---- Tests for _debounce_crossings ----

class TestDebounceCrossings:
    def test_filters_close_crossings(self):
        crossings = [
            {'idx': 1, 'time': 0.0, 't': 0.5},
            {'idx': 2, 'time': 5.0, 't': 0.5},   # too close (< 10s)
            {'idx': 3, 'time': 30.0, 't': 0.5},
            {'idx': 4, 'time': 35.0, 't': 0.5},   # too close
            {'idx': 5, 'time': 60.0, 't': 0.5},
        ]
        filtered = _debounce_crossings(crossings)
        assert len(filtered) == 3
        assert [c['time'] for c in filtered] == [0.0, 30.0, 60.0]

    def test_empty_input(self):
        assert _debounce_crossings([]) == []

    def test_single_crossing(self):
        crossings = [{'idx': 1, 'time': 10.0, 't': 0.5}]
        assert len(_debounce_crossings(crossings)) == 1


# ---- Tests for split_laps_by_gate ----

class TestSplitLapsByGate:
    def test_basic_lap_splitting(self):
        lats, lons, times = _oval_path(n_laps=3)
        df = _make_telemetry(lats, lons, times)

        # Gate: horizontal line at lon=0
        sf_gate = {
            'sf_lat1': -0.001, 'sf_lon1': 0.0,
            'sf_lat2': 0.001, 'sf_lon2': 0.0,
        }

        result = split_laps_by_gate(df, sf_gate)

        # Should have multiple distinct lap numbers
        unique_laps = sorted(result['lap_number'].unique())
        assert len(unique_laps) >= 3  # at least 3 laps from 3 crossings

    def test_returns_original_when_no_crossings(self):
        # Path far from gate
        lats = [10.0, 10.0, 10.0]
        lons = [10.0, 10.001, 10.002]
        times = [0.0, 30.0, 60.0]
        df = _make_telemetry(lats, lons, times)

        sf_gate = {
            'sf_lat1': 0.0, 'sf_lon1': 0.0,
            'sf_lat2': 0.001, 'sf_lon2': 0.0,
        }

        result = split_laps_by_gate(df, sf_gate)
        # Original lap_number should be preserved
        assert list(result['lap_number']) == [1, 1, 1]

    def test_returns_original_when_only_one_crossing(self):
        # Path crosses gate only once
        lats = [0.0, 0.0, 0.0]
        lons = [-0.001, 0.001, 0.002]
        times = [0.0, 30.0, 60.0]
        df = _make_telemetry(lats, lons, times)

        sf_gate = {
            'sf_lat1': -0.001, 'sf_lon1': 0.0,
            'sf_lat2': 0.001, 'sf_lon2': 0.0,
        }

        result = split_laps_by_gate(df, sf_gate)
        assert len(result) == len(df)

    def test_missing_columns_returns_original(self):
        df = pd.DataFrame({'x': [1, 2, 3], 'y': [4, 5, 6]})
        sf_gate = {
            'sf_lat1': 0.0, 'sf_lon1': 0.0,
            'sf_lat2': 0.001, 'sf_lon2': 0.0,
        }
        result = split_laps_by_gate(df, sf_gate)
        assert list(result.columns) == ['x', 'y']

    def test_synthetic_rows_inserted(self):
        lats, lons, times = _oval_path(n_laps=3)
        df = _make_telemetry(lats, lons, times)
        original_len = len(df)

        sf_gate = {
            'sf_lat1': -0.001, 'sf_lon1': 0.0,
            'sf_lat2': 0.001, 'sf_lon2': 0.0,
        }

        result = split_laps_by_gate(df, sf_gate)
        # Synthetic rows should be added (one per crossing)
        assert len(result) > original_len

    def test_does_not_mutate_input(self):
        lats, lons, times = _oval_path(n_laps=3)
        df = _make_telemetry(lats, lons, times)
        original_laps = df['lap_number'].tolist()

        sf_gate = {
            'sf_lat1': -0.001, 'sf_lon1': 0.0,
            'sf_lat2': 0.001, 'sf_lon2': 0.0,
        }

        split_laps_by_gate(df, sf_gate)
        assert df['lap_number'].tolist() == original_laps

    def test_lap_numbers_are_sequential(self):
        lats, lons, times = _oval_path(n_laps=4)
        df = _make_telemetry(lats, lons, times)

        sf_gate = {
            'sf_lat1': -0.001, 'sf_lon1': 0.0,
            'sf_lat2': 0.001, 'sf_lon2': 0.0,
        }

        result = split_laps_by_gate(df, sf_gate)
        unique_laps = sorted(result['lap_number'].unique())
        # Lap numbers should be consecutive starting from 0
        assert unique_laps == list(range(len(unique_laps)))
