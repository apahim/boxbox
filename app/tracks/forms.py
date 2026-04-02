from flask_wtf import FlaskForm
from wtforms import StringField, HiddenField, SubmitField
from wtforms.validators import DataRequired, Length


class TrackForm(FlaskForm):
    name = StringField('Track Name', validators=[DataRequired(), Length(max=200)])
    lat = HiddenField('Latitude', validators=[DataRequired()])
    lon = HiddenField('Longitude', validators=[DataRequired()])
    submit = SubmitField('Create Track')
