from flask_wtf import FlaskForm
from wtforms import (StringField, SelectField, IntegerField, DateField,
                     HiddenField, SubmitField)
from wtforms.validators import DataRequired, Optional, Length, NumberRange


def _coerce_optional_int(val):
    """Coerce to int, returning None for empty/zero values."""
    try:
        v = int(val)
        return v if v else None
    except (ValueError, TypeError):
        return None


class LeaderboardForm(FlaskForm):
    name = StringField('Leaderboard Name',
                       validators=[DataRequired(), Length(max=200)])
    track_id = SelectField('Track', coerce=_coerce_optional_int,
                           validators=[DataRequired()])
    labels = HiddenField('Labels', default='[]')
    period_type = SelectField('Period', choices=[
        ('last_30', 'Last 30 days'),
        ('last_90', 'Last 90 days'),
        ('this_year', 'This year'),
        ('all_time', 'All time'),
        ('custom', 'Custom range'),
    ], validators=[DataRequired()])
    period_start = DateField('Start Date', validators=[Optional()])
    period_end = DateField('End Date', validators=[Optional()])
    max_drivers = IntegerField('Top N Drivers', default=10,
                               validators=[DataRequired(),
                                           NumberRange(min=1, max=100)])
    submit = SubmitField('Create Leaderboard')
