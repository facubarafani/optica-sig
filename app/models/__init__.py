"""Import every model so SQLAlchemy's metadata is fully populated.

Anything that needs the full schema (Alembic, create_all, mappers) should import
from here.
"""
from app.core.database import Base
from app.models.audit import ChangeHistory, NumberSequence
from app.models.auth import (
    Permission,
    Role,
    User,
    role_permissions,
    user_roles,
)
from app.models.branch import Branch
from app.models.company import Company, CompanySettings
from app.models.customer import Customer, Prescription, TreatmentHistory
from app.models.enums import (
    ExternalWorkStatus,
    ExternalWorkType,
    SaleStatus,
    StockMovementType,
    SupplierType,
    TreatmentType,
)
from app.models.pricing import CostHistory, PriceCategory, PriceList, PriceListItem
from app.models.product import Brand, Product, ProductType
from app.models.stock import StockLevel, StockMovement
from app.models.supplier import Supplier

__all__ = [
    "Base",
    "ChangeHistory",
    "NumberSequence",
    "Permission",
    "Role",
    "User",
    "role_permissions",
    "user_roles",
    "Branch",
    "Company",
    "CompanySettings",
    "Customer",
    "Prescription",
    "TreatmentHistory",
    "CostHistory",
    "PriceCategory",
    "PriceList",
    "PriceListItem",
    "Brand",
    "Product",
    "ProductType",
    "StockLevel",
    "StockMovement",
    "Supplier",
    # enums
    "SupplierType",
    "StockMovementType",
    "TreatmentType",
    "SaleStatus",
    "ExternalWorkType",
    "ExternalWorkStatus",
]
