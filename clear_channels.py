
import json
import logging
import os
from cassandra.cluster import Cluster
from cassandra.auth import PlainTextAuthProvider

# Configure Logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Config
CASSANDRA_HOSTS = ['cassandra'] 
CASSANDRA_KEYSPACE = 'fluxer'
CASSANDRA_USER = 'cassandra' 
CASSANDRA_PASS = 'cassandra'
STATE_FILE = 'sync_state.json'

TARGET_CHANNELS = [
    1474050382828159001, # vedení-nepornu
    1474050387307675675, # grafika-a-socialni-site
    1474050391799775261, # články-žp-podcasty
    1474050396346400799, # sprava-webu
    1474050401828356129, # pravidla-pro-dobrovolníky
    1474050406731497507, # status-oznámení
    1474050411462672421, # chat-pro-dobrovolníky
    1474050416114155559, # práce-s-klienty
    1474050420568506409, # Prostor pro pokec
    1474050634335404075, # Pokec pro tým
]

class ChannelClearer:
    def __init__(self):
        self.session = None
        self.cluster = None
        
    def connect(self):
        logger.info("Connecting to Cassandra...")
        auth_provider = PlainTextAuthProvider(username=CASSANDRA_USER, password=CASSANDRA_PASS)
        self.cluster = Cluster(contact_points=CASSANDRA_HOSTS, auth_provider=auth_provider)
        self.session = self.cluster.connect(CASSANDRA_KEYSPACE)
        
    def clear_channel(self, channel_id):
        logger.info(f"Purging Channel {channel_id}...")
        
        # 1. Fetch buckets
        rows = self.session.execute("SELECT bucket FROM channel_message_buckets WHERE channel_id = %s", (channel_id,))
        buckets = [r.bucket for r in rows]
        
        if not buckets:
            logger.info(f"  No buckets found for {channel_id}.")
        else:
            logger.info(f"  Found {len(buckets)} buckets. Deleting messages...")
            for bucket in buckets:
                # Delete messages
                self.session.execute("DELETE FROM messages WHERE channel_id = %s AND bucket = %s", (channel_id, bucket))
                # Delete reactions (best effort)
                # self.session.execute("DELETE FROM message_reactions WHERE channel_id = %s AND bucket = %s", (channel_id, bucket))
                # ^ actually message_reactions partition key is (channel_id, bucket, message_id)
                logger.info(f"    Bucket {bucket} purged.")
                
        # 2. Delete bucket markers
        self.session.execute("DELETE FROM channel_message_buckets WHERE channel_id = %s", (channel_id,))
        
        # 3. Reset channel metadata
        # primaryKey: ['channel_id', 'soft_deleted']
        self.session.execute(
            "UPDATE channels SET last_message_id = null, indexed_at = null WHERE channel_id = %s AND soft_deleted = false",
            (channel_id,)
        )
        logger.info(f"  Channel {channel_id} metadata reset.")

    def update_sync_state(self):
        if not os.path.exists(STATE_FILE):
            logger.error(f"{STATE_FILE} not found!")
            return
            
        with open(STATE_FILE, 'r') as f:
            state = json.load(f)
            
        # Reverse map to find Discord IDs
        fluxer_to_discord = {v: k for k, v in state.get('channel_map', {}).items()}
        
        modified = False
        last_message_ids = state.get('last_message_ids', {})
        
        for fid in TARGET_CHANNELS:
            did = fluxer_to_discord.get(str(fid))
            if did and did in last_message_ids:
                logger.info(f"Removing sync state for Discord {did} (Fluxer {fid})")
                del last_message_ids[did]
                modified = True
                
        if modified:
            with open(STATE_FILE, 'w') as f:
                json.dump(state, f, indent=2)
            logger.info("sync_state.json updated.")
        else:
            logger.info("No changes needed in sync_state.json.")

    def run(self):
        try:
            self.connect()
            for cid in TARGET_CHANNELS:
                self.clear_channel(cid)
            self.update_sync_state()
            logger.info("All targeted channels cleared.")
        finally:
            if self.cluster:
                self.cluster.shutdown()

if __name__ == "__main__":
    clearer = ChannelClearer()
    clearer.run()
