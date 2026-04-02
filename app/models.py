from datetime import datetime, timezone

import bcrypt
from flask_login import UserMixin

from app import db


class User(UserMixin, db.Model):
    __tablename__ = 'users'

    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(255), unique=True, nullable=False)
    password_hash = db.Column(db.LargeBinary, nullable=False)
    display_name = db.Column(db.String(100), nullable=False)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    sessions = db.relationship('Session', backref='user', lazy='dynamic')

    def set_password(self, password):
        self.password_hash = bcrypt.hashpw(
            password.encode('utf-8'), bcrypt.gensalt()
        )

    def check_password(self, password):
        return bcrypt.checkpw(password.encode('utf-8'), self.password_hash)


class Team(db.Model):
    __tablename__ = 'teams'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    slug = db.Column(db.String(100), unique=True, nullable=False)
    created_by = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    creator = db.relationship('User', backref='created_teams')
    members = db.relationship('TeamMember', backref='team', lazy='dynamic',
                              cascade='all, delete-orphan')


class TeamMember(db.Model):
    __tablename__ = 'team_members'

    id = db.Column(db.Integer, primary_key=True)
    team_id = db.Column(db.Integer, db.ForeignKey('teams.id'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    role = db.Column(db.String(20), nullable=False, default='member')
    joined_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    user = db.relationship('User', backref='team_memberships')

    __table_args__ = (
        db.UniqueConstraint('team_id', 'user_id', name='uq_team_user'),
    )


class Track(db.Model):
    __tablename__ = 'tracks'

    id = db.Column(db.Integer, primary_key=True)
    slug = db.Column(db.String(100), unique=True, nullable=False)
    name = db.Column(db.String(200), nullable=False)
    lat = db.Column(db.Float, nullable=False)
    lon = db.Column(db.Float, nullable=False)
    timezone = db.Column(db.String(50), default='UTC')
    created_by = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)

    corners = db.relationship('TrackCorner', backref='track', lazy='dynamic',
                              cascade='all, delete-orphan',
                              order_by='TrackCorner.sort_order')
    sessions = db.relationship('Session', backref='track', lazy='dynamic')


class TrackCorner(db.Model):
    __tablename__ = 'track_corners'

    id = db.Column(db.Integer, primary_key=True)
    track_id = db.Column(db.Integer, db.ForeignKey('tracks.id'), nullable=False)
    name = db.Column(db.String(50), nullable=False)
    sort_order = db.Column(db.Integer, nullable=False, default=0)
    trap_lat1 = db.Column(db.Float, nullable=False)
    trap_lon1 = db.Column(db.Float, nullable=False)
    trap_lat2 = db.Column(db.Float, nullable=False)
    trap_lon2 = db.Column(db.Float, nullable=False)

    @property
    def lat(self):
        return (self.trap_lat1 + self.trap_lat2) / 2

    @property
    def lon(self):
        return (self.trap_lon1 + self.trap_lon2) / 2


class Session(db.Model):
    __tablename__ = 'sessions'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    track_id = db.Column(db.Integer, db.ForeignKey('tracks.id'), nullable=False)
    team_id = db.Column(db.Integer, db.ForeignKey('teams.id'), nullable=True)
    date = db.Column(db.Date, nullable=False)
    session_type = db.Column(db.String(100))
    session_start = db.Column(db.String(10))
    kart_number = db.Column(db.Integer)
    driver_weight_kg = db.Column(db.Float)

    # Precomputed summary stats
    total_laps = db.Column(db.Integer)
    clean_laps = db.Column(db.Integer)
    best_lap_time = db.Column(db.Float)
    average_time = db.Column(db.Float)
    median_time = db.Column(db.Float)
    std_dev = db.Column(db.Float)
    consistency_pct = db.Column(db.Float)
    top_speed_kmh = db.Column(db.Float)
    max_lateral_g = db.Column(db.Float)
    max_braking_g = db.Column(db.Float)
    max_accel_g = db.Column(db.Float)

    weather = db.Column(db.JSON)
    coaching = db.Column(db.JSON)
    needs_reingest = db.Column(db.Boolean, default=False, nullable=False)

    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    team = db.relationship('Team', backref='sessions')
    laps = db.relationship('Lap', backref='session', lazy='dynamic',
                           cascade='all, delete-orphan')
    telemetry = db.relationship('Telemetry', backref='session', lazy='dynamic',
                                cascade='all, delete-orphan')
    corner_records = db.relationship('CornerRecord', backref='session', lazy='dynamic',
                                     cascade='all, delete-orphan')
    corner_summaries = db.relationship('CornerSummary', backref='session', lazy='dynamic',
                                       cascade='all, delete-orphan')
    sector_times = db.relationship('SectorTime', backref='session', lazy='dynamic',
                                   cascade='all, delete-orphan')
    chart_data = db.relationship('ChartData', backref='session', lazy='dynamic',
                                 cascade='all, delete-orphan')
    upload = db.relationship('SessionUpload', backref='session', uselist=False,
                             cascade='all, delete-orphan')


class Lap(db.Model):
    __tablename__ = 'laps'

    id = db.Column(db.Integer, primary_key=True)
    session_id = db.Column(db.Integer, db.ForeignKey('sessions.id'), nullable=False)
    lap_number = db.Column(db.Integer, nullable=False)
    seconds = db.Column(db.Float, nullable=False)
    is_outlier = db.Column(db.Boolean, default=False)
    outlier_reason = db.Column(db.String(200))


class Telemetry(db.Model):
    __tablename__ = 'telemetry'

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    session_id = db.Column(db.Integer, db.ForeignKey('sessions.id'), nullable=False)
    lap_number = db.Column(db.Integer)
    sample_index = db.Column(db.Integer)
    timestamp = db.Column(db.Float)
    elapsed_time = db.Column(db.Float)
    distance_traveled = db.Column(db.Float)
    latitude = db.Column(db.Float)
    longitude = db.Column(db.Float)
    altitude = db.Column(db.Float)
    bearing = db.Column(db.Float)
    speed_gps = db.Column(db.Float)
    speed_calc = db.Column(db.Float)
    lateral_acc = db.Column(db.Float)
    longitudinal_acc = db.Column(db.Float)
    combined_acc = db.Column(db.Float)
    x_acc = db.Column(db.Float)
    y_acc = db.Column(db.Float)
    z_acc = db.Column(db.Float)
    x_rotation = db.Column(db.Float)
    y_rotation = db.Column(db.Float)
    z_rotation = db.Column(db.Float)
    lean_angle = db.Column(db.Float)

    __table_args__ = (
        db.Index('ix_telemetry_session_lap', 'session_id', 'lap_number'),
    )


class CornerRecord(db.Model):
    __tablename__ = 'corner_records'

    id = db.Column(db.Integer, primary_key=True)
    session_id = db.Column(db.Integer, db.ForeignKey('sessions.id'), nullable=False)
    corner_name = db.Column(db.String(50), nullable=False)
    corner_index = db.Column(db.Integer, nullable=False)
    lap_number = db.Column(db.Integer, nullable=False)
    lat = db.Column(db.Float)
    lon = db.Column(db.Float)
    distance = db.Column(db.Float)
    corner_frac = db.Column(db.Float)
    entry_speed = db.Column(db.Float)
    min_speed = db.Column(db.Float)
    exit_speed = db.Column(db.Float)
    time_loss = db.Column(db.Float)
    braking_point = db.Column(db.Float)
    braking_distance = db.Column(db.Float)
    trail_braking_depth = db.Column(db.Float)
    root_cause = db.Column(db.String(20))


class CornerSummary(db.Model):
    __tablename__ = 'corner_summaries'

    id = db.Column(db.Integer, primary_key=True)
    session_id = db.Column(db.Integer, db.ForeignKey('sessions.id'), nullable=False)
    corner_name = db.Column(db.String(50), nullable=False)
    corner_index = db.Column(db.Integer, nullable=False)
    lat = db.Column(db.Float)
    lon = db.Column(db.Float)
    distance = db.Column(db.Float)
    archetype = db.Column(db.String(30))
    avg_time_loss = db.Column(db.Float)
    total_time_loss = db.Column(db.Float)
    best_min_speed = db.Column(db.Float)
    avg_min_speed = db.Column(db.Float)
    std_min_speed = db.Column(db.Float)
    best_entry_speed = db.Column(db.Float)
    best_exit_speed = db.Column(db.Float)
    braking_spread = db.Column(db.Float)
    dominant_root_cause = db.Column(db.String(20))


class SectorTime(db.Model):
    __tablename__ = 'sector_times'

    id = db.Column(db.Integer, primary_key=True)
    session_id = db.Column(db.Integer, db.ForeignKey('sessions.id'), nullable=False)
    lap_number = db.Column(db.Integer, nullable=False)
    sector_index = db.Column(db.Integer, nullable=False)
    sector_name = db.Column(db.String(50))
    seconds = db.Column(db.Float, nullable=False)


class ChartData(db.Model):
    __tablename__ = 'chart_data'

    id = db.Column(db.Integer, primary_key=True)
    session_id = db.Column(db.Integer, db.ForeignKey('sessions.id'), nullable=False)
    chart_type = db.Column(db.String(50), nullable=False)
    chart_key = db.Column(db.String(50), nullable=False)
    data = db.Column(db.JSON, nullable=False)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    __table_args__ = (
        db.Index('ix_chart_data_session_type_key', 'session_id', 'chart_type', 'chart_key'),
    )


class SessionUpload(db.Model):
    __tablename__ = 'session_uploads'

    id = db.Column(db.Integer, primary_key=True)
    session_id = db.Column(db.Integer, db.ForeignKey('sessions.id'), nullable=False,
                           unique=True)
    original_filename = db.Column(db.String(255))
    csv_compressed = db.Column(db.LargeBinary)
    uploaded_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
