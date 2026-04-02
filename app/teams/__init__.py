from flask import Blueprint

bp = Blueprint('teams', __name__, template_folder='../templates/teams')

from app.teams import routes  # noqa: E402, F401
