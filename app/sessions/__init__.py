from flask import Blueprint

bp = Blueprint('sessions', __name__, template_folder='../templates/sessions')

from app.sessions import routes  # noqa: E402, F401
