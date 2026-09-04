from app.database import Base
from sqlalchemy import String, Column, Integer, DateTime, ForeignKey, Float,Index,CheckConstraint, func
from datetime import datetime , timezone
from sqlalchemy.orm import relationship

class NursingNote(Base):
    __tablename__="nursing_notes"
    id = Column(Integer , primary_key=True , index=True)
    patient_id = Column(Integer, ForeignKey("patients.id"), index= True, nullable=False)
    nursing_by_id = Column(Integer, ForeignKey("users.id") , nullable=False)
    care_notes = Column(String , nullable=False)
    blood_pressure = Column(String , nullable=True)
    heart_rate = Column(Integer , nullable=True)
    respiratory_rate = Column(Integer , nullable=True)
    pain_level= Column(Integer , nullable=True)
    temperature_celsius = Column(Float , nullable = True)
    oxygen_saturation = Column(Integer , nullable = True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), default=lambda: datetime.now(timezone.utc))
    nursing_by = relationship("User" , foreign_keys=[nursing_by_id])
    patient = relationship("Patient", back_populates="nursing_notes")

    __table_args__ = (
        CheckConstraint('pain_level >= 0 AND pain_level <= 10', name='pain_level_range'),
        CheckConstraint('heart_rate >= 0 AND heart_rate <= 300', name='heart_rate_range'),
        CheckConstraint('respiratory_rate >= 0 AND respiratory_rate <= 60', name='respiratory_rate_range'),
        CheckConstraint('oxygen_saturation >= 0 AND oxygen_saturation <= 100', name='spo2_range'),
        CheckConstraint('temperature_celsius >= 25 AND temperature_celsius <= 45', name='temp_range'),
    )