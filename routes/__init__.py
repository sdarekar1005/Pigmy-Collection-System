from flask import Blueprint


def create_blueprint(name):
    return Blueprint(name, __name__)
