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
from app.models.imports import ImportBatch
from app.models.enums import (
    DiscountType,
    ExternalWorkStatus,
    ExternalWorkType,
    PaymentMethod,
    PlatformAction,
    TokenPurpose,
    SaleStatus,
    StockMovementType,
    SupplierType,
    TreatmentType,
)
from app.models.platform import PlatformAuditLog, PlatformUser
from app.models.pricing import CostHistory, PriceCategory, PriceList
from app.models.product import (
    Brand,
    Color,
    Product,
    ProductModel,
    ProductType,
    product_colors,
)
from app.models.sales import PaymentAccount, Sale, SaleItem, SalePayment
from app.models.stock import StockLevel, StockMovement
from app.models.token import UserToken
from app.models.supplier import Supplier, supplier_brands

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
    "ImportBatch",
    "PlatformAuditLog",
    "PlatformUser",
    "CostHistory",
    "PriceCategory",
    "PriceList",
    "Brand",
    "Color",
    "Product",
    "ProductModel",
    "ProductType",
    "StockLevel",
    "UserToken",
    "StockMovement",
    "Supplier",
    "product_colors",
    "supplier_brands",
    "PaymentAccount",
    "Sale",
    "SaleItem",
    "SalePayment",
    # enums
    "SupplierType",
    "StockMovementType",
    "TreatmentType",
    "DiscountType",
    "PaymentMethod",
    "SaleStatus",
    "ExternalWorkType",
    "ExternalWorkStatus",
    "PlatformAction",
    "TokenPurpose",
]
