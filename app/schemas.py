from pydantic import BaseModel
from typing import Optional, List
from datetime import date, datetime

# Subscription Plan
class SubscriptionPlanBase(BaseModel):
    name: str
    price_pkr: float
    max_animals: int

class SubscriptionPlan(SubscriptionPlanBase):
    id: int

    class Config:
        from_attributes = True

# User
class UserCreate(BaseModel):
    phone_number: str

class UserUpdate(BaseModel):
    role: Optional[str] = None
    plan_id: Optional[int] = None

class User(BaseModel):
    id: int
    firebase_uid: str
    phone_number: str
    role: Optional[str]
    plan_id: Optional[int]
    created_at: datetime
    
    class Config:
        from_attributes = True

# Animal
class AnimalBase(BaseModel):
    tag_id: str
    sra_id: str
    species: Optional[str] = None
    breed: Optional[str] = None
    dob: Optional[date] = None
    origin: Optional[str] = None # 'Home_Bred', 'Purchased'
    status: Optional[str] = None # 'Milking', 'Dry', 'Heifer'

class AnimalCreate(AnimalBase):
    pass

class AnimalUpdate(AnimalBase):
    tag_id: Optional[str] = None
    sra_id: Optional[str] = None

class Animal(AnimalBase):
    id: int
    farm_id: Optional[int]

    class Config:
        from_attributes = True

# Milk Entry
class MilkEntryBase(BaseModel):
    liters: float
    date: Optional[date] = None
    session: Optional[str] = None

class MilkEntryCreate(MilkEntryBase):
    animal_id: int

class MilkEntry(MilkEntryBase):
    id: int
    animal_id: int

    class Config:
        from_attributes = True
