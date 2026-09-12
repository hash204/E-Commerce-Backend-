from fastapi import FastAPI, Depends, HTTPException, status
from pydantic import BaseModel, EmailStr
from sqlalchemy import create_engine, Column, Integer, String, Float, ForeignKey, DateTime
from sqlalchemy.orm import declarative_base, sessionmaker, Session, relationship
from sqlalchemy.sql import func
import os
from dotenv import load_dotenv

# 1. DATABASE CONFIGURATION
load_dotenv()
DATABASE_URL = os.getenv("DATABASE_URL")

engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


# 2. RELATIONAL DATABASE MODELS
class Product(Base):
    __tablename__ = "products"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False, index=True)
    description = Column(String)
    price = Column(Float, nullable=False)
    inventory_count = Column(Integer, default=0)


class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True, index=True)
    email = Column(String, unique=True, index=True, nullable=False)
    hashed_password = Column(String, nullable=False) 
    
    orders = relationship("Order", back_populates="owner")


class Order(Base):
    __tablename__ = "orders"
    id = Column(Integer, primary_key=True, index=True)
    # Fixed: Let the SQL database engine stamp the timestamp automatically
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    status = Column(String, default="Pending")
    
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    
    owner = relationship("User", back_populates="orders")
    items = relationship("OrderItem", back_populates="order")


class OrderItem(Base):
    __tablename__ = "order_items"
    id = Column(Integer, primary_key=True, index=True)
    quantity = Column(Integer, nullable=False, default=1)
    
    order_id = Column(Integer, ForeignKey("orders.id"), nullable=False)
    product_id = Column(Integer, ForeignKey("products.id"), nullable=False)
    
    order = relationship("Order", back_populates="items")
    product = relationship("Product")


# Generate database schemas
Base.metadata.create_all(bind=engine)


# 3. PYDANTIC SCHEMAS (Fixes incoming JSON Request Data)
class ProductCreate(BaseModel):
    name: str
    price: float
    description: str = None
    inventory_count: int = 10

class UserCreate(BaseModel):
    email: EmailStr  # Automatically checks for real email syntax
    password: str

class OrderCreate(BaseModel):
    user_id: int
    product_id: int
    quantity: int = 1


# 4. FASTAPI CONFIGURATION
app = FastAPI(title="Relational E-Commerce Backend")

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# 5. API ROUTES
@app.get("/")
def home():
    return {"status": "Online", "message": "Welcome to the Relational E-Commerce API!"}


# --- PRODUCT ROUTES ---
@app.get("/products")
def read_products(db: Session = Depends(get_db)):
    return db.query(Product).all()

@app.post("/products", status_code=201)
def create_product(product_data: ProductCreate, db: Session = Depends(get_db)):
    # Converts Pydantic data clean into your database dictionary structure
    new_product = Product(**product_data.model_dump())
    db.add(new_product)
    db.commit()
    db.refresh(new_product)
    return new_product


# --- USER ROUTES ---
@app.post("/users", status_code=201)
def create_user(user_data: UserCreate, db: Session = Depends(get_db)):
    existing_user = db.query(User).filter(User.email == user_data.email).first()
    if existing_user:
        raise HTTPException(status_code=400, detail="Email already registered")
    
    new_user = User(email=user_data.email, hashed_password=user_data.password) 
    db.add(new_user)
    db.commit()
    db.refresh(new_user)
    return {"message": "User registered successfully!", "user_id": new_user.id, "email": new_user.email}


# --- ORDER ROUTES ---
@app.post("/orders", status_code=201)
def place_order(order_data: OrderCreate, db: Session = Depends(get_db)):
    # 1. Verify user exists
    user = db.query(User).filter(User.id == order_data.user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
        
    # 2. Verify product exists and check stock levels
    product = db.query(Product).filter(Product.id == order_data.product_id).first()
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")
    if product.inventory_count < order_data.quantity:
        raise HTTPException(status_code=400, detail="Not enough stock available")
        
    # 3. Deduct stock items from inventory
    product.inventory_count -= order_data.quantity
    
    # 4. Create Order entry
    new_order = Order(user_id=order_data.user_id, status="Processing")
    db.add(new_order)
    db.commit() 
    db.refresh(new_order)
    
    # 5. Create Order Line Item entry linking everything together
    order_item = OrderItem(order_id=new_order.id, product_id=order_data.product_id, quantity=order_data.quantity)
    db.add(order_item)
    db.commit()
    
    return {
        "message": "Order placed successfully!",
        "order_id": new_order.id,
        "product_ordered": product.name,
        "quantity": order_data.quantity,
        "remaining_stock": product.inventory_count
    }

@app.get("/users/{user_id}/orders")
def get_user_orders(user_id: int, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    
    # Fixed: Manual structural breakdown prevents infinite nested JSON loops
    return {
        "user_email": user.email, 
        "orders": [{"id": o.id, "status": o.status, "created_at": o.created_at} for o in user.orders]
    }


# 6. SERVER RUN TIME ENVIRONMENT CONFIGURATION
if __name__ == "__main__":
    import uvicorn
    # Look for the port Render provides dynamically, fallback to 8000 for local testing
    port = int(os.getenv("PORT", 8000)) 
    
    # Change "main:app" string target to match your file name if not named main.py
    uvicorn.run("main:app", host="0.0.0.0", port=port, reload=False)
