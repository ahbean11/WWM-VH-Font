from app import db, app

with app.app_context():
    print('Connected to DB:', db.engine.url)
    print('Tables before create_all:', list(db.metadata.tables.keys()))
    db.create_all()
    print('Tables after create_all:', list(db.metadata.tables.keys()))
    print("Database tables created successfully!")