from flask_wtf import FlaskForm
from wtforms import StringField, SubmitField
from wtforms.validators import DataRequired, Email, Length


class TeamForm(FlaskForm):
    name = StringField('Team Name', validators=[DataRequired(), Length(max=100)])
    submit = SubmitField('Create Team')


class AddMemberForm(FlaskForm):
    email = StringField('Member Email', validators=[DataRequired(), Email()])
    submit = SubmitField('Add Member')
