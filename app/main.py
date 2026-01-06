from fastapi import FastAPI, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from typing import List
from . import models, schemas, database, auth
from .database import engine

from fastapi.middleware.cors import CORSMiddleware

app = FastAPI(title="ApniFarm API", version="2.0.0")

# CORS Configuration
origins = ["*"]  # Allow all origins for development
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Database Dependency
get_db = database.get_db

@app.on_event("startup")
async def startup():
    # In production, use migrations (Alembic). For this setup, auto-create.
    async with engine.begin() as conn:
        await conn.run_sync(models.Base.metadata.create_all)

@app.get("/health")
def health_check():
    return {"status": "ok", "version": "2.0.0"}

# --- Users ---
@app.post("/users/", response_model=schemas.User)
async def create_user(
    user_data: schemas.UserCreate,
    token_data: dict = Depends(auth.verify_firebase_token),
    db: AsyncSession = Depends(get_db)
):
    firebase_uid = token_data["uid"]
    
    # Check if user exists
    stmt = select(models.User).filter(models.User.firebase_uid == firebase_uid)
    result = await db.execute(stmt)
    existing_user = result.scalars().first()
    
    if existing_user:
        return existing_user

    # Create new user
    new_user = models.User(
        firebase_uid=firebase_uid,
        phone_number=user_data.phone_number,
        role="Owner", # Default role
        plan_id=1 # Default to Free plan (id=1 assumed from seed)
    )
    db.add(new_user)
    await db.commit()
    await db.refresh(new_user)
    return new_user

@app.get("/users/me", response_model=schemas.User)
async def get_current_user_profile(
    user: models.User = Depends(auth.get_current_user),
):
    return user

# --- Auth Sync ---
@app.post("/api/auth/sync")
async def sync_user(
    token_data: dict = Depends(auth.verify_firebase_token),
    db: AsyncSession = Depends(get_db)
):
    firebase_uid = token_data["uid"]
    phone_number = token_data.get("phone_number")
    
    # Check if user exists
    stmt = select(models.User).filter(models.User.firebase_uid == firebase_uid)
    result = await db.execute(stmt)
    existing_user = result.scalars().first()
    
    if existing_user:
        return {"status": "synced", "user_id": existing_user.id, "new": False}

    # Create new user
    new_user = models.User(
        firebase_uid=firebase_uid,
        phone_number=phone_number,
        role="Owner", 
        plan_id=1 # Default to Free plan
    )
    db.add(new_user)
    try:
        await db.commit()
        await db.refresh(new_user)
        return {"status": "synced", "user_id": new_user.id, "new": True}
    except Exception as e:
        await db.rollback()
        raise HTTPException(status_code=500, detail=f"Failed to create user: {str(e)}")

# --- Subscription Plans ---
@app.get("/plans/", response_model=List[schemas.SubscriptionPlan])
async def get_plans(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(models.SubscriptionPlan))
    return result.scalars().all()

# --- Animals ---
import string
import random
from datetime import datetime as dt

def generate_sra_id(species: str) -> str:
    """Generate unique SRA ID: PK-{SPECIES_CODE}-{YEAR}-{RANDOM_4}"""
    species_codes = {
        "Buffalo": "BUF",
        "Cow": "COW",
        "Goat": "GOA",
        "Horse": "HOR",
        "Camel": "CAM",
    }
    code = species_codes.get(species, "ANI")
    year = dt.now().year
    random_chars = ''.join(random.choices(string.ascii_uppercase + string.digits, k=4))
    return f"PK-{code}-{year}-{random_chars}"

@app.post("/animals/", response_model=schemas.Animal)
async def create_animal(
    animal: schemas.AnimalCreate,
    user: models.User = Depends(auth.get_current_user),
    db: AsyncSession = Depends(get_db)
):
    # Check if tag_id already exists for this farm
    stmt = select(models.Animal).filter(
        models.Animal.farm_id == user.id,
        models.Animal.tag_id == animal.tag_id
    )
    result = await db.execute(stmt)
    if result.scalars().first():
        raise HTTPException(
            status_code=400, 
            detail="Tag ID already exists for this farm"
        )
    
    # Generate unique SRA ID
    sra_id = generate_sra_id(animal.species.value)
    
    # Ensure SRA ID is unique (retry if collision)
    for _ in range(5):
        check_stmt = select(models.Animal).filter(models.Animal.sra_id == sra_id)
        check_result = await db.execute(check_stmt)
        if not check_result.scalars().first():
            break
        sra_id = generate_sra_id(animal.species.value)
    
    # Determine initial status based on species
    # For milking animals (Buffalo, Cow, Goat, Camel) - default to Heifer
    # For non-milking (Horse) - default to Male
    milking_species = ["Buffalo", "Cow", "Goat", "Camel"]
    initial_status = "Heifer" if animal.species.value in milking_species else "Male"
    
    new_animal = models.Animal(
        farm_id=user.id,
        tag_id=animal.tag_id,
        sra_id=sra_id,
        species=animal.species.value,
        breed=animal.breed,
        dob=animal.dob,
        origin=animal.origin.value,
        status=initial_status,
        purchase_price=animal.purchase_price if animal.origin.value == "Purchased" else None
    )
    db.add(new_animal)
    try:
        await db.commit()
        await db.refresh(new_animal)
        return new_animal
    except Exception as e:
        await db.rollback()
        raise HTTPException(status_code=400, detail=str(e))

@app.get("/animals/", response_model=List[schemas.Animal])
async def get_animals(
    user: models.User = Depends(auth.get_current_user),
    db: AsyncSession = Depends(get_db)
):
    stmt = select(models.Animal).filter(models.Animal.farm_id == user.id)
    result = await db.execute(stmt)
    return result.scalars().all()

# --- Milk Entries ---
@app.post("/milk/", response_model=schemas.MilkEntry)
async def add_milk_entry(
    entry: schemas.MilkEntryCreate,
    user: models.User = Depends(auth.get_current_user),
    db: AsyncSession = Depends(get_db)
):
    # Verify animal belongs to user
    stmt = select(models.Animal).filter(models.Animal.id == entry.animal_id, models.Animal.farm_id == user.id)
    result = await db.execute(stmt)
    animal = result.scalars().first()
    if not animal:
        raise HTTPException(status_code=404, detail="Animal not found")

    new_entry = models.MilkEntry(**entry.dict())
    db.add(new_entry)
    await db.commit()
    await db.refresh(new_entry)
    return new_entry

@app.get("/milk/{animal_id}", response_model=List[schemas.MilkEntry])
async def get_milk_history(
    animal_id: int,
    user: models.User = Depends(auth.get_current_user),
    db: AsyncSession = Depends(get_db)
):
     # Verify animal belongs to user
    stmt = select(models.Animal).filter(models.Animal.id == animal_id, models.Animal.farm_id == user.id)
    result = await db.execute(stmt)
    animal = result.scalars().first()
    if not animal:
        raise HTTPException(status_code=404, detail="Animal not found")
        
    stmt = select(models.MilkEntry).filter(models.MilkEntry.animal_id == animal_id)
    result = await db.execute(stmt)
    return result.scalars().all()
