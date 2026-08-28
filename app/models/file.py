from sqlalchemy import Column , String ,  Integer ,DateTime, func, ForeignKey , Boolean,text
from datetime import datetime , timezone
from sqlalchemy.orm import relationship
from app.database import Base
class File(Base):
    __tablename__ = "files"
    id = Column(Integer , primary_key=True , index = True)
    patient_id = Column(Integer , ForeignKey("patients.id"),index=True , nullable=False)
    file_type = Column(String , nullable=False)
    file_name = Column(String , nullable=False)
    file_path = Column(String , nullable=False)
    uploaded_by_id = Column(Integer , ForeignKey("users.id") , nullable=False)
    is_active = Column(Boolean , server_default=text('true') , nullable=False)
    invalidation_reason = Column(String , nullable=True)
    invalidated_by_id = Column(Integer , ForeignKey("users.id") , nullable=True)
    invalidated_at = Column(DateTime(timezone=True) , nullable=True)
    created_at = Column(DateTime(timezone=True) , server_default=func.now(), default= lambda: datetime.now(timezone.utc))
    patient = relationship("Patient" , back_populates="files")
    uploaded_by = relationship("User" , foreign_keys=[uploaded_by_id])
    invalidated_by = relationship("User" , foreign_keys=[invalidated_by_id])
    file_hash = relationship("FileHash", back_populates="file", uselist=False)
    @property
    def verified_at(self):
        return self.file_hash.verified_at if self.file_hash else None
    
class FileHash(Base):
    __tablename__ = "file_hashes"
    id = Column(Integer , primary_key=True , index=True)
    file_id = Column(Integer , ForeignKey("files.id"),unique=True , nullable=False)
    hash_value = Column(String , nullable=False)
    created_at = Column(DateTime(timezone=True) , server_default=func.now(), default=lambda: datetime.now(timezone.utc))
    verified_at = Column(DateTime(timezone=True) , nullable=True)
    file = relationship("File" , back_populates="file_hash")

