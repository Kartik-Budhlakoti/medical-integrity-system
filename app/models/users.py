from app.database import Base
from sqlalchemy import Column , Integer , String , DateTime , Boolean , ForeignKey
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
    role_id = Column(Integer , ForeignKey("roles.id") ,nullable=False)
    pass_hash= Column(String , nullable=False)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    is_active = Column(Boolean , default=True)
    role = relationship("Role", back_populates="users")

