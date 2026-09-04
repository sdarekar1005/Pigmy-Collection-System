from flask_sqlalchemy import SQLAlchemy


db = SQLAlchemy()

from .agent import Agent
from .customer import Customer
from .collection import Collection
from .user import User

__all__ = ["db", "Agent", "Customer", "Collection", "User"]
