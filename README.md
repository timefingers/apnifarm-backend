# ApniFarm Backend

Shared REST API for the Apni Ecosystem (ApniFarm, ApniMandi, ApniMilk).

## Tech Stack

- **Framework**: FastAPI
- **Database**: PostgreSQL (Cloud SQL) with SQLAlchemy async
- **Auth**: Firebase Admin SDK
- **Deployment**: Google Cloud Run

## Quick Start

```bash
# Create virtual environment
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Set up environment
cp .env.example .env
# Edit .env with your database and Firebase credentials

# Run locally
uvicorn app.main:app --reload --port 8080
```

## Docker

```bash
# Build
docker build -t apnifarm-backend .

# Run
docker run -p 8080:8080 -e PORT=8080 apnifarm-backend
```

## API Endpoints

| Endpoint | Description |
|----------|-------------|
| `GET /health` | Health check |
| `POST /users/register` | Register new user |
| `GET /users/me` | Get current user |
| `POST /assets` | Create livestock asset |
| `GET /assets` | List assets |
| `POST /feeding` | One-click feeding |
| `POST /milk` | Add milk record |

## Environment Variables

See `.env.example` for all configuration options.
