from app.models.audit_log import AuditLog
from sqlalchemy.orm import Session
import logging

logger = logging.getLogger(__name__)

def log_action(
    user_id,
    action: str,
    entity_type: str,
    entity_id: int,
    result: str,
    ip_address: str,
    db: Session,
) -> None:
    new_log = AuditLog(
        user_id=user_id,
        action=action,
        entity_type=entity_type,
        entity_id=entity_id,
        result=result,
        ip_address=ip_address,
    )
    try:
        db.add(new_log)
        db.commit()
    except Exception:
        db.rollback()
        logger.error(
            "Failed to write audit log: user_id=%s action=%s entity_type=%s entity_id=%s",
            user_id, action, entity_type, entity_id
        )