import os
import reflex as rx

BACKEND_URL = os.getenv("BACKEND_URL", "http://localhost:8000")
FRONTEND_URL = os.getenv("FRONTEND_URL", "http://localhost:3000")

config = rx.Config(
    app_name="gamehost",
    plugins=[
        rx.plugins.SitemapPlugin(),
        rx.plugins.TailwindV4Plugin(),
    ],
    db_url="sqlite:///gamehost.db",
    deploy_url=FRONTEND_URL,
    api_url=BACKEND_URL,
)
