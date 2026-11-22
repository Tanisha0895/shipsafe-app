import os

os.environ["DATABASE_URL"] = "sqlite:///./test.db"
os.environ["REDIS_URL"] = "redis://localhost:6390/0"  # nothing runs here, so Redis is "down"
os.environ["INTERNAL_API_KEY"] = "test-key"

if os.path.exists("test.db"):
    os.remove("test.db")