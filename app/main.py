from fastapi import FastAPI, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy import text, func, cast, Date, extract, distinct
from typing import List, Optional
from datetime import datetime, timedelta, date
from . import models, schemas, database, auth
from .database import engine

from fastapi.middleware.cors import CORSMiddleware

app = FastAPI(title="ApniFarm API", version="2.0.0")

# CORS Configuration
origins = [
    "http://localhost:3000",
    "http://127.0.0.1:3000",
    "http://localhost:8000",
    "http://127.0.0.1:8000"
]
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
        
        # Manual Migration for MilkEntry updates
        try:
            # Check/Add recorded_at
            await conn.execute(text("ALTER TABLE milk_entries ADD COLUMN IF NOT EXISTS recorded_at TIMESTAMP WITHOUT TIME ZONE DEFAULT NOW()"))
            await conn.execute(text("ALTER TABLE milk_entries ADD COLUMN IF NOT EXISTS fat_percentage FLOAT DEFAULT NULL"))
            await conn.execute(text("ALTER TABLE milk_entries ADD COLUMN IF NOT EXISTS quality VARCHAR(20) DEFAULT NULL"))
        except Exception as e:
            print(f"Migration warning (can be ignored if columns exist): {e}")

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
    
    return [{"id": a.id, "tag_id": a.tag_id, "sra_id": a.sra_id, "species": a.species, "breed": a.breed, "gender": a.gender, "status": a.status} for a in animals]

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

    entry_data = entry.dict()
    # Ensure 'date' is populated from 'recorded_at' (for backward compat or query simplicity)
    if entry_data.get('recorded_at') and not entry_data.get('date'):
        if isinstance(entry_data['recorded_at'], str):
             # Should be datetime object if Pydantic parsed it, but just safely:
             dt = datetime.fromisoformat(entry_data['recorded_at'].replace('Z', '+00:00'))
             entry_data['date'] = dt.date()
        else:
             entry_data['date'] = entry_data['recorded_at'].date()

    new_entry = models.MilkEntry(**entry_data)
    db.add(new_entry)
    await db.commit()
    await db.refresh(new_entry)
    return new_entry

@app.get("/milk/", response_model=List[schemas.MilkEntryResponse])
async def get_milk_entries(
    date_filter: str = None, # 'today', 'yesterday'
    start_date: date = None,
    end_date: date = None,
    animal_id: int = None,
    session: str = None,
    user: models.User = Depends(auth.get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """List milk entries with filters and animal details"""
    # Join with Animal to get tag details and filter by farm
    stmt = select(models.MilkEntry, models.Animal).join(models.Animal).filter(models.Animal.farm_id == user.id)
    
    if date_filter:
        today = datetime.utcnow().date()
        if date_filter == 'today':
            stmt = stmt.filter(models.MilkEntry.date == today)
        elif date_filter == 'yesterday':
            stmt = stmt.filter(models.MilkEntry.date == (today - timedelta(days=1)))
            
    if start_date and end_date:
        stmt = stmt.filter(models.MilkEntry.date >= start_date, models.MilkEntry.date <= end_date)
        
    if animal_id:
        stmt = stmt.filter(models.MilkEntry.animal_id == animal_id)

    if session:
        stmt = stmt.filter(models.MilkEntry.session == session)
        
    stmt = stmt.order_by(models.MilkEntry.recorded_at.desc())
    result = await db.execute(stmt)
    rows = result.all()
    
    # Construct response with animal details
    response = []
    for entry, animal in rows:
        # Pydantic model construction from ORM object
        entry_dict = {c.name: getattr(entry, c.name) for c in models.MilkEntry.__table__.columns}
        entry_dict['animal_tag_id'] = animal.tag_id
        entry_dict['animal_species'] = animal.species
        response.append(entry_dict)
        
    return response

@app.put("/milk/{entry_id}", response_model=schemas.MilkEntry)
async def update_milk_entry(
    entry_id: int,
    entry_update: schemas.MilkEntryCreate, # Re-using create schema for update
    user: models.User = Depends(auth.get_current_user),
    db: AsyncSession = Depends(get_db)
):
    # Fetch existing entry joined with Animal to verify ownership
    stmt = select(models.MilkEntry).join(models.Animal).filter(
        models.MilkEntry.id == entry_id,
        models.Animal.farm_id == user.id
    )
    result = await db.execute(stmt)
    existing_entry = result.scalars().first()
    
    if not existing_entry:
        raise HTTPException(status_code=404, detail="Milk entry not found")
        
    # Verify new animal belongs to user (if animal_id changed)
    if entry_update.animal_id != existing_entry.animal_id:
        stmt_animal = select(models.Animal).filter(models.Animal.id == entry_update.animal_id, models.Animal.farm_id == user.id)
        res_animal = await db.execute(stmt_animal)
        if not res_animal.scalars().first():
             raise HTTPException(status_code=404, detail="New animal not found")

    # Update fields
    entry_data = entry_update.dict()
    # Date logic same as create
    if entry_data.get('recorded_at'):
        if isinstance(entry_data['recorded_at'], str):
             dt = datetime.fromisoformat(entry_data['recorded_at'].replace('Z', '+00:00'))
             entry_data['date'] = dt.date()
        else:
             entry_data['date'] = entry_data['recorded_at'].date()
             
    for key, value in entry_data.items():
        setattr(existing_entry, key, value)
        
    await db.commit()
    await db.refresh(existing_entry)
    return existing_entry

@app.delete("/milk/{entry_id}")
async def delete_milk_entry(
    entry_id: int,
    user: models.User = Depends(auth.get_current_user),
    db: AsyncSession = Depends(get_db)
):
    # Verify ownership via join
    stmt = select(models.MilkEntry).join(models.Animal).filter(
        models.MilkEntry.id == entry_id,
        models.Animal.farm_id == user.id
    )
    result = await db.execute(stmt)
    entry = result.scalars().first()
    
    if not entry:
        raise HTTPException(status_code=404, detail="Milk entry not found")
        
    await db.delete(entry)
    await db.commit()
    return {"message": "Entry deleted"}

@app.get("/milk/stats", response_model=schemas.MilkStatsResponse)
async def get_milk_stats(
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
    species: Optional[str] = None,
    breed: Optional[str] = None,
    status: Optional[str] = None,
    user: models.User = Depends(auth.get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Get aggregated stats for dashboard with advanced filters"""
    
    # Base Filters
    filters = []
    filters.append(models.Animal.farm_id == user.id)
    
    if start_date:
        filters.append(models.MilkEntry.date >= start_date)
    if end_date:
        filters.append(models.MilkEntry.date <= end_date)
    else:
        # Default to last 7 days if NO date range provided? 
        # Actually client should probably provide range, but let's default if both missing.
        if not start_date:
           today = datetime.utcnow().date()
           filters.append(models.MilkEntry.date >= today - timedelta(days=6))

    if species:
        filters.append(models.Animal.species == species)
    if breed:
        filters.append(models.Animal.breed == breed)
    if status:
        filters.append(models.Animal.status == status)

    # Helper to build query
    def build_query(select_stmt):
        q = select_stmt.select_from(models.MilkEntry).join(models.Animal)
        for f in filters:
            q = q.filter(f)
        return q

    # 1. Aggregates: Total Liters & Average/Animal
    # We need total liters
    stmt_sum = build_query(select(func.sum(models.MilkEntry.liters)))
    result_sum = await db.execute(stmt_sum)
    total_liters = result_sum.scalar() or 0.0

    # Count distinct animals in this period
    stmt_count = build_query(select(func.count(distinct(models.MilkEntry.animal_id))))
    result_count = await db.execute(stmt_count)
    animal_count = result_count.scalar() or 0
    
    avg_per_animal = (total_liters / animal_count) if animal_count > 0 else 0.0

    # 2. Daily Production (Line Chart)
    stmt_daily = build_query(select(models.MilkEntry.date, func.sum(models.MilkEntry.liters)))
    stmt_daily = stmt_daily.group_by(models.MilkEntry.date).order_by(models.MilkEntry.date)
    result_daily = await db.execute(stmt_daily)
    daily_production = [{"date": r[0], "liters": r[1] or 0.0} for r in result_daily.all()]

    # 3. Aggregations (Pie Chart Data)
    species_breakdown = []
    breed_breakdown = []

    # If NO Species selected, show Species Breakdown
    if not species:
        stmt_species = build_query(select(models.Animal.species, func.sum(models.MilkEntry.liters), func.count(distinct(models.MilkEntry.animal_id))))
        stmt_species = stmt_species.group_by(models.Animal.species)
        result_species = await db.execute(stmt_species)
        species_breakdown = [
            {"label": r[0] or "Unknown", "total_liters": r[1] or 0.0, "avg_liters": (r[1]/r[2]) if r[2]>0 else 0} 
            for r in result_species.all()
        ]
    
    # If Species IS selected, show Breed Breakdown
    # (Or we can always calculate it? But usually requested behavior implies context switch)
    # The user request "When Filtered for a Species, show a breakdown... by Breed" hints conditional.
    # However, for API flexiblity, maybe providing both is fine if cheap. But cleaner to follow logic.
    if species:
        stmt_breed = build_query(select(models.Animal.breed, func.sum(models.MilkEntry.liters), func.count(distinct(models.MilkEntry.animal_id))))
        stmt_breed = stmt_breed.group_by(models.Animal.breed)
        result_breed = await db.execute(stmt_breed)
        breed_breakdown = [
            {"label": r[0] or "Unknown", "total_liters": r[1] or 0.0, "avg_liters": (r[1]/r[2]) if r[2]>0 else 0}
            for r in result_breed.all()
        ]

    # 4. Top 5 Producers (Leaderboard)
    stmt_top = build_query(select(models.Animal.tag_id, func.sum(models.MilkEntry.liters)))
    stmt_top = stmt_top.group_by(models.Animal.tag_id).order_by(func.sum(models.MilkEntry.liters).desc()).limit(5)
    result_top = await db.execute(stmt_top)
    top_producers = [{"tag_id": r[0], "total_liters": r[1] or 0.0} for r in result_top.all()]
    
    return schemas.MilkStatsResponse(
        total_liters=total_liters,
        avg_per_animal=avg_per_animal,
        daily_production=daily_production,
        species_breakdown=species_breakdown,
        breed_breakdown=breed_breakdown,
        top_producers=top_producers
    )

@app.get("/animals/milking", response_model=List[schemas.Animal])
async def get_milking_animals(
    user: models.User = Depends(auth.get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Get animals eligible for milking (Females)"""
    # Return all females for now. 
    # Logic: Gender=Female AND Status NOT IN ('Sold', 'Deceased', 'Calf'?)
    # Broad is better.
    stmt = select(models.Animal).filter(
        models.Animal.farm_id == user.id,
        models.Animal.gender == schemas.GenderEnum.Female
    ).filter(models.Animal.status.not_in(['Sold', 'Deceased']))
    
    result = await db.execute(stmt)
    return result.scalars().all()
