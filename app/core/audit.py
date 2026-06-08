from app.models.audit_log import AuditLog
from sqlalchemy.orm import Session
def log_action(
        user_id,
        action : str, 
        entity_type : str, 
        entity_id: int, 
        result: str, 
        ip_address : str,
        db : Session):
    new_log = AuditLog(
        user_id = user_id,
        action = action,
        entity_type = entity_type,
        entity_id = entity_id,
        result = result,
        ip_address = ip_address       
    )
    db.add(new_log)
    db.commit()
