# payment_gateway.py (with multi-unit extras support)

import stripe
import json
import os
from collections import Counter
from config import Config

# Stripe initialization
stripe.api_key = Config.STRIPE_SECRET_KEY
if not stripe.api_key:
    raise Exception("STRIPE_SECRET_KEY not found")

YOUR_DOMAIN = getattr(Config, "BASE_URL", "http://localhost:8501")
if not (YOUR_DOMAIN.startswith("http://") or YOUR_DOMAIN.startswith("https://")):
    raise ValueError("Config.BASE_URL must be an absolute URL (http(s)://...)")

# -----------------------------
# Load menu.json (Add-ons, Spa, Drinks, etc.)
# -----------------------------
MENU_FILE = os.path.join(os.path.dirname(__file__), "menu.json")
with open(MENU_FILE, "r", encoding="utf-8") as f:
    MENU = json.load(f)

# Flattened pricing dictionary
EXTRA_PRICING = {}
for category, items in MENU.items():
    if category == "complimentary":
        continue
    for name, price in items.items():
        EXTRA_PRICING[name.lower().replace(" ", "_")] = price

# Complimentary items (free)
COMPLIMENTARY_ITEMS = set(MENU.get("complimentary", []))

# -----------------------------
# Room pricing (still fixed in INR)
# -----------------------------
RAW_ROOM_PRICING = {
    "Safari Tent": 12000,
    "Star Bed Suite": 18000,
    "double room": 10000,
    "suite": 34000,
    "family": 27500
}
ROOM_PRICING = {k.lower(): v for k, v in RAW_ROOM_PRICING.items()}


# -----------------------------
# Checkout for room booking + add-ons
# -----------------------------
def create_checkout_session(session_id, room_type, nights, cash=False, extras=None):
    try:
        extras = extras or []
        nights = int(nights)

        # Normalize room_type
        lookup_key = (room_type or "").strip().lower()
        price_per_night = ROOM_PRICING.get(lookup_key)
        if price_per_night is None:
            raise ValueError(f"Invalid room_type for pricing lookup: {room_type!r}")

        # Room charge
        room_amount = 2000 if cash else price_per_night * nights

        line_items = [{
            'price_data': {
                'currency': 'inr',
                'product_data': {
                    'name': f"{room_type} Room Booking",
                    'description': f"{nights} night(s) stay"
                },
                'unit_amount': int(room_amount * 100)  # Stripe expects paise
            },
            'quantity': 1
        }]

        # Aggregate extras by count
        extras_counter = Counter([e.lower().replace(" ", "_") for e in extras])

        for key, qty in extras_counter.items():
            if key in COMPLIMENTARY_ITEMS:
                continue
            extra_price = EXTRA_PRICING.get(key)
            if extra_price:
                line_items.append({
                    'price_data': {
                        'currency': 'inr',
                        'product_data': {'name': key.replace("_", " ").title()},
                        'unit_amount': int(extra_price * 100)
                    },
                    'quantity': qty
                })

        checkout_session = stripe.checkout.Session.create(
            payment_method_types=['card'],
            line_items=line_items,
            mode='payment',
            success_url=f"{YOUR_DOMAIN}?payment=success&session_id={session_id}",
            cancel_url=f"{YOUR_DOMAIN}?payment=cancel&session_id={session_id}",
        )
        return checkout_session.url

    except Exception as e:
        print(f"[Stripe Checkout Error] {e}")
        return None


# -----------------------------
# Checkout for add-ons only
# -----------------------------
def create_addon_checkout_session(session_id, extras):
    try:
        extras = extras or []
        line_items = []

        # Aggregate extras by count
        extras_counter = Counter([e.lower().replace(" ", "_") for e in extras])

        for key, qty in extras_counter.items():
            if key in COMPLIMENTARY_ITEMS:
                continue
            extra_price = EXTRA_PRICING.get(key)
            if extra_price:
                line_items.append({
                    'price_data': {
                        'currency': 'inr',
                        'product_data': {'name': key.replace("_", " ").title()},
                        'unit_amount': int(extra_price * 100)
                    },
                    'quantity': qty
                })

        if not line_items:
            return None

        checkout_session = stripe.checkout.Session.create(
            payment_method_types=['card'],
            line_items=line_items,
            mode='payment',
            success_url=f"{YOUR_DOMAIN}?payment=success&session_id={session_id}",
            cancel_url=f"{YOUR_DOMAIN}?payment=cancel&session_id={session_id}",
        )
        return checkout_session.url

    except Exception as e:
        print(f"[Stripe Add-on Error] {e}")
        return None



# -----------------------------
# Checkout for pending payment
# -----------------------------
def create_pending_checkout_session(pending_amount):
    line_items = []

    line_items.append({
        'price_data': {
                    'currency': 'inr',
                    'product_data': {'name': 'Pending Amount before Checkout'},
                        'unit_amount': int(pending_amount * 100)
                    },
                    'quantity': 1
                })

    checkout_session = stripe.checkout.Session.create(
        payment_method_types=['card'],
        line_items=line_items,
        mode='payment',
        success_url=f"{YOUR_DOMAIN}?payment=success&session_id=1",
        cancel_url=f"{YOUR_DOMAIN}?payment=cancel&session_id=0",
        )
    
    return checkout_session.url

