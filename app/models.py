from sqlalchemy import Column, Integer, String, Float, DateTime, ForeignKey, Date, Text
from sqlalchemy.orm import relationship
from datetime import datetime
from .database import Base

class SubscriptionPlan(Base):
    __tablename__ = 'subscription_plans'
    id = Column(Integer, primary_key=True)
    name = Column(String(50)) # Free, Basic, Pro
    price_pkr = Column(Float)
    max_animals = Column(Integer)

class User(Base):
    __tablename__ = 'users'
    id = Column(Integer, primary_key=True)
    firebase_uid = Column(String(128), unique=True, nullable=False)
    phone_number = Column(String(20), unique=True, nullable=False)
    role = Column(String(20)) # 'Owner', 'Manager', 'Worker'
    plan_id = Column(Integer, ForeignKey('subscription_plans.id'), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

class Animal(Base):
    __tablename__ = 'animals'
    id = Column(Integer, primary_key=True)
    farm_id = Column(Integer, ForeignKey('users.id'))
    tag_id = Column(String(50), nullable=False) # Local Visual Tag
    sra_id = Column(String(50), unique=True, nullable=False) # Global Asset ID
    species = Column(String(20)) # 'Buffalo', 'Cow', 'Goat', 'Horse', 'Camel'
    breed = Column(String(50))
    gender = Column(String(10)) # 'Male', 'Female'
    dob = Column(Date)
    origin = Column(String(20)) # 'Home_Bred', 'Purchased'
    status = Column(String(20)) # 'Milking', 'Dry', 'Heifer', 'Male'
    purchase_price = Column(Float, nullable=True) # Price if Purchased
    
    # Genealogy
    dam_id = Column(Integer, ForeignKey('animals.id'), nullable=True) # Internal mother
    dam_label = Column(String(100), nullable=True) # External mother name/tag
    sire_label = Column(String(100), nullable=True) # Father name/code
    
    # Biometrics
    initial_weight = Column(Float, nullable=True) # First recorded weight in kg
    
    # Relationships
    dam = relationship("Animal", remote_side=[id], foreign_keys=[dam_id])
    milk_entries = relationship("MilkEntry", back_populates="animal")
    weight_logs = relationship("WeightLog", back_populates="animal")

class WeightLog(Base):
    __tablename__ = 'weight_logs'
    id = Column(Integer, primary_key=True)
    animal_id = Column(Integer, ForeignKey('animals.id'), nullable=False)
    weight_kg = Column(Float, nullable=False)
    date = Column(Date, default=datetime.utcnow)
    notes = Column(Text, nullable=True) # e.g., "Initial Weight", "Monthly Check"
    
    animal = relationship("Animal", back_populates="weight_logs")

class MilkEntry(Base):
    __tablename__ = 'milk_entries'
    id = Column(Integer, primary_key=True)
    animal_id = Column(Integer, ForeignKey('animals.id'))
    liters = Column(Float, nullable=False)
    date = Column(Date, default=datetime.utcnow)
    session = Column(String(10))
    animal = relationship("Animal", back_populates="milk_entries")
