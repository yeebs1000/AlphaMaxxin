from .status import router as status_router
from .portfolio import router as portfolio_router
from .watchlists import router as watchlists_router
from .market import router as market_router

routers = [status_router, portfolio_router, watchlists_router, market_router]
