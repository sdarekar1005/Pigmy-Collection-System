from flask import Blueprint, jsonify, request
from flask_login import current_user, login_required, login_user, logout_user

from models import Agent, User, db

auth_bp = Blueprint("auth", __name__)


@auth_bp.route("/api/setup-status")
def setup_status():
    return jsonify({"success": True, "data": {"setup_required": Agent.query.count() == 0}})


@auth_bp.route("/api/setup", methods=["POST"])
def setup():
    if Agent.query.count():
        return jsonify({"success": False, "error": "Initial setup has already been completed"}), 403
    data = request.get_json(silent=True) or {}
    required = ("name", "agent_id", "mobile", "email", "password", "confirm_password")
    if any(not str(data.get(field, "")).strip() for field in required):
        return jsonify({"success": False, "error": "All setup fields are required"}), 400
    if data["password"] != data["confirm_password"] or len(data["password"]) < 8:
        return jsonify({"success": False, "error": "Passwords must match and be at least 8 characters"}), 400
    agent_id = str(data["agent_id"]).strip().upper()
    if Agent.query.filter_by(agent_id=agent_id).first():
        return jsonify({"success": False, "error": "Agent ID already exists"}), 409
    agent = Agent(agent_id=agent_id, name=str(data["name"]).strip(), mobile=str(data["mobile"]).strip(), email=str(data["email"]).strip(), status="active")
    db.session.add(agent)
    db.session.flush()
    user = User(username=agent_id.lower(), role="ADMIN", agent_id=agent.id, status="active")
    user.set_password(data["password"])
    db.session.add(user)
    db.session.commit()
    return jsonify({"success": True, "data": {"username": user.username}}), 201


@auth_bp.route("/api/login", methods=["POST"])
def login():
    payload = request.get_json(silent=True) or {}
    username = (payload.get("username") or "").strip().lower()
    password = payload.get("password") or ""

    if not username or not password:
        return jsonify({"success": False, "error": "Username and password are required"}), 400

    user = User.query.filter_by(username=username).first()
    if user is None or not user.check_password(password):
        return jsonify({"success": False, "error": "Invalid credentials"}), 401

    if user.status != "active":
        return jsonify({"success": False, "error": "User account is inactive"}), 403

    login_user(user)
    return jsonify({"success": True, "data": {"user": user.to_dict()}})


@auth_bp.route("/api/logout", methods=["POST"])
@login_required
def logout():
    logout_user()
    return jsonify({"success": True, "data": {}})


@auth_bp.route("/api/me", methods=["GET"])
@login_required
def me():
    return jsonify({"success": True, "data": {"user": current_user.to_dict()}})
