import pytest

from app import create_app, db as _db
from app.models import Track, TrackCorner


KILTORCAN_TRACK = {
    'slug': 'kiltorcan_raceway',
    'name': 'Kiltorcan Raceway',
    'lat': 52.5436,
    'lon': -7.3656,
    'timezone': 'Europe/Dublin',
    'corners': [
        {'name': 'T1', 'lat': 52.46228, 'lon': -7.18163},
        {'name': 'T2', 'lat': 52.46310, 'lon': -7.18208},
        {'name': 'T3', 'lat': 52.46325, 'lon': -7.18278},
        {'name': 'T4', 'lat': 52.46400, 'lon': -7.18190},
        {'name': 'T5', 'lat': 52.46383, 'lon': -7.18223},
        {'name': 'T6', 'lat': 52.46420, 'lon': -7.18148},
    ],
}


def seed_test_track(track_data=None):
    """Create a Track with TrackCorners in the test database.

    Returns (track, track_coords, track_corners) where track_coords and
    track_corners are in the format expected by ingest_session().
    """
    td = track_data or KILTORCAN_TRACK
    track = Track(
        slug=td['slug'], name=td['name'],
        lat=td['lat'], lon=td['lon'],
        timezone=td.get('timezone', 'UTC'),
    )
    _db.session.add(track)
    _db.session.flush()

    offset = 0.00005
    for i, c in enumerate(td.get('corners', [])):
        _db.session.add(TrackCorner(
            track_id=track.id, name=c['name'], sort_order=i,
            trap_lat1=c['lat'] + offset, trap_lon1=c['lon'] - offset,
            trap_lat2=c['lat'] - offset, trap_lon2=c['lon'] + offset,
        ))
    _db.session.flush()

    corners = TrackCorner.query.filter_by(track_id=track.id).order_by(TrackCorner.sort_order).all()
    track_corners = [
        {
            'name': c.name, 'lat': c.lat, 'lon': c.lon,
            'trap_lat1': c.trap_lat1, 'trap_lon1': c.trap_lon1,
            'trap_lat2': c.trap_lat2, 'trap_lon2': c.trap_lon2,
        }
        for c in corners
    ] if corners else None
    track_coords = (track.lat, track.lon, track.timezone)

    return track, track_coords, track_corners


@pytest.fixture
def app():
    app = create_app('testing')
    with app.app_context():
        _db.create_all()
        yield app
        _db.session.remove()
        _db.drop_all()


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def db_session(app):
    with app.app_context():
        yield _db.session
