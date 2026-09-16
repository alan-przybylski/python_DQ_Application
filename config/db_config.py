"""The application database lives in the project, independently of the terminal."""

from config.paths import DATABASE_PATH

config = {"database": str(DATABASE_PATH)}
