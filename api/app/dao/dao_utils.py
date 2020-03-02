import itertools
from functools import wraps, partial

from app import db
from app.history_meta import create_history


def transactional(func):
    @wraps(func)
    def commit_or_rollback(*args, **kwargs):
        from flask import current_app
        try:
            res = func(*args, **kwargs)
            db.session.commit()
            return res
        except Exception as e:
            current_app.logger.error(e)
            db.session.rollback()
            raise
    return commit_or_rollback


def version_class(model_class, history_cls=None):
    create_hist = partial(create_history, history_cls=history_cls)

    def versioned(func):
        @wraps(func)
        def record_version(*args, **kwargs):
            func(*args, **kwargs)
            history_objects = [create_hist(obj) for obj in
                               itertools.chain(db.session.new, db.session.dirty)
                               if isinstance(obj, model_class)]
            for h_obj in history_objects:
                db.session.add(h_obj)
        return record_version
    return versioned


def dao_rollback():
    db.session.rollback()


def is_duplicate_key_integrity_error(e):
    if hasattr(e, 'orig') and hasattr(e.orig, 'pgerror') and e.orig.pgerror \
            and ('duplicate key value violates unique constraint' in e.orig.pgerror):
        return True
    return False
