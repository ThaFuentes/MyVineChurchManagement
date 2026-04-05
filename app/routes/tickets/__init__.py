# app/routes/tickets/__init__.py
# Full path: myvinechurchonline/app/routes/tickets/__init__.py
# File name: __init__.py
# Brief, detailed purpose: Package initializer for the tickets blueprint.
# Imports and exposes tickets_bp from views.py so it can be registered in the main app factory (app/routes/__init__.py or main.py).
# 100% identical to modularization standard used across all features.

from .views import tickets_bp

__all__ = ['tickets_bp']