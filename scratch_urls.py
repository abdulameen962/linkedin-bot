import sqlite3

conn = sqlite3.connect('linkedin_bot.db')
cur = conn.cursor()
cur.execute("SELECT profile_url FROM connections")
urls = [r[0] for r in cur.fetchall()]
for u in urls:
    print(u)
