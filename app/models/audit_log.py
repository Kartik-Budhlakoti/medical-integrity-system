from sqlalchemy import Column , Integer , String, DateTime , ForeignKey , Enum
from datetime import datetime , timezone
from app.database import Base
from sqlalchemy.orm import relationship

class AuditLog(Base):
    __tablename__ = "audit_logs"
    id = Column(Integer , primary_key=True , index=True)
    user_id = Column(Integer , ForeignKey("users.id") , nullable=True)
    action = Column(String , nullable=False)
    entity_type = Column(String , nullable=False)
    entity_id = Column(Integer , nullable=False)
    result = Column(Enum ("SUCCESS", "FAILURE" , name="result_enum"), nullable=False)
    ip_address = Column(String , nullable=True)
    created_at = Column(DateTime(timezone=True) , default= lambda: datetime.now(timezone.utc))
    user = relationship("User" , foreign_keys=[user_id])