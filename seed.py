import asyncio
from sqlalchemy.future import select
from app.database import engine, get_db, SessionLocal
from app.models import SubscriptionPlan, Base

async def seed_data():
    async with SessionLocal() as session:
        # Check if plans exist
        result = await session.execute(select(SubscriptionPlan))
        plans = result.scalars().first()
        
        if not plans:
            print("Seeding Subscription Plans...")
            current_plans = [
                SubscriptionPlan(name="Free", price_pkr=0.0, max_animals=5),
                SubscriptionPlan(name="Basic", price_pkr=1500.0, max_animals=20),
                SubscriptionPlan(name="Pro", price_pkr=5000.0, max_animals=100)
            ]
            session.add_all(current_plans)
            await session.commit()
            print("Seeding Complete!")
        else:
            print("Plans already exist. Skipping.")

async def main():
    # Ensure tables exist
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    
    await seed_data()

if __name__ == "__main__":
    asyncio.run(main())
