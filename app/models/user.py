from app.database import Base
from sqlalchemy import Column , Integer ,  String , DateTime ,CheckConstraint, Boolean ,func, ForeignKey , text
from sqlalchemy.orm import relationship
from datetime import datetime , timezone

class Role(Base):
    __tablename__= "roles"
    id = Column(Integer , primary_key=True , index=True)
    dept_name = Column(String , nullable=False)
    role_name = Column(String, unique=True ,nullable=False)
    users = relationship("User", back_populates="role")


class User(Base):
    __tablename__="users"
    id = Column(Integer , primary_key=True , index=True)
    full_name = Column(String , nullable=False)
    email = Column(String , unique=True ,nullable=False)
    role_id = Column(Integer , ForeignKey("roles.id") ,index=True,nullable=False)
    specialty = Column(String , nullable=True)
    pass_hash= Column(String , nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), default=lambda: datetime.now(timezone.utc))
    __table_args__ = (
        CheckConstraint(
            "specialty IN ('General Medicine', 'Cardiology', 'Orthopedics', 'Neurology', 'Pediatrics', 'Emergency Medicine')",
            name='specialty_valid_values'
        ),
    )
    is_active = Column(Boolean , server_default=text('true') , nullable=False)
    role = relationship("Role", back_populates="users")


