from sqlalchemy import Column , Integer, Boolean , DateTime ,func, ForeignKey , text , Index
from datetime import datetime , timezone
from sqlalchemy.orm import relationship
from app.database import Base

class PatientAssignment(Base):
    __tablename__ = "patient_assignments"
    id = Column(Integer , primary_key=True , index=True)
    patient_id = Column(Integer , ForeignKey("patients.id"), nullable=False)
    user_id = Column(Integer , ForeignKey("users.id") , nullable=False)
    assigned_by_id = Column(Integer , ForeignKey("users.id") , nullable=False)
    created_at = Column(DateTime(timezone=True) , server_default=func.now(), default= lambda: datetime.now(timezone.utc))
    is_active = Column(Boolean , server_default=text('true') , nullable=False)
    __table_args__ = (Index('ix_patient_assignments_user_patient', 'user_id', 'patient_id'),)
    patient = relationship("Patient" , back_populates="assignments")
    assigned_user = relationship("User" , foreign_keys=[user_id])
    assigned_admin = relationship("User" , foreign_keys=[assigned_by_id])