from flask_sqlalchemy import SQLAlchemy
from datetime import datetime, timezone

db = SQLAlchemy()

class JenkinsJob(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    job_name = db.Column(db.String(100), unique=True, nullable=False)
    git_repo = db.Column(db.String(200), nullable=False)
    git_user = db.Column(db.String(100), nullable=False) 
    branch = db.Column(db.String(100), nullable=False)
    email = db.Column(db.String(100), nullable=False)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    def __repr__(self):
        return f'<JenkinsJob {self.job_name}>'
