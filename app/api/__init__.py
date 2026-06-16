"""Aggregate API router."""
from fastapi import APIRouter

from app.api.routers import (
    auth,
    branches,
    catalog,
    company,
    customers,
    pricing,
    products,
    stock,
    suppliers,
    users,
)

api_router = APIRouter()
api_router.include_router(auth.router)
api_router.include_router(company.router)
api_router.include_router(users.router)
api_router.include_router(branches.router)
api_router.include_router(suppliers.router)
api_router.include_router(catalog.router)
api_router.include_router(products.router)
api_router.include_router(pricing.router)
api_router.include_router(stock.router)
api_router.include_router(customers.router)
