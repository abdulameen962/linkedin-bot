import sqlite3

conn = sqlite3.connect('linkedin_bot.db')
conn.row_factory = sqlite3.Row
cur = conn.cursor()
cur.execute("SELECT profile_url, full_name, status, connection_status, connected_at, first_message_at, query_used FROM connections ORDER BY connected_at DESC LIMIT 20")
for r in cur.fetchall():
    print(dict(r))
