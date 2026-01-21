# main.py
# Full path: myvinechurchonline/main.py
# File name: main.py
# Brief, detailed purpose: Application entry point. Creates the Flask app using the factory pattern
# from app/__init__.py and runs the development server when executed directly.
# Database table creation is handled inside create_app() (idempotent with IF NOT EXISTS).
# Owner registration enforcement is handled via @app.before_request in __init__.py.
# No top-level database calls are needed here – everything requiring app context is already
# wrapped inside the factory or route handlers for smoothness and to avoid context errors.

from app import create_app

app = create_app()

if __name__ == '__main__':
    # Development mode only – use gunicorn or similar WSGI server in production
    app.run(
        host='0.0.0.0',
        port=5050,
        debug=True,
        threaded=True
    )