from app.database import Base
from sqlalchemy import String, Column , Integer , DateTime, ForeignKey
from datetime import datetime , timezone
from sqlalchemy.orm import relationship

class TreatmentNote(Base):
    __tablename__="treatment_notes"
    id = Column(Integer , primary_key=True , index=True)
    patient_id = Column(Integer, ForeignKey("patients.id") , nullable=False)
    treatment_by_id = Column(Integer, ForeignKey("users.id") , nullable=False)
    completed_procedures = Column(String , nullable=True)
    ongoing_treatments = Column(String, nullable=True)
    condition_update = Column(String , nullable=False)
    medications = Column(String , nullable=False)
    observations = Column(String , nullable=True)
    orders = Column(String , nullable=False)
    created_at = Column(DateTime , default=lambda: datetime.now(timezone.utc))
    treatment_by = relationship("User" , foreign_keys=[treatment_by_id])
    patient = relationship("Patient", back_populates="treatment_notes")