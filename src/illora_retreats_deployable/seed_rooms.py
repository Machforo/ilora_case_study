# seed_rooms.py
from illora.checkin_app.models import Room, Base
from illora.checkin_app.database import SessionLocal, engine
import datetime

# Create tables if missing
Base.metadata.create_all(bind=engine)
session = SessionLocal()

sample_rooms = [
    {
        "name": "Safari Tent",
        "room_type": "Tents",
        "base_price": 12000,
        "total_units": 5,
        "capacity": 2,
        "media": [],
        "description": "Tent with pool view, outdoor fireplace, private bathroom, immersive wildlife experience."
    },
    {
        "name": "Star Bed Suite",
        "room_type": "Star Beds",
        "base_price": 18000,
        "total_units": 2,
        "capacity": 2,
        "media": [],
        "description": "Perched open-air star bed with panoramic views and attached bathroom."
    },
    {
        "name": "Double Room",
        "room_type": "Tents",
        "base_price": 10000,
        "total_units": 3,
        "capacity": 2,
        "media": [],
        "description": "25 m², partial mountain view, private balcony, coffee station, smart TV."
    },
    {
        "name": "suite",
        "room_type": "luxury rooms",
        "base_price": 34000,
        "total_units": 3,
        "capacity": 5,
        "media": [],
        "description": "25 m², partial mountain view, private balcony, coffee station, smart TV, all luxury services free spa sessions and access to the pool area"
    },
    {
        "name": "family",
        "room_type": "family rooms",
        "base_price": 27500,
        "total_units": 5,
        "capacity": 5,
        "media": [],
        "description": "A king sized bed with addotional mattress for family friendly stay. Good scenic views, compliemntary balcony and amaenities"
    }

]

for data in sample_rooms:
    exists = session.query(Room).filter_by(name=data["name"]).first()
    if not exists:
        room = Room(
            name=data["name"],
            room_type=data["room_type"],
            base_price=data["base_price"],
            total_units=data["total_units"],
            capacity=data["capacity"],
            media=data["media"],
            description=data["description"]
        )
        session.add(room)

session.commit()
print("✅ Seeded Ilora Retreats room data.")
session.close()
