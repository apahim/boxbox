from flask_wtf import FlaskForm
from wtforms import StringField, FloatField, SubmitField
from wtforms.validators import DataRequired, Length


class TrackForm(FlaskForm):
    name = StringField('Track Name', validators=[DataRequired(), Length(max=200)])
    lat = FloatField('Latitude', validators=[DataRequired()])
    lon = FloatField('Longitude', validators=[DataRequired()])
    timezone = StringField('Timezone', default='UTC')
    submit = SubmitField('Create Track')
