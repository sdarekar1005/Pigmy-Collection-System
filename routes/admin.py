from flask import Blueprint, jsonify
from flask_login import login_required

admin_bp = Blueprint("admin", __name__)


@admin_bp.route("/api/admin/overview")
@login_required
def admin_overview():
    from flask_login import current_user

    if current_user.role != "ADMIN":
        return jsonify({"success": False, "error": "Forbidden"}), 403

    return jsonify({"success": True, "data": {"overview": {"agents": 0}}})
