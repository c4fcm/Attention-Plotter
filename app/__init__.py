from flask import Flask
from flask_login import LoginManager
from pymongo import Connection

# Settings
config_host = 'localhost'
config_db = 'attention'
config_upload_folder = 'app/uploads'
config_allowed_extensions = ['csv']

# Flask app
app = Flask(__name__)
app.secret_key = 'put secret key here'
app.config['UPLOAD_FOLDER'] = config_upload_folder

# Create user login manager
login_manager = LoginManager()
login_manager.init_app(app)

# Connect to db
db = Connection(config_host)[config_db]

# Task statuses
def enum(**enums):
    return type('Enum', (), enums)
TaskStatus = enum(
    DISABLED = 'Disabled'
    , ENABLED = 'Enabled'
    , EXTRACTING = 'Extracting'
    , EXTRACTED = 'Extracted'
    , TRANSFORMING = 'Transforming'
    , TRANSFORMED = 'Transformed'
    , LOADING = 'Loading'
    , COMPLETE = 'Complete'
)

# Data source configuration
from app.sources.source import Source
from app.sources.csvsource import CsvSource
Source.add_sources({
    CsvSource.name: CsvSource
})

from app import views