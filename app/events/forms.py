from flask_wtf import FlaskForm
from wtforms import StringField, SelectField, SubmitField, DateField, TimeField, TextAreaField
from wtforms.validators import DataRequired, Optional, Length


def _coerce_optional_int(val):
    """Coerce to int, returning None for empty/zero values."""
    try:
        v = int(val)
        return v if v else None
    except (ValueError, TypeError):
        return None


class EventForm(FlaskForm):
    name = StringField('Event Name', validators=[DataRequired(), Length(max=200)])
    date = DateField('Date', validators=[DataRequired()])
    time = TimeField('Start Time', validators=[Optional()])
    track_id = SelectField('Track', coerce=_coerce_optional_int, validators=[Optional()])
    description = TextAreaField('Description', validators=[Optional(), Length(max=500)])
    submit = SubmitField('Create Event')
