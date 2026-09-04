import os

from dotenv import load_dotenv
from flask import Flask, jsonify
from flask_login import LoginManager
from sqlalchemy import inspect, text

from config import Config
from models import Agent, User, db
from routes.admin import admin_bp
from routes.auth import auth_bp
from routes.dashboard import dashboard_bp
from routes.operations import operations_bp

load_dotenv()

login_manager = LoginManager()
login_manager.login_view = "auth.login"
login_manager.session_protection = "strong"


@login_manager.unauthorized_handler
def unauthorized_handler():
    return jsonify({"success": False, "error": "Unauthorized"}), 401


@login_manager.user_loader
def load_user(user_id):
    return db.session.get(User, int(user_id))


def apply_safe_schema_updates():
    """Add optional profile/payment columns for pre-existing SQLite databases."""
    inspector = inspect(db.engine)
    additions = {"agents": {"email": "VARCHAR(120)", "address": "VARCHAR(255)", "profile_photo": "VARCHAR(255)", "updated_at": "DATETIME"}, "customers": {"collection_frequency": "VARCHAR(20) DEFAULT 'daily'", "deleted_at": "DATETIME"}, "collections": {"collection_time": "TIME DEFAULT '00:00:00'", "payment_method": "VARCHAR(30) DEFAULT 'Cash'", "reference_number": "VARCHAR(100)", "updated_at": "DATETIME"}}
    for table, columns in additions.items():
        if table not in inspector.get_table_names():
            continue
        existing = {column["name"] for column in inspector.get_columns(table)}
        for column, sql_type in columns.items():
            if column not in existing:
                db.session.execute(text(f"ALTER TABLE {table} ADD COLUMN {column} {sql_type}"))
    db.session.commit()

def create_app(test_config=None):
    app = Flask(__name__, template_folder="templates", static_folder="static")
    app.config.from_object(Config)

    if test_config:
        app.config.update(test_config)

    db.init_app(app)
    os.makedirs(app.config["UPLOAD_FOLDER"], exist_ok=True)
    login_manager.init_app(app)
    app.db = db

    app.register_blueprint(auth_bp)
    app.register_blueprint(dashboard_bp)
    app.register_blueprint(operations_bp)
    app.register_blueprint(admin_bp)

    @app.route("/health")
    def health():
        return {"status": "ok"}

    @app.errorhandler(401)
    def unauthorized(error):
        return jsonify({"success": False, "error": "Unauthorized"}), 401

    @app.errorhandler(403)
    def forbidden(error):
        return jsonify({"success": False, "error": "Forbidden"}), 403

    @app.errorhandler(404)
    def not_found(error):
        return jsonify({"success": False, "error": "Not found"}), 404

    @app.errorhandler(400)
    def bad_request(error):
        return jsonify({"success": False, "error": "Bad request"}), 400

    with app.app_context():
        db.create_all()
        apply_safe_schema_updates()

    return app


if __name__ == "__main__":
    app = create_app()
    app.run(debug=os.getenv("FLASK_DEBUG", "false").lower() == "true", host="0.0.0.0", port=5000)

app = create_app()
