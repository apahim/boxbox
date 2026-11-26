"""Tests for the session creation wizard."""

import io

from datetime import datetime, timezone

from app import db
from app.models import User


def _make_user(email='test@test.com', demo_seeded=True):
    return User(
        email=email,
        display_name=email.split('@')[0].title(),
        google_id='g-' + email,
        terms_accepted_at=datetime.now(timezone.utc),
        demo_seeded=demo_seeded,
    )


def _login(client, user):
    with client.session_transaction() as sess:
        sess['_user_id'] = str(user.id)


class TestCreatePage:
    def test_csv_input_has_accept_attribute(self, app, client):
        """The RaceChrono input must constrain the picker so Android offers a
        file browser instead of media/capture apps only."""
        with app.app_context():
            user = _make_user()
            db.session.add(user)
            db.session.commit()

            _login(client, user)
            rv = client.get('/sessions/create')

        assert rv.status_code == 200
        assert b'id="csv-file"' in rv.data
        assert b'accept=".csv,text/csv"' in rv.data


class TestCreateValidation:
    def test_non_csv_filename_rejected_with_field_errors(self, app, client):
        """Fetch uploads get field-level errors back so the client can show
        them instead of a generic 'Validation failed' message."""
        with app.app_context():
            user = _make_user()
            db.session.add(user)
            db.session.commit()

            _login(client, user)
            rv = client.post(
                '/sessions/create',
                data={
                    'data_source': 'racechrono',
                    'date': '2026-11-26',
                    'labels': '[]',
                    'csv_file': (io.BytesIO(b'timestamp,\n'), 'telemetry.txt'),
                },
                content_type='multipart/form-data',
                headers={'X-Requested-With': 'fetch'},
            )

        assert rv.status_code == 400
        body = rv.get_json()
        assert 'fields' in body
        messages = [msg for errs in body['fields'].values() for msg in errs]
        assert any('CSV' in msg for msg in messages)
