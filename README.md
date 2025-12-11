# WWM-VH-Font Tool

## Features
- Vietnamese font editing tool
- User authentication (Google OAuth only)
- Payment integration with SePay
- VIP donor system

## Setup Instructions

### 1. Install Dependencies
```bash
pip install -r requirements.txt
```

### 2. Environment Variables
Create a `.env` file with the following variables:

```env
SECRET_KEY=your_secret_key_here
DATABASE_URL=sqlite:///site.db
SHEET_URL=your_google_sheet_url_here
GOOGLE_CLIENT_ID=your_google_client_id_here
GOOGLE_CLIENT_SECRET=your_google_client_secret_here
```

### 3. Google OAuth Setup
1. Go to [Google Cloud Console](https://console.cloud.google.com/)
2. Create a new project or select an existing one
3. Enable the Google+ API
4. Create OAuth 2.0 credentials
5. Add authorized redirect URIs:
   - http://localhost:5000/login/google/callback (for local development)
   - Your production URL for deployment

### 4. Run the Application
```bash
python app.py
```

## Donate System
- Minimum donation: 10.000 VND to become a VIP donor
- Each donation creates a unique code with the user's email hash for verification
- Authentication is handled through SePay webhooks
- VIP donors get unlimited access to the font tool
- Regular members get 1 free trial usage

## User Access System
- Registration has been removed - users can only log in with Google
- Guest access has been removed - only authenticated members can use the font editor
- Regular members get 1 free trial usage
- VIP donors (those who donate 10.000 VND or more) get unlimited usage

## Implementation Notes
- Font patching logic is currently a placeholder and needs to be implemented
- The application uses SQLite for local development and PostgreSQL for production
- Payment verification is handled through SePay webhooks