from datetime import datetime

from . import db


class Collection(db.Model):
    """A recorded payment made by a customer; deliberately independent of UI state."""

    __tablename__ = "collections"

    id = db.Column(db.Integer, primary_key=True)
    customer_id = db.Column(db.Integer, db.ForeignKey("customers.id"), nullable=False, index=True)
    agent_id = db.Column(db.Integer, db.ForeignKey("agents.id"), nullable=False, index=True)
    amount = db.Column(db.Numeric(10, 2), nullable=False)
    collection_date = db.Column(db.Date, nullable=False, default=lambda: datetime.utcnow().date(), index=True)
    collection_time = db.Column(db.Time, nullable=False, default=lambda: datetime.utcnow().time())
    status = db.Column(db.String(30), nullable=False, default="completed")
    payment_method = db.Column(db.String(30), nullable=False, default="Cash")
    reference_number = db.Column(db.String(100), nullable=True)
    note = db.Column(db.String(255), nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    customer = db.relationship("Customer", backref=db.backref("collections", lazy="dynamic"))
    agent = db.relationship("Agent", backref=db.backref("collections", lazy="dynamic"))

    def to_dict(self):
        return {
            "id": self.id,
            "customer_id": self.customer_id,
            "customer_code": self.customer.customer_id if self.customer else None,
            "customer_name": self.customer.name if self.customer else None,
            "agent_id": self.agent_id,
            "agent_name": self.agent.name if self.agent else None,
            "amount": float(self.amount),
            "collection_date": self.collection_date.isoformat(),
            "status": self.status,
            "payment_method": self.payment_method,
            "reference_number": self.reference_number,
            "collection_time": self.collection_time.strftime("%H:%M:%S") if self.collection_time else self.created_at.strftime("%H:%M:%S"),
            "note": self.note,
            "notes": self.note,
            "created_at": self.created_at.isoformat(),
        }
