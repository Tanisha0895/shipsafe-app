import os

os.environ["DATABASE_URL"] = "sqlite:///./test.db"
os.environ["JWT_SECRET"] = "test-secret-key-that-is-at-least-32-bytes-long"

if os.path.exists("test.db"):
    os.remove("test.db")