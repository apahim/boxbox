from flask import Blueprint

bp = Blueprint('events', __name__, template_folder='../templates/events')

from app.events import routes  # noqa: E402, F401
