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

@app.post("/herd/", response_model=schemas.Animal)
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
    
    # Resolve dam_tag_id to dam_id if provided
    dam_id = None
    if animal.dam_tag_id:
        dam_stmt = select(models.Animal).filter(
            models.Animal.farm_id == user.id,
            models.Animal.tag_id == animal.dam_tag_id
        )
        dam_result = await db.execute(dam_stmt)
        dam_animal = dam_result.scalars().first()
        if not dam_animal:
            raise HTTPException(
                status_code=400,
                detail=f"Mother Tag '{animal.dam_tag_id}' not found in your farm"
            )
        dam_id = dam_animal.id
    
    # Generate unique SRA ID
    sra_id = generate_sra_id(animal.species.value)
    
    # Ensure SRA ID is unique (retry if collision)
    for _ in range(5):
        check_stmt = select(models.Animal).filter(models.Animal.sra_id == sra_id)
        check_result = await db.execute(check_stmt)
        if not check_result.scalars().first():
            break
        sra_id = generate_sra_id(animal.species.value)
    
    # Determine initial status
    if animal.status:
        initial_status = animal.status
    elif animal.gender.value == "Male":
        initial_status = "Calf" # Default for male if unlocked status not provided
    else:
        # Female: default to Heifer (young female) or Calf based on age
        initial_status = "Heifer"
    
    new_animal = models.Animal(
        farm_id=user.id,
        tag_id=animal.tag_id,
        sra_id=sra_id,
        species=animal.species.value,
        breed=animal.breed,
        gender=animal.gender.value,
        dob=animal.dob,
        origin=animal.origin.value,
        status=initial_status,
        purchase_price=animal.purchase_price if animal.origin.value == "Purchased" else None,
        # Genealogy
        dam_id=dam_id,
        dam_label=animal.dam_label,
        sire_label=animal.sire_label,
        # Biometrics
        initial_weight=animal.weight_kg
    )
    db.add(new_animal)
    
    try:
        await db.commit()
        await db.refresh(new_animal)
        
        # Create WeightLog entry if weight provided
        if animal.weight_kg:
            weight_log = models.WeightLog(
                animal_id=new_animal.id,
                weight_kg=animal.weight_kg,
                date=dt.now().date(),
                notes="Initial Weight"
            )
            db.add(weight_log)
            await db.commit()
        
        return new_animal
    except Exception as e:
        await db.rollback()
        raise HTTPException(status_code=400, detail=str(e))

@app.get("/herd/", response_model=List[schemas.Animal])
async def get_animals(
    user: models.User = Depends(auth.get_current_user),
    db: AsyncSession = Depends(get_db)
):
    stmt = select(models.Animal).filter(models.Animal.farm_id == user.id)
    result = await db.execute(stmt)
    return result.scalars().all()

@app.delete("/herd/{animal_id}")
async def delete_animal(
    animal_id: int,
    user: models.User = Depends(auth.get_current_user),
    db: AsyncSession = Depends(get_db)
):
    # Check ownership
    stmt = select(models.Animal).filter(
        models.Animal.id == animal_id,
        models.Animal.farm_id == user.id
    )
    result = await db.execute(stmt)
    animal = result.scalar_one_or_none()
    
    if not animal:
        raise HTTPException(status_code=404, detail="Animal not found")
    
    # Clear any offspring references (set dam_id to NULL for animals that have this as parent)
    from sqlalchemy import update, delete
    
    # 1. Clear parent references in other animals
    await db.execute(
        update(models.Animal)
        .where(models.Animal.dam_id == animal_id)
        .values(dam_id=None, dam_label=f"Deleted #{animal.tag_id}")
    )
    
    # 2. Delete related WeightLogs
    await db.execute(
        delete(models.WeightLog).where(models.WeightLog.animal_id == animal_id)
    )
    
    # 3. Delete related MilkEntries
    await db.execute(
        delete(models.MilkEntry).where(models.MilkEntry.animal_id == animal_id)
    )
    
    await db.delete(animal)
    await db.commit()
    return {"message": "Animal deleted successfully"}

@app.put("/herd/{animal_id}", response_model=schemas.Animal)
async def update_animal(
    animal_id: int,
    animal_update: dict,
    user: models.User = Depends(auth.get_current_user),
    db: AsyncSession = Depends(get_db)
):
    # Check ownership
    stmt = select(models.Animal).filter(
        models.Animal.id == animal_id,
        models.Animal.farm_id == user.id
    )
    result = await db.execute(stmt)
    animal = result.scalar_one_or_none()
    
    if not animal:
        raise HTTPException(status_code=404, detail="Animal not found")
    
    # Update fields from dict (partial update)
    if 'tag_id' in animal_update:
        animal.tag_id = animal_update['tag_id']
    if 'species' in animal_update:
        animal.species = animal_update['species']
    if 'breed' in animal_update:
        animal.breed = animal_update['breed']
    if 'gender' in animal_update:
        animal.gender = animal_update['gender']
    if 'dob' in animal_update:
        from datetime import datetime
        if isinstance(animal_update['dob'], str):
            animal.dob = datetime.strptime(animal_update['dob'], '%Y-%m-%d').date()
        else:
            animal.dob = animal_update['dob']
    if 'origin' in animal_update:
        animal.origin = animal_update['origin']
    if 'status' in animal_update:
        animal.status = animal_update['status']
    if 'purchase_price' in animal_update:
        animal.purchase_price = animal_update['purchase_price']
    if 'initial_weight' in animal_update:
        animal.initial_weight = animal_update['initial_weight']
    
    await db.commit()
    await db.refresh(animal)
    return animal


@app.get("/herd/next-tag")
async def get_next_tag_id(
    user: models.User = Depends(auth.get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Get suggested next tag ID (max existing + 1)"""
    from sqlalchemy import func, cast, Integer
    
    # Get max numeric tag_id for this farm
    stmt = select(func.max(cast(models.Animal.tag_id, Integer))).filter(
        models.Animal.farm_id == user.id
    )
    result = await db.execute(stmt)
    max_tag = result.scalar()
    
    next_tag = (max_tag or 0) + 1
    return {"next_tag_id": str(next_tag)}

@app.get("/herd/search")
async def search_animals(
    q: str = "",
    gender: str = None,
    species: str = None,
    user: models.User = Depends(auth.get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Search animals by tag_id, filtered by gender and species"""
    stmt = select(models.Animal).filter(models.Animal.farm_id == user.id)
    
    if q:
        stmt = stmt.filter(models.Animal.tag_id.ilike(f"%{q}%"))
    if gender:
        stmt = stmt.filter(models.Animal.gender == gender)
    if species:
        stmt = stmt.filter(models.Animal.species == species)
    
    stmt = stmt.limit(10)
    result = await db.execute(stmt)
    animals = result.scalars().all()
    
    return [{"id": a.id, "tag_id": a.tag_id, "sra_id": a.sra_id, "species": a.species, "breed": a.breed, "gender": a.gender} for a in animals]

@app.get("/herd/validate-sra")
async def validate_sra_id(
    sra_id: str,
    gender: str,
    species: str,
    db: AsyncSession = Depends(get_db)
):
    """Validate external SRA ID for lineage - checks gender and species match"""
    stmt = select(models.Animal).filter(models.Animal.sra_id == sra_id)
    result = await db.execute(stmt)
    animal = result.scalars().first()
    
    if not animal:
        return {"valid": False, "error": "SRA ID not found"}
    
    if animal.gender != gender:
        return {"valid": False, "error": f"Gender mismatch: expected {gender}, found {animal.gender}"}
    
    if animal.species != species:
        return {"valid": False, "error": f"Species mismatch: expected {species}, found {animal.species}"}
    
    return {"valid": True, "animal": {"tag_id": animal.tag_id, "breed": animal.breed}}


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
