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

        track = db.session.get(Track, session.track_id)
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

        current_app.logger.info('Reingesting session %d', session.id)
        ingest_session(temp_path, session, track_coords, track_corners)
        session.needs_reingest = False
        db.session.commit()
        current_app.logger.info('Session %d reingested successfully', session.id)
        return True
    finally:
        os.unlink(temp_path)
