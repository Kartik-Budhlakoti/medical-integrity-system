from sqlalchemy import Column , String ,  Integer ,DateTime, ForeignKey , Boolean
from datetime import datetime , timezone
from sqlalchemy.orm import relationship
from app.database import Base
class File(Base):
    __tablename__ = "files"
    id = Column(Integer , primary_key=True , index = True)
    patient_id = Column(Integer , ForeignKey("patients.id") , nullable=False)
    file_type = Column(String , nullable=False)
    file_name = Column(String , nullable=False)
    file_path = Column(String , nullable=False)
    uploaded_by_id = Column(Integer , ForeignKey("users.id") , nullable=False)
    is_active = Column(Boolean , default = True)
    invalidation_reason = Column(String , nullable=True)
    invalidated_by_id = Column(Integer , ForeignKey("users.id") , nullable=True)
    invalidated_at = Column(DateTime , nullable=True)
    created_at = Column(DateTime , default= lambda: datetime.now(timezone.utc))
    patient = relationship("Patient" , back_populates="files")
    uploaded_by = relationship("User" , foreign_keys=[uploaded_by_id])
    invalidated_by = relationship("User" , foreign_keys=[invalidated_by_id])
    file_hash = relationship("FileHash", back_populates="file", uselist=False)

class FileHash(Base):
    __tablename__ = "file_hashes"
    id = Column(Integer , primary_key=True , index=True)
    file_id = Column(Integer , ForeignKey("files.id") , nullable=False)
    hash_value = Column(String , nullable=False)
    created_at = Column(DateTime , default=lambda: datetime.now(timezone.utc))
    verified_at = Column(DateTime , nullable=True)
    file = relationship("File" , back_populates="file_hash")
