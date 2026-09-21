import sqlite3

conn = sqlite3.connect('linkedin_bot.db')
conn.row_factory = sqlite3.Row
cur = conn.cursor()

cur.execute("SELECT count(*) FROM connections")
total = cur.fetchone()[0]
print(f"TOTAL CONNECTIONS: {total}")

cur.execute("SELECT status, count(*) FROM connections GROUP BY status")
print("\nSTATUS BREAKDOWN:")
for row in cur.fetchall():
    print(f"  {row[0]}: {row[1]}")

cur.execute("SELECT connection_status, count(*) FROM connections GROUP BY connection_status")
print("\nCONNECTION_STATUS BREAKDOWN:")
for row in cur.fetchall():
    print(f"  {row[0]}: {row[1]}")

cur.execute("SELECT profile_url, full_name, status, connection_status, first_message_at, first_message_text FROM connections WHERE first_message_at IS NOT NULL OR status IN ('messaged', 'followed_up', 'replied')")
messaged = cur.fetchall()
print(f"\nTOTAL MESSAGED IN DB: {len(messaged)}")
for m in messaged:
    print(f"  {m['full_name']} ({m['profile_url']}) - status: {m['status']}, msg_at: {m['first_message_at']}")

cur.execute("SELECT profile_url, full_name, status, connection_status FROM connections LIMIT 15")
print("\nSAMPLE 15 RECORDS:")
for r in cur.fetchall():
    print(f"  {r['full_name']} | {r['profile_url']} | status: {r['status']} | conn_status: {r['connection_status']}")
