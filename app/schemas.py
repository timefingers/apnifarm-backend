from pydantic import BaseModel
from typing import Optional, List
from datetime import date, datetime
from enum import Enum

# ==================== ENUMS ====================

class SpeciesEnum(str, Enum):
    Buffalo = "Buffalo"
    Cow = "Cow"
    Goat = "Goat"
    Horse = "Horse"
    Camel = "Camel"

class GenderEnum(str, Enum):
    Male = "Male"
    Female = "Female"

class OriginEnum(str, Enum):
    Home_Bred = "Home_Bred"
    Purchased = "Purchased"

class AnimalStatusEnum(str, Enum):
    Milking = "Milking"
    Dry = "Dry"
    Heifer = "Heifer"
    Calf = "Calf"
    Bull = "Bull"

# ==================== SUBSCRIPTION PLAN ====================

class SubscriptionPlanBase(BaseModel):
    name: str
    price_pkr: float
    max_animals: int

class SubscriptionPlan(SubscriptionPlanBase):
    id: int

    class Config:
        from_attributes = True

# ==================== USER ====================

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

# ==================== ANIMAL ====================

class AnimalCreate(BaseModel):
    """Schema for creating a new animal - sra_id is auto-generated"""
    # Required fields
    tag_id: str
    species: SpeciesEnum
    breed: str
    gender: GenderEnum
    dob: date
    origin: OriginEnum
    
    # Optional fields
    purchase_price: Optional[float] = None  # Only for Purchased origin
    
    # Genealogy (optional)
    dam_tag_id: Optional[str] = None    # Internal mother's tag (will be resolved to dam_id)
    dam_label: Optional[str] = None     # External mother name/details
    sire_label: Optional[str] = None    # Father name/code
    
    # Biometrics (optional)
    weight_kg: Optional[float] = None   # Initial weight - creates WeightLog entry

class AnimalUpdate(BaseModel):
    tag_id: Optional[str] = None
    breed: Optional[str] = None
    gender: Optional[GenderEnum] = None
    status: Optional[AnimalStatusEnum] = None
    purchase_price: Optional[float] = None
    dam_label: Optional[str] = None
    sire_label: Optional[str] = None

class Animal(BaseModel):
    """Full animal response schema"""
    id: int
    farm_id: Optional[int]
    tag_id: str
    sra_id: str
    species: str
    breed: Optional[str]
    gender: Optional[str]
    dob: Optional[date]
    origin: Optional[str]
    status: Optional[str]
    purchase_price: Optional[float]
    dam_id: Optional[int]
    dam_label: Optional[str]
    sire_label: Optional[str]
    initial_weight: Optional[float]

    class Config:
        from_attributes = True

# ==================== WEIGHT LOG ====================

class WeightLogCreate(BaseModel):
    animal_id: int
    weight_kg: float
    date: Optional[date] = None
    notes: Optional[str] = None

class WeightLog(BaseModel):
    id: int
    animal_id: int
    weight_kg: float
    date: Optional[date]
    notes: Optional[str]

    class Config:
        from_attributes = True

# ==================== MILK ENTRY ====================

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
