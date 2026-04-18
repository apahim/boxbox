from flask_wtf import FlaskForm
from wtforms import BooleanField, StringField, HiddenField, SubmitField
from wtforms.validators import DataRequired, Length


class TrackForm(FlaskForm):
    name = StringField('Track Name', validators=[DataRequired(), Length(max=200)])
    lat = HiddenField('Latitude', validators=[DataRequired()])
    lon = HiddenField('Longitude', validators=[DataRequired()])
    is_official = BooleanField('Official track (visible to all users)')
    submit = SubmitField('Create Track')
