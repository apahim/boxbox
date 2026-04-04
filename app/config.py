import os


class Config:
    SECRET_KEY = os.environ.get('SECRET_KEY', 'dev-secret-change-me')
    SQLALCHEMY_DATABASE_URI = os.environ.get('DATABASE_URL', 'sqlite:///kart.db')
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    MAPKIT_TOKEN = os.environ.get('MAPKIT_TOKEN', '')
    MAX_CONTENT_LENGTH = 150 * 1024 * 1024  # 150MB upload limit


class TestingConfig(Config):
    TESTING = True
    SQLALCHEMY_DATABASE_URI = 'sqlite:///:memory:'
    WTF_CSRF_ENABLED = False
    SECRET_KEY = 'test-secret'
    MAPKIT_TOKEN = 'test-token'  # skip validation in tests
