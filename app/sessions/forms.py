from flask_wtf import FlaskForm
from flask_wtf.file import FileField, FileAllowed
from wtforms import StringField, SelectField, SubmitField, DateField, TimeField, HiddenField
from wtforms.validators import DataRequired, Optional


class SessionEditForm(FlaskForm):
    date = DateField('Date', validators=[DataRequired()])
    track_id = SelectField('Track', coerce=int, validators=[DataRequired()])
    session_start = TimeField('Session Start', validators=[Optional()])
    team_id = SelectField('Team (optional)', coerce=int, validators=[Optional()])
    labels = HiddenField('Labels', default='[]')
    submit = SubmitField('Save Changes')


class SessionCreateForm(FlaskForm):
    csv_file = FileField('Telemetry CSV', validators=[
        FileAllowed(['csv'], 'CSV files only'),
    ])
    data_source = HiddenField('Data Source', default='racechrono')
    date = DateField('Date', validators=[DataRequired()])
    track_id = SelectField('Track', coerce=int, validators=[DataRequired()])
    session_start = TimeField('Session Start', validators=[Optional()])
    team_id = SelectField('Team (optional)', coerce=int, validators=[Optional()])
    labels = HiddenField('Labels', default='[]')
    submit = SubmitField('Upload & Process')
