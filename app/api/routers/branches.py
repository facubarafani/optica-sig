from app.api.crud_router import build_crud_router
from app.core.crud import CRUDBase
from app.models.branch import Branch
from app.schemas.branch import BranchCreate, BranchRead, BranchUpdate

router = build_crud_router(
    prefix="/branches",
    tags=["branches"],
    crud=CRUDBase(Branch),
    create_schema=BranchCreate,
    update_schema=BranchUpdate,
    read_schema=BranchRead,
    permission="branches",
)
