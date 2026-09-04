from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from io import BytesIO

import os
import uuid

from flask import Blueprint, current_app, jsonify, request, send_file
from werkzeug.utils import secure_filename
from flask_login import current_user, login_required
from sqlalchemy import func

from models import Agent, Collection, Customer, User, db

operations_bp = Blueprint("operations", __name__)


def _agent_scope(query, model=Customer):
    """Agents can only see their assigned customers; admins retain the full view."""
    if current_user.role != "ADMIN" and current_user.agent_id:
        return query.filter(model.assigned_agent_id == current_user.agent_id)
    return query


def _customer_or_404(customer_id, include_deleted=False):
    query = _agent_scope(Customer.query).filter(Customer.id == customer_id)
    if not include_deleted:
        query = query.filter(Customer.deleted_at.is_(None))
    return query.first_or_404()


def _is_due_on(customer, day):
    return customer.is_due_on(day)


def _customer_payload(customer, today=None):
    today = today or date.today()
    last = Collection.query.filter_by(customer_id=customer.id).order_by(Collection.collection_date.desc(), Collection.id.desc()).first()
    collected_today = Collection.query.filter_by(customer_id=customer.id, collection_date=today).filter(func.lower(Collection.status) == "completed").with_entities(func.coalesce(func.sum(Collection.amount), 0)).scalar()
    data = customer.to_dict()
    expected = Decimal(customer.daily_amount) if _is_due_on(customer, today) and customer.status.lower() == "active" else Decimal("0")
    due = max(expected - Decimal(collected_today), Decimal("0"))
    status = "collected" if expected and Decimal(collected_today) >= expected else "partial" if collected_today else "pending" if expected else "not_due"
    data.update({"last_collection": last.collection_date.isoformat() if last else None, "expected_today": float(expected),
                 "collected_today": float(collected_today), "due_amount": float(due), "collection_status": status})
    return data


def _end_of_day_data(day, include_rows=False):
    records = Collection.query.filter(Collection.collection_date == day)
    if current_user.role != "ADMIN" and current_user.agent_id:
        records = records.filter(Collection.agent_id == current_user.agent_id)
    all_customers = [customer for customer in _agent_scope(Customer.query).filter(func.lower(Customer.status) == "active").order_by(Customer.name).all() if customer.is_due_on(day)]
    record_list = records.filter(func.lower(Collection.status) == "completed").order_by(
        Collection.collection_time, Collection.id
    ).all()
    totals = {}
    times = {}
    for record in record_list:
        totals[record.customer_id] = totals.get(record.customer_id, Decimal("0")) + Decimal(record.amount)
        times.setdefault(record.customer_id, record.collection_time or record.created_at.time())
    expected = sum((Decimal(customer.daily_amount) for customer in all_customers), Decimal("0"))
    actual = sum((Decimal(record.amount) for record in record_list), Decimal("0"))
    rows = [{"customer_id": customer.customer_id, "name": customer.name, "mobile": customer.mobile, "expected": float(customer.daily_amount),
             "collected": float(totals.get(customer.id, Decimal("0"))),
             "pending": float(max(Decimal(customer.daily_amount) - totals.get(customer.id, Decimal("0")), Decimal("0"))),
             "status": "collected" if totals.get(customer.id, Decimal("0")) >= Decimal(customer.daily_amount) else "partial" if totals.get(customer.id, Decimal("0")) > 0 else "pending",
             "collection_time": times[customer.id].strftime("%I:%M %p") if customer.id in times else None} for customer in all_customers]
    agent = db.session.get(Agent, current_user.agent_id) if current_user.agent_id else None
    return {"date": day.isoformat(), "agent": agent.to_dict() if agent else None, "expected_collection": float(expected),
            "total_collection": float(actual), "pending_amount": float(max(expected - actual, Decimal("0"))),
            "difference": float(actual - expected), "customers_assigned": len(all_customers),
            "customers_collected": sum(1 for row in rows if row["collected"] > 0),
            "pending_customers": sum(1 for row in rows if row["pending"] > 0),
            "pending_collections": sum(1 for row in rows if row["pending"] > 0),
            "transactions": len(record_list), "efficiency": round(float(actual / expected * 100) if expected else 0, 1),
            "average_collection": float(actual / len(record_list)) if record_list else 0,
            "first_collection": (record_list[0].collection_time or record_list[0].created_at.time()).strftime("%I:%M %p") if record_list else None,
            "last_collection": (record_list[-1].collection_time or record_list[-1].created_at.time()).strftime("%I:%M %p") if record_list else None,
            "customers": rows if include_rows else [],
            "transactions_detail": [record.to_dict() for record in record_list]}


@operations_bp.route("/api/customers", methods=["GET", "POST"])
@login_required
def customers():
    if request.method == "POST":
        data = request.get_json(silent=True) or {}
        required = ("name", "address", "mobile", "daily_amount")
        if any(not str(data.get(key, "")).strip() for key in required):
            return jsonify({"success": False, "error": "All customer fields are required"}), 400
        try:
            amount = Decimal(str(data["daily_amount"]))
        except InvalidOperation:
            return jsonify({"success": False, "error": "Daily amount must be valid"}), 400
        if amount <= 0:
            return jsonify({"success": False, "error": "Daily amount must be greater than zero"}), 400
        agent_id = current_user.agent_id or data.get("assigned_agent_id")
        if not agent_id:
            return jsonify({"success": False, "error": "An assigned agent is required"}), 400
        customer_code = str(data.get("customer_id") or "").strip().upper()
        if not customer_code:
            last_id = db.session.query(func.max(Customer.id)).scalar() or 0
            customer_code = f"PF{last_id + 1:05d}"
        frequency = (data.get("collection_frequency") or "daily").strip().lower()
        if frequency not in {"daily", "weekly", "monthly"}:
            return jsonify({"success": False, "error": "Collection frequency must be daily, weekly, or monthly"}), 400
        customer = Customer(customer_id=customer_code, name=str(data["name"]).strip(),
                            address=str(data["address"]).strip(), mobile=str(data["mobile"]).strip(),
                            daily_amount=amount, collection_frequency=frequency, assigned_agent_id=agent_id, status=data.get("status", "active"))
        db.session.add(customer)
        try:
            db.session.commit()
        except Exception:
            db.session.rollback()
            return jsonify({"success": False, "error": "Customer ID already exists"}), 409
        return jsonify({"success": True, "data": {"customer": customer.to_dict()}}), 201

    search = request.args.get("search", "").strip()
    status = request.args.get("status", "").strip().lower()
    query = _agent_scope(Customer.query).filter(Customer.deleted_at.is_(None))
    if search:
        pattern = f"%{search}%"
        query = query.filter(db.or_(Customer.customer_id.ilike(pattern), Customer.name.ilike(pattern), Customer.mobile.ilike(pattern)))
    if status:
        query = query.filter(func.lower(Customer.status) == status)
    customers = query.order_by(Customer.created_at.desc()).all()
    return jsonify({"success": True, "data": {"customers": [_customer_payload(item) for item in customers]}})


@operations_bp.route("/api/customers/<int:customer_id>", methods=["GET", "PUT", "DELETE"])
@login_required
def customer_detail(customer_id):
    customer = _customer_or_404(customer_id, include_deleted=request.method == "GET")
    if request.method == "DELETE":
        data = request.get_json(silent=True) or {}
        if (customer.status or "").lower() != "inactive":
            return jsonify({"success": False, "error": "Customer must be Inactive before deletion"}), 400
        if data.get("confirmation") != "DELETE" or not current_user.check_password(data.get("current_password") or ""):
            return jsonify({"success": False, "error": "Confirmation and current password are required"}), 403
        customer.status = "deleted"
        customer.deleted_at = datetime.utcnow()
        db.session.commit()
        return jsonify({"success": True, "data": {"message": "Customer deleted successfully. Historical records have been preserved."}})
    if request.method == "PUT":
        data = request.get_json(silent=True) or {}
        for field in ("name", "address", "mobile", "status", "collection_frequency"):
            if field in data and str(data[field]).strip():
                setattr(customer, field, str(data[field]).strip())
        if (customer.status or "").lower() not in {"active", "inactive"}:
            return jsonify({"success": False, "error": "Status must be Active or Inactive"}), 400
        customer.status = customer.status.lower()
        if "daily_amount" in data:
            try:
                amount = Decimal(str(data["daily_amount"]))
            except InvalidOperation:
                return jsonify({"success": False, "error": "Daily amount must be valid"}), 400
            if amount <= 0:
                return jsonify({"success": False, "error": "Daily amount must be greater than zero"}), 400
            customer.daily_amount = amount
        if customer.collection_frequency not in {"daily", "weekly", "monthly"}:
            return jsonify({"success": False, "error": "Collection frequency must be daily, weekly, or monthly"}), 400
        db.session.commit()
    total = db.session.query(func.coalesce(func.sum(Collection.amount), 0)).filter(Collection.customer_id == customer.id, func.lower(Collection.status) == "completed").scalar()
    history = Collection.query.filter_by(customer_id=customer.id).order_by(Collection.collection_date.desc(), Collection.id.desc()).limit(20).all()
    return jsonify({"success": True, "data": {"customer": _customer_payload(customer), "total_collected": float(total), "collections": [row.to_dict() for row in history]}})


@operations_bp.route("/api/collections", methods=["GET", "POST"])
@login_required
def collections():
    if request.method == "POST":
        data = request.get_json(silent=True) or {}
        try:
            customer = _customer_or_404(int(data.get("customer_id")))
            amount = Decimal(str(data.get("amount")))
            collection_date = datetime.strptime(data.get("collection_date") or date.today().isoformat(), "%Y-%m-%d").date()
        except (TypeError, ValueError, InvalidOperation):
            return jsonify({"success": False, "error": "Choose a customer and enter a valid amount and date"}), 400
        if amount <= 0:
            return jsonify({"success": False, "error": "Collection amount must be greater than zero"}), 400
        if (customer.status or "").lower() != "active" or customer.deleted_at is not None:
            return jsonify({"success": False, "error": "Collections can only be recorded for active customers"}), 400
        if collection_date > date.today():
            return jsonify({"success": False, "error": "Collection date cannot be in the future"}), 400
        try:
            collection_time = datetime.strptime(
                data.get("collection_time") or datetime.now().strftime("%H:%M"), "%H:%M"
            ).time()
        except ValueError:
            return jsonify({"success": False, "error": "Collection time must use HH:MM"}), 400
        record = Collection(customer_id=customer.id, agent_id=current_user.agent_id or customer.assigned_agent_id,
                            amount=amount, collection_date=collection_date, collection_time=collection_time,
                            payment_method=(data.get("payment_method") or "Cash").strip(), reference_number=(data.get("reference_number") or "").strip() or None, note=(data.get("note") or data.get("notes") or "").strip() or None)
        db.session.add(record)
        db.session.commit()
        return jsonify({"success": True, "data": {"collection": record.to_dict()}}), 201

    query = Collection.query.join(Customer)
    if current_user.role != "ADMIN" and current_user.agent_id:
        query = query.filter(Collection.agent_id == current_user.agent_id)
    search = request.args.get("search", "").strip()
    selected_date = request.args.get("date", "").strip()
    status = request.args.get("status", "").strip().lower()
    if search:
        pattern = f"%{search}%"
        query = query.filter(db.or_(Customer.customer_id.ilike(pattern), Customer.name.ilike(pattern)))
    if selected_date:
        try:
            query = query.filter(Collection.collection_date == datetime.strptime(selected_date, "%Y-%m-%d").date())
        except ValueError:
            return jsonify({"success": False, "error": "Date must use YYYY-MM-DD"}), 400
    if status:
        query = query.filter(func.lower(Collection.status) == status)
    records = query.order_by(Collection.collection_date.desc(), Collection.id.desc()).all()
    return jsonify({"success": True, "data": {"collections": [item.to_dict() for item in records]}})


@operations_bp.route("/api/reports/summary")
@login_required
def report_summary():
    today = date.today()
    try:
        start = datetime.strptime(request.args.get("start") or today.replace(day=1).isoformat(), "%Y-%m-%d").date()
        end = datetime.strptime(request.args.get("end") or today.isoformat(), "%Y-%m-%d").date()
    except ValueError:
        return jsonify({"success": False, "error": "Dates must use YYYY-MM-DD"}), 400
    if start > end:
        return jsonify({"success": False, "error": "Start date must be before end date"}), 400
    week_start = today - timedelta(days=today.weekday())
    query = Collection.query
    if current_user.role != "ADMIN" and current_user.agent_id:
        query = query.filter(Collection.agent_id == current_user.agent_id)
    successful_query = query.filter(func.lower(Collection.status) == "completed")
    def collected_between(start, end):
        return float(successful_query.filter(Collection.collection_date.between(start, end)).with_entities(func.coalesce(func.sum(Collection.amount), 0)).scalar())
    customer_totals = successful_query.join(Customer).with_entities(
        Customer.customer_id, Customer.name, func.coalesce(func.sum(Collection.amount), 0).label("total")
    ).filter(Collection.collection_date.between(start, end)).group_by(Customer.id).order_by(func.sum(Collection.amount).desc()).limit(10).all()
    transactions = successful_query.filter(Collection.collection_date.between(start, end)).count()
    return jsonify({"success": True, "data": {"today": collected_between(today, today), "week": collected_between(week_start, today), "month": collected_between(today.replace(day=1), today), "customer_totals": [
        {"customer_id": row.customer_id, "name": row.name, "amount": float(row.total)} for row in customer_totals
    ], "range_collection": collected_between(start, end), "transactions": transactions, "start": start.isoformat(), "end": end.isoformat()}})


@operations_bp.route("/api/pending")
@login_required
def pending_list():
    today = date.today()
    items = _agent_scope(Customer.query).filter(func.lower(Customer.status) == "active").order_by(Customer.name).all()
    pending = [_customer_payload(customer, today) for customer in items]
    pending = [item for item in pending if item["due_amount"] > 0]
    return jsonify({"success": True, "data": {"pending": pending, "total_due": sum(item["due_amount"] for item in pending), "as_of": today.isoformat()}})


@operations_bp.route("/api/end-of-day")
@login_required
def end_of_day():
    requested = request.args.get("date")
    try:
        day = datetime.strptime(requested, "%Y-%m-%d").date() if requested else date.today()
    except ValueError:
        return jsonify({"success": False, "error": "Date must use YYYY-MM-DD"}), 400
    return jsonify({"success": True, "data": _end_of_day_data(day, include_rows=True)})


@operations_bp.route("/api/agent-profile")
@login_required
def agent_profile():
    agent = db.session.get(Agent, current_user.agent_id) if current_user.agent_id else None
    if not agent:
        return jsonify({"success": False, "error": "No agent profile is linked to this account"}), 404
    today = date.today()
    records = Collection.query.filter_by(agent_id=agent.id)
    successful = records.filter(func.lower(Collection.status) == "completed")
    week_start = today - timedelta(days=today.weekday())
    return jsonify({"success": True, "data": {"agent": agent.to_dict(),
        "today_collection": float(successful.filter(Collection.collection_date == today).with_entities(func.coalesce(func.sum(Collection.amount), 0)).scalar()),
        "week_collection": float(successful.filter(Collection.collection_date.between(week_start, today)).with_entities(func.coalesce(func.sum(Collection.amount), 0)).scalar()),
        "month_collection": float(successful.filter(Collection.collection_date.between(today.replace(day=1), today)).with_entities(func.coalesce(func.sum(Collection.amount), 0)).scalar()),
        "total_collection": float(successful.with_entities(func.coalesce(func.sum(Collection.amount), 0)).scalar()),
        "customers_handled": Customer.query.filter_by(assigned_agent_id=agent.id).count()}})


@operations_bp.route("/api/agent-profile", methods=["PUT"])
@login_required
def update_agent_profile():
    agent = db.session.get(Agent, current_user.agent_id) if current_user.agent_id else None
    if not agent:
        return jsonify({"success": False, "error": "No agent profile is linked to this account"}), 404
    data = request.get_json(silent=True) or {}
    for field in ("name", "mobile", "email", "address"):
        if field in data:
            setattr(agent, field, str(data[field]).strip() or None)
    if not agent.name:
        return jsonify({"success": False, "error": "Agent name is required"}), 400
    db.session.commit()
    return jsonify({"success": True, "data": {"agent": agent.to_dict()}})


@operations_bp.route("/api/change-password", methods=["POST"])
@login_required
def change_password():
    data = request.get_json(silent=True) or {}
    current_password = data.get("current_password") or ""
    new_password = data.get("new_password") or ""
    if not current_user.check_password(current_password):
        return jsonify({"success": False, "error": "Current password is incorrect"}), 400
    if len(new_password) < 8:
        return jsonify({"success": False, "error": "New password must be at least 8 characters"}), 400
    current_user.set_password(new_password)
    db.session.commit()
    return jsonify({"success": True, "data": {}})


@operations_bp.route("/api/agent-profile/photo", methods=["POST"])
@login_required
def upload_profile_photo():
    agent = db.session.get(Agent, current_user.agent_id) if current_user.agent_id else None
    image = request.files.get("photo")
    if not agent or not image or not image.filename:
        return jsonify({"success": False, "error": "Choose a profile image"}), 400
    extension = os.path.splitext(secure_filename(image.filename))[1].lower()
    if extension not in {".jpg", ".jpeg", ".png", ".webp"}:
        return jsonify({"success": False, "error": "Only JPG, JPEG, PNG, and WEBP images are allowed"}), 400
    filename = f"agent-{agent.id}-{uuid.uuid4().hex}{extension}"
    image.save(os.path.join(current_app.config["UPLOAD_FOLDER"], filename))
    agent.profile_photo = f"uploads/{filename}"
    db.session.commit()
    return jsonify({"success": True, "data": {"profile_photo": agent.profile_photo}})


@operations_bp.route("/api/end-of-day/pdf")
@login_required
def end_of_day_pdf():
    try:
        day = datetime.strptime(request.args.get("date") or date.today().isoformat(), "%Y-%m-%d").date()
    except ValueError:
        return jsonify({"success": False, "error": "Date must use YYYY-MM-DD"}), 400
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.lib.units import mm
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
    data = _end_of_day_data(day, include_rows=True)
    buffer = BytesIO()
    document = SimpleDocTemplate(buffer, pagesize=A4, rightMargin=15*mm, leftMargin=15*mm, topMargin=14*mm, bottomMargin=14*mm)
    styles = getSampleStyleSheet()
    story = [Paragraph("PIGMYFLOW", styles["Title"]), Paragraph("END OF DAY COLLECTION REPORT", styles["Heading2"]), Spacer(1, 7*mm)]
    agent = data["agent"] or {}
    story.append(Paragraph(f"Date: {data['date']} &nbsp;&nbsp;&nbsp; Agent: {agent.get('name', '—')} &nbsp;&nbsp;&nbsp; Agent ID: {agent.get('agent_id', '—')}", styles["BodyText"]))
    metrics = [["Expected Collection", f"Rs. {data['expected_collection']:,.2f}"], ["Total Collected", f"Rs. {data['total_collection']:,.2f}"], ["Pending / Difference", f"Rs. {data['pending_amount']:,.2f} / Rs. {data['difference']:,.2f}"], ["Customers", f"{data['customers_collected']} collected / {data['customers_assigned']} assigned"], ["Collection Efficiency", f"{data['efficiency']}%"], ["Transactions / Average", f"{data['transactions']} / Rs. {data['average_collection']:,.2f}"]]
    summary = Table(metrics, colWidths=[72*mm, 95*mm]); summary.setStyle(TableStyle([("BACKGROUND", (0,0), (-1,0), colors.HexColor("#e7f2ef")), ("GRID", (0,0), (-1,-1), .25, colors.HexColor("#b8cdc7")), ("FONTNAME", (0,0), (0,-1), "Helvetica-Bold"), ("PADDING", (0,0), (-1,-1), 7)])); story += [Spacer(1, 5*mm), summary, Spacer(1, 7*mm), Paragraph("CUSTOMER-WISE COLLECTION", styles["Heading3"])]
    rows = [["Customer ID", "Customer", "Expected", "Collected", "Pending", "Status", "Time"]] + [[r['customer_id'], r['name'], f"Rs. {r['expected']:,.2f}", f"Rs. {r['collected']:,.2f}", f"Rs. {r['pending']:,.2f}", r['status'].title(), r['collection_time'] or "—"] for r in data['customers']]
    table = Table(rows, repeatRows=1, colWidths=[23*mm, 38*mm, 24*mm, 24*mm, 24*mm, 21*mm, 20*mm]); table.setStyle(TableStyle([("BACKGROUND", (0,0), (-1,0), colors.HexColor("#175f5a")), ("TEXTCOLOR", (0,0), (-1,0), colors.white), ("GRID", (0,0), (-1,-1), .25, colors.HexColor("#cbd8d5")), ("FONTSIZE", (0,0), (-1,-1), 7), ("PADDING", (0,0), (-1,-1), 5)])); story.append(table)
    story += [Spacer(1, 7*mm), Paragraph("TRANSACTION SUMMARY", styles["Heading3"])]
    transaction_rows = [["Time", "Customer", "Amount", "Status", "Reference", "Notes"]]
    transaction_rows += [[item["collection_time"], item["customer_name"], f"Rs. {item['amount']:,.2f}", item["status"].title(), item["reference_number"] or "—", item["note"] or "—"] for item in data["transactions_detail"]]
    transaction_table = Table(transaction_rows, repeatRows=1, colWidths=[22*mm, 40*mm, 25*mm, 23*mm, 30*mm, 35*mm]); transaction_table.setStyle(TableStyle([("BACKGROUND", (0,0), (-1,0), colors.HexColor("#175f5a")), ("TEXTCOLOR", (0,0), (-1,0), colors.white), ("GRID", (0,0), (-1,-1), .25, colors.HexColor("#cbd8d5")), ("FONTSIZE", (0,0), (-1,-1), 7), ("PADDING", (0,0), (-1,-1), 5)])); story.append(transaction_table)
    document.build(story); buffer.seek(0)
    return send_file(buffer, mimetype="application/pdf", as_attachment=True, download_name=f"pigmyflow-end-of-day-{day.isoformat()}.pdf")


@operations_bp.route("/api/export/<string:report_type>")
@login_required
def export_excel(report_type):
    """Download database-backed customer or transaction data; never imports into storage."""
    from openpyxl import Workbook
    if report_type not in {"customers", "transactions", "daily"}:
        return jsonify({"success": False, "error": "Unsupported export type"}), 400
    book, sheet = Workbook(), None
    sheet = book.active
    if report_type == "customers":
        sheet.title = "Customers"
        sheet.append(["Customer ID", "Name", "Mobile", "Daily Amount", "Frequency", "Status"])
        for customer in _agent_scope(Customer.query).order_by(Customer.name).all():
            sheet.append([customer.customer_id, customer.name, customer.mobile, float(customer.daily_amount), customer.collection_frequency, customer.status])
    else:
        selected_day = date.today() if report_type == "daily" else None
        query = Collection.query.join(Customer)
        if current_user.role != "ADMIN" and current_user.agent_id:
            query = query.filter(Collection.agent_id == current_user.agent_id)
        if selected_day:
            query = query.filter(Collection.collection_date == selected_day)
        sheet.title = "Daily Collections" if selected_day else "Transactions"
        sheet.append(["Date", "Time", "Customer", "Agent", "Amount", "Status", "Reference", "Notes"])
        for item in query.order_by(Collection.collection_date.desc(), Collection.id.desc()).all():
            sheet.append([item.collection_date.isoformat(), item.collection_time.strftime("%H:%M"), item.customer.name, item.agent.name, float(item.amount), item.status, item.reference_number or "", item.note or ""])
    output = BytesIO()
    book.save(output)
    output.seek(0)
    return send_file(output, mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", as_attachment=True, download_name=f"pigmy-{report_type}-{date.today().isoformat()}.xlsx")
