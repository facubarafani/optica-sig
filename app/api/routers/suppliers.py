from app.api.crud_router import build_crud_router
from app.core.crud import CRUDBase
from app.models.supplier import Supplier
from app.schemas.supplier import SupplierCreate, SupplierRead, SupplierUpdate

router = build_crud_router(
    prefix="/suppliers",
    tags=["suppliers"],
    crud=CRUDBase(Supplier),
    create_schema=SupplierCreate,
    update_schema=SupplierUpdate,
    read_schema=SupplierRead,
    permission="suppliers",
)
