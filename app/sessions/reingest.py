import csv
import gzip
import os
import tempfile

from flask import current_app

from app import db
from app.models import (
    Lap, Telemetry, CornerRecord, CornerSummary,
    SectorTime, ChartData, SessionUpload, Track, TrackCorner,
)
from app.sessions.ingest import ingest_session


def _auto_detect_track(csv_path):
    """Try to match a track from the first GPS coordinate in the CSV.

    Returns a Track or None.
    """
    try:
        with open(csv_path, 'r') as f:
            reader = csv.reader(f)
            # Find header row
            header = None
            for row in reader:
                if row and row[0].strip().lower() == 'timestamp':
                    header = [c.strip().lower() for c in row]
                    break
            if not header:
                return None
            # Skip units and source rows
            next(reader, None)
            next(reader, None)
            # Read first data row
            first_row = next(reader, None)
            if not first_row:
                return None

            lat_idx = lon_idx = -1
            for i, col in enumerate(header):
                if 'latitude' in col and lat_idx < 0:
                    lat_idx = i
                if 'longitude' in col and lon_idx < 0:
                    lon_idx = i
            if lat_idx < 0 or lon_idx < 0:
                return None

            lat = float(first_row[lat_idx])
            lon = float(first_row[lon_idx])
    except Exception:
        return None

    # Find nearest track (same threshold as create form: ~5km ≈ 0.002 deg²)
    tracks = Track.query.all()
    best_track = None
    best_dist = float('inf')
    for t in tracks:
        d = (t.lat - lat) ** 2 + (t.lon - lon) ** 2
        if d < best_dist:
            best_dist = d
            best_track = t
    if best_track and best_dist <= 0.002:
        return best_track
    return None


def reingest_session(session):
    """Re-process a session from its stored compressed CSV.

    Returns True on success, False if no stored CSV is available.
    """
    upload = SessionUpload.query.filter_by(session_id=session.id).first()
    if not upload or not upload.csv_compressed:
        return False

    csv_data = gzip.decompress(upload.csv_compressed)

    # Delete computed data and old upload
    Lap.query.filter_by(session_id=session.id).delete()
    Telemetry.query.filter_by(session_id=session.id).delete()
    CornerRecord.query.filter_by(session_id=session.id).delete()
    CornerSummary.query.filter_by(session_id=session.id).delete()
    SectorTime.query.filter_by(session_id=session.id).delete()
    ChartData.query.filter_by(session_id=session.id).delete()
    SessionUpload.query.filter_by(session_id=session.id).delete()
    db.session.flush()

    temp_fd, temp_path = tempfile.mkstemp(suffix='.csv')
    try:
        with os.fdopen(temp_fd, 'wb') as f:
            f.write(csv_data)

        track = db.session.get(Track, session.track_id) if session.track_id else None

        # Auto-detect track from GPS if none assigned
        if not track:
            track = _auto_detect_track(temp_path)
            if track:
                session.track_id = track.id
                current_app.logger.info(
                    'Auto-detected track "%s" for session %d', track.name, session.id
                )

        sf_gate = None
        if track:
            corners = TrackCorner.query.filter_by(
                track_id=track.id,
            ).order_by(TrackCorner.sort_order).all()
            track_corners = [
                {
                    'name': c.name, 'lat': c.lat, 'lon': c.lon,
                    'trap_lat1': c.trap_lat1, 'trap_lon1': c.trap_lon1,
                    'trap_lat2': c.trap_lat2, 'trap_lon2': c.trap_lon2,
                }
                for c in corners
            ] if corners else None
            track_coords = (track.lat, track.lon, track.timezone)
            if track.sf_lat1 is not None:
                sf_gate = {
                    'sf_lat1': track.sf_lat1, 'sf_lon1': track.sf_lon1,
                    'sf_lat2': track.sf_lat2, 'sf_lon2': track.sf_lon2,
                }
        else:
            track_corners = None
            track_coords = None

        current_app.logger.info('Reingesting session %d', session.id)
        ingest_session(temp_path, session, track_coords, track_corners, sf_gate=sf_gate)
        session.needs_reingest = False
        db.session.commit()
        current_app.logger.info('Session %d reingested successfully', session.id)
        return True
    finally:
        os.unlink(temp_path)
