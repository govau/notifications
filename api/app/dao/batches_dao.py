import uuid

from app import db
from app.models import Batch


def dao_get_batch_by_id(batch_id):
    return Batch.query.filter_by(id=batch_id).one()


def dao_get_batches_by_service_id(service_id):
    return Batch.query.filter_by(service_id=service_id).order_by(Batch.created_at.desc()).all()


def dao_get_batches_by_reference(reference):
    return Batch.query.filter_by(client_reference=reference).order_by(Batch.created_at.desc()).all()


def dao_create_batch(batch):
    if not batch.id:
        batch.id = uuid.uuid4()
    db.session.add(batch)
    db.session.commit()


def dao_update_batch(batch):
    db.session.add(batch)
    db.session.commit()
