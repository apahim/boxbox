from flask_wtf import FlaskForm
from flask_wtf.file import FileField, FileAllowed
from wtforms import StringField, SelectField, SubmitField, DateField, TimeField, HiddenField
from wtforms.validators import DataRequired, Optional


def _coerce_optional_int(val):
    """Coerce to int, returning None for empty/zero values."""
    try:
        v = int(val)
        return v if v else None
    except (ValueError, TypeError):
        return None


class SessionEditForm(FlaskForm):
    date = DateField('Date', validators=[DataRequired()])
    track_id = SelectField('Track', coerce=_coerce_optional_int, validators=[Optional()])
    session_start = TimeField('Session Start', validators=[Optional()])
    labels = HiddenField('Labels', default='[]')
    submit = SubmitField('Save Changes')


class SessionCreateForm(FlaskForm):
    csv_file = FileField('Telemetry CSV', validators=[
        FileAllowed(['csv'], 'CSV files only'),
    ])
    data_source = HiddenField('Data Source', default='racechrono')
    date = DateField('Date', validators=[DataRequired()])
    track_id = SelectField('Track', coerce=_coerce_optional_int, validators=[Optional()])
    session_start = TimeField('Session Start', validators=[Optional()])
    labels = HiddenField('Labels', default='[]')
    submit = SubmitField('Upload & Process')
