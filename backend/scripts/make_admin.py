"""将指定用户提升为管理员"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import pymysql
from app.core.config import settings

username = sys.argv[1] if len(sys.argv) > 1 else "test"

conn = pymysql.connect(
    host=settings.MYSQL_HOST,
    user=settings.MYSQL_USER,
    password=settings.MYSQL_PASSWORD,
    database=settings.MYSQL_DATABASE,
)
cursor = conn.cursor()
cursor.execute("UPDATE users SET is_admin = 1 WHERE username = %s", (username,))
conn.commit()
print(f"已将 '{username}' 提升为管理员")
cursor.close()
conn.close()
