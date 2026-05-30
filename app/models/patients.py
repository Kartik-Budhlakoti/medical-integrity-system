from sqlalchemy import Column , Integer, Float , String , Boolean , DateTime
from datetime import datetime , timezone 
from sqlalchemy.orm import relationship
from app.database import Base

class Patient(Base):
    __tablename__="patients"
    id = Column(Integer, primary_key=True , index=True)
    name = Column(String , nullable=False)
    height = Column(Float , nullable=False)
    weight = Column(Float , nullable=False)
    dob = Column(DateTime , nullable=False)
    chief_complaint = Column(String , nullable=False)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    is_admitted = Column(Boolean , default=True)
    is_emergency = Column(Boolean , default=False)
    assignments = relationship("PatientAssignment", back_populates="patient")
    files = relationship("File", back_populates="patient")
    treatment_notes = relationship("TreatmentNote", back_populates="patient")