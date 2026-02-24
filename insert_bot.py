import os
import uuid
import datetime
from cassandra.cluster import Cluster

# Connect to Scylla/Cassandra
cluster = Cluster(['fluxer-cassandra-1'])
session = cluster.connect('fluxer')

BOT_ID = 1227269599951589508
USERNAME = "NePornu Bot"
BOT_TOKEN = "MTIyNzI2OTU5OTk1MTU4OTUwOA.GsCoHP.OEpQd6iF6thu7cbvnBl3c5-48rIREWgoLEY6MY"
APP_ID = BOT_ID

print(f"Injecting Bot ID: {BOT_ID} into fluxer database...")

# Insert User
try:
    session.execute(
        """
        INSERT INTO users (
            user_id, username, bot, system, discriminator, flags, email_verified
        ) VALUES (%s, %s, %s, %s, %s, %s, %s)
        """,
        (BOT_ID, USERNAME, True, False, 6391, 0, True)
    )
    print("✅ Inserted into users table")
except Exception as e:
    print(f"❌ Error inserting user: {e}")

# Insert application
try:
    session.execute(
        """
        INSERT INTO applications (
            application_id, bot_is_public, bot_user_id, is_confidential, name, owner_user_id
        ) VALUES (%s, %s, %s, %s, %s, %s)
        """,
        (APP_ID, True, BOT_ID, False, USERNAME, 0)
    )
    print("✅ Inserted into applications table")
except Exception as e:
    print(f"❌ Error inserting application: {e}")

cluster.shutdown()
print("Done.")
