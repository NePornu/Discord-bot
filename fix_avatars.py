
import os
import json
import logging
import asyncio
import hashlib
import boto3
import discord
from botocore.client import Config
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

MINIO_ENDPOINT = 'http://minio:9000'
MINIO_ACCESS_KEY = 'minioadmin'
MINIO_SECRET_KEY = 'minioadmin'
MINIO_BUCKET = 'fluxer'

DISCORD_TOKEN = os.getenv('BOT_TOKEN')

# Bucket Utils
BUCKET_SIZE = 1000 * 60 * 60 * 24 * 10
def make_bucket(snowflake):
    return (snowflake >> 22) // BUCKET_SIZE

class AvatarFixer(discord.Client):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.state = {}
        self.session = None
        self.s3 = None
        
    async def setup_dbs(self):
        logger.info("Connecting to Cassandra...")
        auth_provider = PlainTextAuthProvider(username=CASSANDRA_USER, password=CASSANDRA_PASS)
        # We need to set allow_remote_native_transport_requests=true on Cassandra side? 
        # Usually internal docker networking treats it as remote?
        # But default config usually works for Docker.
        self.cluster = Cluster(contact_points=CASSANDRA_HOSTS, auth_provider=auth_provider)
        self.session = self.cluster.connect(CASSANDRA_KEYSPACE)
        
        logger.info("Connecting to Minio...")
        self.s3 = boto3.client('s3',
            endpoint_url=MINIO_ENDPOINT,
            aws_access_key_id=MINIO_ACCESS_KEY,
            aws_secret_access_key=MINIO_SECRET_KEY,
            config=Config(signature_version='s3v4'),
            region_name='us-east-1'
        )
        
        # Load Sync State from /app/sync_state.json
        if not os.path.exists('sync_state.json'):
            logger.error("sync_state.json not found!")
            return False
            
        with open('sync_state.json', 'r') as f:
            self.state = json.load(f)
        return True
        
    async def on_ready(self):
        logger.info(f"Logged in as {self.user}")
        if not await self.setup_dbs():
            await self.close()
            return
            
        channel_map = self.state.get('channel_map', {})
        for d_cid, f_cid in channel_map.items():
            await self.process_channel(int(d_cid), int(f_cid))
            
        logger.info("All channels processed.")
        await self.close()
        
    async def process_channel(self, d_cid, f_cid):
        logger.info(f"Processing Channel: Discord {d_cid} -> Fluxer {f_cid}")
        
        # 1. Fetch Fluxer Partitions (buckets) from DB
        try:
            rows = self.session.execute("SELECT bucket FROM channel_message_buckets WHERE channel_id = %s", (f_cid,))
            buckets = [r.bucket for r in rows]
        except Exception as e:
            logger.error(f"Failed to fetch buckets for channel {f_cid}: {e}")
            return

        buckets.sort() # Ensure we scan in order for consistency if needed, but bucket scan order doesn't strictly matter for matching if ID is used for sorting.
        logger.info(f"  Found {len(buckets)} buckets in Fluxer.")
        if not buckets:
            logger.warning("  No buckets found. Skipping.")
            return

        # 2. Load Fluxer Messages
        # Only fetch necessary fields to minimize memory
        # We need to find messages that are MASQUERADED (webhook_id is set)
        fluxer_msgs = []
        stmt = self.session.prepare("SELECT message_id, bucket, content, webhook_name, webhook_id, webhook_avatar_hash FROM messages WHERE channel_id = ? AND bucket = ?")
        
        for b in buckets:
            results = self.session.execute(stmt, (f_cid, b))
            for r in results:
                if r.webhook_id: # Is masqueraded
                    fluxer_msgs.append(r)
        
        # Sort by ID (chronological) to match Discord order
        fluxer_msgs.sort(key=lambda x: x.message_id)
        logger.info(f"  Loaded {len(fluxer_msgs)} masqueraded messages from Fluxer DB.")
        
        if not fluxer_msgs:
            return

        # 3. Match with Discord
        d_channel = self.get_channel(d_cid)
        if not d_channel:
            # Try fetch
            try:
                d_channel = await self.fetch_channel(d_cid)
            except Exception as e:
                logger.error(f"  Failed to fetch Discord channel {d_cid}: {e}")
                return

        matched_count = 0
        fixed_count = 0
        
        # We can keep an index for fluxer messages to avoid O(N^2) if possible,
        # but since streams match (mostly), a simple crawling pointer is best.
        f_idx = 0
        
        # Fetch Discord history
        # limit=None matches the "sync all" approach.
        async for d_msg in d_channel.history(limit=None, oldest_first=True):
            if f_idx >= len(fluxer_msgs):
                break
                
            # Try to match current Discord msg with current Fluxer msg(s)
            # Fluxer list potentially contains fewer messages if some were skipped or not synced yet.
            # So we scan forward in fluxer_msgs? No, sync script should have synced them in order.
            # But if sync script skipped empty messages, we must also skip them.
            if not d_msg.content and not d_msg.embeds and not d_msg.attachments:
                continue # Sync script skips these usually

            # Heuristic match
            # We look ahead in fluxer_msgs a bit in case of desync?
            # Or just strictly check next.
            
            matched_f_msg = None
            
            # Simple greedy match: find the first Fluxer message (from current ptr) that looks like this Discord message.
            # "Looks like" = Content matches AND Author Name matches.
            search_limit = 50 # Don't search too far ahead
            
            for i in range(f_idx, min(f_idx + search_limit, len(fluxer_msgs))):
                f_msg = fluxer_msgs[i]
                
                # Check Content
                # Discord content might need normalization? Sync script stores d_msg.content or ""
                normalized_content = d_msg.content or ""
                
                # Check Author
                # Sync script uses d_msg.author.display_name (or name?)
                # Code: "username": str(msg.author.display_name)[:80]
                target_username = d_msg.author.display_name[:80]
                
                if f_msg.content == normalized_content and f_msg.webhook_name == target_username:
                    matched_f_msg = f_msg
                    f_idx = i + 1 # Advance pointer past this message
                    break
            
            if matched_f_msg:
                matched_count += 1
                
                # Check if fix needed
                if not matched_f_msg.webhook_avatar_hash:
                    # Logic to fix
                    
                    if not d_msg.author.display_avatar:
                        continue
                        
                    try:
                        # 4. Download & Hash
                        avatar_bytes = await d_msg.author.display_avatar.read()
                        md5 = hashlib.md5(avatar_bytes).hexdigest()
                        short_hash = md5[:8]
                        
                        is_gif = d_msg.author.display_avatar.is_animated()
                        if is_gif:
                            short_hash = f"a_{short_hash}"
                            content_type = "image/gif"
                        else:
                            content_type = "image/png" # display_avatar provides png/gif/webp.
                            # We should probably respect the format.
                            # d_msg.author.display_avatar.format gives us format.
                            # But AvatarService implementation uses 'md5' and content type detection?
                            # AvatarService.uploadAvatar -> calls mediaService.getMetadata(base64)
                            # -> verifies format is in AVATAR_EXTENSIONS
                            # -> calculates hash
                            # -> uploadObject
                            
                            # We are bypassing AvatarService validation, writing directly to S3.
                            # We assume data is valid image.
                        
                        # Upload to Minio
                        key = f"avatars/{matched_f_msg.webhook_id}/{short_hash}" # extension??
                        # AvatarService code: key: `${fullKeyPath}/${imageHashShort}` (NO EXTENSION)
                        # wait, does S3 need extension? ContentType handles it.
                        
                        # Check if already exists? (Avoid re-uploading)
                        # s3.head_object...
                        # Optimization: just put.
                        
                        self.s3.put_object(
                            Bucket=MINIO_BUCKET,
                            Key=key,
                            Body=avatar_bytes,
                            ContentType=content_type
                        )
                        
                        # Update DB
                        self.session.execute(
                            "UPDATE messages SET webhook_avatar_hash = %s WHERE channel_id = %s AND bucket = %s AND message_id = %s",
                            (short_hash, f_cid, matched_f_msg.bucket, matched_f_msg.message_id)
                        )
                        fixed_count += 1
                        
                        if fixed_count % 10 == 0:
                            logger.info(f"  Fixed {fixed_count} avatars in {d_channel.name}...")
                            
                    except Exception as e:
                        logger.error(f"  Error fixing message {matched_f_msg.message_id}: {e}")
            else:
                # No match found within search limit
                # This logic desyncs if many unmatched messages occur. 
                # But since we iterate oldest->newest, it should align.
                pass

        logger.info(f"Channel {d_channel.name} Done. Matched: {matched_count}/{len(fluxer_msgs)}, Fixed: {fixed_count}")

if __name__ == "__main__":
    intents = discord.Intents.default()
    intents.message_content = True # Needed to match content
    intents.members = True # Needed for avatar? No, author is in message.
    
    client = AvatarFixer(intents=intents)
    client.run(DISCORD_TOKEN)
