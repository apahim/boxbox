"""Track DNA configuration identification (plan Phase 2).

Proposes track layouts ("configurations") by clustering a track's sessions
on per-session geometric features computed in a common track-centered
projection frame (decision D11):

- direction: sign of the median per-lap shoelace signed area
- length: median per-lap ``distance_traveled`` span (never raw point-step
  arclength — it underestimates badly on 25 Hz data in slow corners)
- bbox: 2.5–97.5 percentile bounding box of all session positions
  (percentiles are mandatory: raw bboxes get corrupted by GPS glitches)
- S/F point: per-axis median of valid laps' first GPS positions

Sessions are joined transitively (union-find) when they share a direction,
their S/F points lie within ``SF_MAX_M`` metres and their robust bboxes
overlap with IoU >= ``BBOX_IOU_MIN`` (decision D9). Median lap length is a
soft signal only — reported per cluster with a warning above 5% spread, it
never splits a cluster (wet sessions legitimately run 5–15% longer laps on
the same layout).

Nothing here persists anything: proposals are computed on demand for the
admin UI and only become ``track_configs`` rows on explicit admin action
(decision D7, revised). Demo-labelled and duplicate sessions ARE clustered
— they physically happened on a layout — and are badged separately at
payload time so the admin sees what the scorecard will exclude.
"""

import math
import statistics
from dataclasses import dataclass

from app import db
from app.models import Session, Telemetry, Track
from app.track_dna.hygiene import MIN_SAMPLES, classify_track_sessions
from scripts.analysis.track_dna import bbox_iou, robust_bbox, signed_area
from scripts.analysis.utils import project_to_meters

# Clustering criteria (plan Section 14.1; decision D9 — hard criteria).
SF_MAX_M = 50.0            # max S/F distance to join two sessions (m)
BBOX_IOU_MIN = 0.75        # min robust-bbox IoU to join two sessions
BBOX_PERCENTILES = (2.5, 97.5)

# Length is a soft signal only (D9): reported, never a split criterion.
LENGTH_SPREAD_WARN = 0.05  # warn above 5% (min-max)/median spread

# Chunk size for the single streamed bulk telemetry query.
STREAM_CHUNK = 5000

UNCLUSTERED_NO_TELEMETRY = 'insufficient telemetry'


@dataclass(frozen=True)
class SessionFeatures:
    """Per-session geometric features in the common track-centered frame."""

    session_id: int
    direction: str    # 'cw' | 'ccw'
    length: float     # median per-lap distance_traveled span (m)
    bbox: tuple       # (x0, y0, x1, y1) robust percentile bbox (m)
    sf: tuple         # (x, y) median of valid laps' first points (m)


@dataclass(frozen=True)
class ClusterProposal:
    """One proposed configuration: a connected component of sessions."""

    direction: str
    session_ids: list        # ordered by session id
    length_min: float
    length_median: float
    length_max: float
    footprint: tuple         # (width, height) of the union bbox (m)
    sf_spread: float         # max member distance from median S/F (m)

    @property
    def length_spread_pct(self):
        if self.length_median <= 0:
            return 0.0
        return (self.length_max - self.length_min) / self.length_median * 100.0

    @property
    def length_warning(self):
        return self.length_spread_pct > LENGTH_SPREAD_WARN * 100.0

    def to_dict(self):
        return {
            'direction': self.direction,
            'session_ids': list(self.session_ids),
            'length': {
                'min': self.length_min,
                'median': self.length_median,
                'max': self.length_max,
                'spread_pct': self.length_spread_pct,
            },
            'length_warning': self.length_warning,
            'footprint_m': [self.footprint[0], self.footprint[1]],
            'sf_spread_m': self.sf_spread,
        }


@dataclass
class TrackClustering:
    """Clustering result for one track (read-only — nothing persisted)."""

    track_id: int
    track_name: str
    features: dict     # session_id -> SessionFeatures | None
    clusters: list     # ClusterProposal, ordered by min session id
    unclustered: list  # (session_id, reason), ordered by session id


def session_features(session_id, laps, center):
    """Compute one session's clustering features.

    ``laps`` is a list of ``(lap_number, lat, lon, dist)`` tuples — one per
    lap present in the telemetry, each holding that lap's rows in telemetry
    order (rows without GPS positions already dropped; ``dist`` holds the
    non-null ``distance_traveled`` values). ``center`` is the track's
    ``(lat, lon)``: features are only comparable between sessions in this
    common frame — per-session centering causes false splits (D11).

    A lap is valid when ``lap_number >= 1`` and it has at least
    ``MIN_SAMPLES`` GPS samples (Phase-1 hygiene rule). Direction and S/F
    come from valid laps only; the bbox uses every session position.

    Returns SessionFeatures, or None when no lap is valid (the session is
    unclusterable with reason 'insufficient telemetry').
    """
    valid = [(n, lat, lon, dist) for n, lat, lon, dist in laps
             if n >= 1 and len(lat) >= MIN_SAMPLES]
    if not valid:
        return None

    areas = []
    spans = []
    firsts = []
    for _n, lat, lon, dist in valid:
        x, y = project_to_meters(lat, lon, center)
        areas.append(signed_area(x, y))
        if dist:
            spans.append(max(dist) - min(dist))
        firsts.append((float(x[0]), float(y[0])))

    all_lat = [v for lap in laps for v in lap[1]]
    all_lon = [v for lap in laps for v in lap[2]]
    pos_x, pos_y = project_to_meters(all_lat, all_lon, center)
    bbox = robust_bbox(pos_x, pos_y, BBOX_PERCENTILES)

    return SessionFeatures(
        session_id=session_id,
        direction='cw' if statistics.median(areas) < 0 else 'ccw',
        length=statistics.median(spans) if spans else 0.0,
        bbox=bbox,
        sf=(statistics.median(f[0] for f in firsts),
            statistics.median(f[1] for f in firsts)),
    )


def _sf_distance(a, b):
    return math.hypot(a.sf[0] - b.sf[0], a.sf[1] - b.sf[1])


def _cluster_features(clusterable):
    """Union-find connected components over the join criteria (D9).

    ``clusterable`` is an ordered list of SessionFeatures. Two sessions
    join when they share direction AND S/F distance <= SF_MAX_M AND bbox
    IoU >= BBOX_IOU_MIN; joins are transitive.
    """
    n = len(clusterable)
    parent = list(range(n))

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    for i in range(n):
        for j in range(i + 1, n):
            a, b = clusterable[i], clusterable[j]
            if a.direction != b.direction:
                continue
            if _sf_distance(a, b) > SF_MAX_M:
                continue
            if bbox_iou(a.bbox, b.bbox) < BBOX_IOU_MIN:
                continue
            ri, rj = find(i), find(j)
            if ri != rj:
                parent[ri] = rj

    groups = {}
    for i in range(n):
        groups.setdefault(find(i), []).append(clusterable[i])
    return list(groups.values())


def _build_cluster(members):
    lengths = sorted(m.length for m in members)
    med_sf = (statistics.median(m.sf[0] for m in members),
              statistics.median(m.sf[1] for m in members))
    x0 = min(m.bbox[0] for m in members)
    y0 = min(m.bbox[1] for m in members)
    x1 = max(m.bbox[2] for m in members)
    y1 = max(m.bbox[3] for m in members)
    return ClusterProposal(
        direction=members[0].direction,
        session_ids=sorted(m.session_id for m in members),
        length_min=lengths[0],
        length_median=statistics.median(lengths),
        length_max=lengths[-1],
        footprint=(x1 - x0, y1 - y0),
        sf_spread=max(math.hypot(m.sf[0] - med_sf[0],
                                 m.sf[1] - med_sf[1]) for m in members),
    )


def _session_features_bulk(session_ids, center):
    """Features for every session, from ONE streamed telemetry query.

    Returns ``{session_id: SessionFeatures | None}`` keyed in session-id
    order. Sessions without a valid lap map to None. Rows are streamed in
    ``(session_id, lap_number, id)`` order (insertion order = telemetry
    order) and finalized per session, so peak memory is one session's
    arrays rather than the track's full telemetry.
    """
    features = {sid: None for sid in session_ids}
    if not session_ids:
        return features

    rows = db.session.execute(
        db.select(Telemetry.session_id,
                  Telemetry.lap_number,
                  Telemetry.latitude,
                  Telemetry.longitude,
                  Telemetry.distance_traveled)
        .where(Telemetry.session_id.in_(session_ids))
        .order_by(Telemetry.session_id, Telemetry.lap_number, Telemetry.id)
        .execution_options(yield_per=STREAM_CHUNK)
    )

    current_sid = None
    laps = []
    lap = None

    def finalize(sid, laps):
        features[sid] = session_features(sid, laps, center)

    for sid, lap_number, lat, lon, dist in rows:
        if sid != current_sid:
            if current_sid is not None:
                finalize(current_sid, laps)
            current_sid, laps, lap = sid, [], None
        if lap is None or lap[0] != lap_number:
            lap = [lap_number, [], [], []]
            laps.append(lap)
        if lat is not None and lon is not None:
            lap[1].append(lat)
            lap[2].append(lon)
        if dist is not None:
            lap[3].append(dist)
    if current_sid is not None:
        finalize(current_sid, laps)

    return features


def cluster_track_sessions(track_id):
    """Cluster a track's sessions into proposed configurations.

    Returns a TrackClustering, or None when the track does not exist.
    Read-only: nothing is written to the database.
    """
    track = db.session.get(Track, track_id)
    if track is None:
        return None

    sessions = (Session.query.filter_by(track_id=track_id)
                .order_by(Session.id).all())
    session_ids = [s.id for s in sessions]
    features = _session_features_bulk(session_ids, (track.lat, track.lon))

    # groups appear in order of their first member, i.e. ordered by
    # min session id (deterministic ordering everywhere)
    clusterable = [features[sid] for sid in session_ids
                   if features[sid] is not None]
    clusters = [_build_cluster(group)
                for group in _cluster_features(clusterable)]

    unclustered = [(sid, UNCLUSTERED_NO_TELEMETRY)
                   for sid in session_ids if features[sid] is None]

    return TrackClustering(
        track_id=track.id,
        track_name=track.name,
        features=features,
        clusters=clusters,
        unclustered=unclustered,
    )


def proposals_payload(track_id):
    """Full proposals payload for the admin UI.

    The clustering result plus, per session, the Phase-1 hygiene verdict
    and ``needs_reingest`` flag for badging. Demo/duplicate sessions stay
    in their clusters (they physically happened on a layout) but carry
    their exclusion badges so the admin sees what the scorecard will
    exclude.

    Returns a JSON-serialisable dict, or None when the track does not
    exist.
    """
    clustering = cluster_track_sessions(track_id)
    if clustering is None:
        return None

    verdicts = {v.session_id: v
                for v in classify_track_sessions(track_id).verdicts}

    session_entries = []
    for session in (Session.query.filter_by(track_id=track_id)
                    .order_by(Session.id).all()):
        v = verdicts.get(session.id)
        session_entries.append({
            'session_id': session.id,
            'date': session.date.isoformat() if session.date else None,
            'data_source': session.data_source,
            'needs_reingest': bool(session.needs_reingest),
            'condition': v.condition if v else None,
            'included': v.included if v else True,
            'exclusion_reason': v.exclusion_reason if v else None,
            'duplicate_of': v.duplicate_of if v else None,
            'provisional_laps': v.provisional_laps if v else 0,
            'clustered': clustering.features.get(session.id) is not None,
        })

    return {
        'track_id': clustering.track_id,
        'track_name': clustering.track_name,
        'sessions': session_entries,
        'clusters': [c.to_dict() for c in clustering.clusters],
        'unclustered': [{'session_id': sid, 'reason': reason}
                        for sid, reason in clustering.unclustered],
        'params': {
            'sf_max_m': SF_MAX_M,
            'bbox_iou_min': BBOX_IOU_MIN,
            'bbox_percentiles': list(BBOX_PERCENTILES),
        },
    }
