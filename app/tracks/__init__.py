from flask import Blueprint

bp = Blueprint('tracks', __name__, template_folder='../templates/tracks')

from app.tracks import routes  # noqa: E402, F401
