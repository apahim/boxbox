from flask_wtf import FlaskForm
from flask_wtf.file import FileField, FileRequired, FileAllowed
from wtforms import StringField, FloatField, IntegerField, SelectField, SubmitField, DateField, TimeField
from wtforms.validators import DataRequired, Optional


class SessionEditForm(FlaskForm):
    date = DateField('Date', validators=[DataRequired()])
    track_id = SelectField('Track', coerce=int, validators=[DataRequired()])
    kart_number = IntegerField('Kart Number', validators=[Optional()])
    driver_weight_kg = FloatField('Driver Weight (kg)', validators=[Optional()])
    session_type = StringField('Session Type', validators=[Optional()])
    session_start = TimeField('Session Start', validators=[Optional()])
    team_id = SelectField('Team (optional)', coerce=int, validators=[Optional()])
    submit = SubmitField('Save Changes')


class SessionCreateForm(FlaskForm):
    csv_file = FileField('Telemetry CSV', validators=[
        FileRequired(),
        FileAllowed(['csv'], 'CSV files only'),
    ])
    date = DateField('Date', validators=[DataRequired()])
    track_id = SelectField('Track', coerce=int, validators=[DataRequired()])
    kart_number = IntegerField('Kart Number', validators=[Optional()])
    driver_weight_kg = FloatField('Driver Weight (kg)', validators=[Optional()])
    session_type = StringField('Session Type', validators=[Optional()])
    session_start = TimeField('Session Start', validators=[Optional()])
    team_id = SelectField('Team (optional)', coerce=int, validators=[Optional()])
    submit = SubmitField('Upload & Process')
