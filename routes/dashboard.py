from datetime import date, timedelta

from flask import Blueprint, jsonify, render_template
from flask_login import current_user, login_required
from decimal import Decimal

from sqlalchemy import func

from models import Collection, Customer

dashboard_bp = Blueprint("dashboard", __name__)


@dashboard_bp.route("/")
def index():
    return render_template("index.html")


@dashboard_bp.route("/api/dashboard")
@login_required
def dashboard():
    today = date.today()
    week_start = today - timedelta(days=today.weekday())
    customers = Customer.query
    records = Collection.query
    if current_user.role != "ADMIN" and current_user.agent_id:
        customers = customers.filter(Customer.assigned_agent_id == current_user.agent_id)
        records = records.filter(Collection.agent_id == current_user.agent_id)
    scoped_customers = customers.all()
    active_customers_list = [customer for customer in scoped_customers if (customer.status or "").lower() == "active"]
    due_customers = [customer for customer in active_customers_list if customer.is_due_on(today)]
    successful_today = records.filter(Collection.collection_date == today, func.lower(Collection.status) == "completed")
    today_total = successful_today.with_entities(func.coalesce(func.sum(Collection.amount), 0)).scalar()
    successful_records = records.filter(func.lower(Collection.status) == "completed")
    total_collection = successful_records.with_entities(func.coalesce(func.sum(Collection.amount), 0)).scalar()
    today_count = successful_today.count()
    week_total = successful_records.filter(Collection.collection_date.between(week_start, today)).with_entities(func.coalesce(func.sum(Collection.amount), 0)).scalar()
    month_total = successful_records.filter(Collection.collection_date.between(today.replace(day=1), today)).with_entities(func.coalesce(func.sum(Collection.amount), 0)).scalar()
    paid_customer_ids = {row[0] for row in successful_today.with_entities(Collection.customer_id).distinct()}
    collected_by_customer = {row[0]: Decimal(row[1] or 0) for row in successful_today.with_entities(Collection.customer_id, func.sum(Collection.amount)).group_by(Collection.customer_id).all()}
    pending_customers = [customer for customer in due_customers if collected_by_customer.get(customer.id, Decimal("0")) < Decimal(customer.daily_amount)]
    pending_amount = sum((max(Decimal(customer.daily_amount) - collected_by_customer.get(customer.id, Decimal("0")), Decimal("0")) for customer in pending_customers), Decimal("0"))
    daily_target = sum((Decimal(customer.daily_amount) for customer in due_customers), Decimal("0"))
    recent = successful_records.order_by(Collection.collection_date.desc(), Collection.id.desc()).limit(8).all()
    return jsonify({"success": True, "data": {"user": current_user.to_dict(), "summary": {
        "total_customers": len(scoped_customers), "active_customers": len(active_customers_list), "today_collection": float(today_total or 0),
        "total_collection": float(total_collection or 0), "pending_amount": float(pending_amount), "today_count": today_count,
        "customers_expected": len(due_customers), "customers_collected": len(paid_customer_ids), "pending_customers": len(pending_customers),
        "week_collection": float(week_total or 0), "month_collection": float(month_total or 0), "daily_target": float(daily_target),
        "collection_progress": round((float(today_total) / float(daily_target) * 100) if daily_target else 0, 1)}, "recent_collections": [item.to_dict() for item in recent]}})
