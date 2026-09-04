from datetime import datetime

from . import db


class Customer(db.Model):
    __tablename__ = "customers"

    id = db.Column(db.Integer, primary_key=True)
    customer_id = db.Column(db.String(50), unique=True, nullable=False)
    name = db.Column(db.String(150), nullable=False)
    address = db.Column(db.String(255), nullable=False)
    mobile = db.Column(db.String(20), nullable=False)
    daily_amount = db.Column(db.Numeric(10, 2), nullable=False)
    collection_frequency = db.Column(db.String(20), nullable=False, default="daily")
    assigned_agent_id = db.Column(db.Integer, db.ForeignKey("agents.id"), nullable=False)
    status = db.Column(db.String(30), nullable=False, default="active")
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)
    deleted_at = db.Column(db.DateTime, nullable=True)

    def is_due_on(self, day):
        frequency = (self.collection_frequency or "daily").lower()
        if frequency == "weekly":
            return self.created_at.weekday() == day.weekday()
        if frequency == "monthly":
            return self.created_at.day == day.day
        return frequency == "daily"

    def to_dict(self):
        return {
            "id": self.id,
            "customer_id": self.customer_id,
            "name": self.name,
            "address": self.address,
            "mobile": self.mobile,
            "daily_amount": float(self.daily_amount),
            "collection_frequency": self.collection_frequency,
            "assigned_agent_id": self.assigned_agent_id,
            "status": self.status,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "deleted_at": self.deleted_at.isoformat() if self.deleted_at else None,
        }
