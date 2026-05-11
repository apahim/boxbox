from flask import Blueprint

bp = Blueprint('leaderboard', __name__, template_folder='../templates/leaderboard')

from app.leaderboard import routes  # noqa: E402, F401
