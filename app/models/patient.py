from sqlalchemy import Column , Integer, Float , String , Boolean , Date , DateTime , text
from datetime import datetime , timezone 
from sqlalchemy.orm import relationship
from app.database import Base

class Patient(Base):
    __tablename__="patients"
    id = Column(Integer, primary_key=True , index=True)
    full_name = Column(String , nullable=False)
    height = Column(Float , nullable=False)
    weight = Column(Float , nullable=False)
    dob = Column(Date, nullable=False)
    chief_complaint = Column(String , nullable=False)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    is_admitted = Column(Boolean , server_default=text('false') , nullable=False)
    is_emergency = Column(Boolean , server_default=text('false') , nullable=False)
    assignments = relationship("PatientAssignment", back_populates="patient")
    files = relationship("File", back_populates="patient")
    treatment_notes = relationship("TreatmentNote", back_populates="patient")