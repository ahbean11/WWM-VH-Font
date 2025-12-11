#!/bin/bash
pip install -r requirements.txt
python -c "from app import db, app; with app.app_context(): db.create_all(); print('Database initialized successfully')"