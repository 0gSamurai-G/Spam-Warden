import os
import json
import re
import requests
import discord
import time
import datetime 
import asyncio
from google import genai
import psycopg2 # NEW: Import for PostgreSQL
from psycopg2 import sql # Helps with safe SQL queries
try:
    from google.generativeai import APIError as GeminiAPIError
except Exception:
    class GeminiAPIError(Exception):
        pass

# --- 0. DISCORD CONFIGURATION ---

DISCORD_BOT_TOKEN = os.environ.get("DISCORD_BOT_TOKEN")
# Set intents for the bot (crucial for message content)
intents = discord.Intents.default()
intents.message_content = True 
intents.members = True 

# --- COMMAND ROLES CONFIGURATION (No longer used, but kept as configuration) ---
MOD_ROLES = ["Admin", "Moderator"]
ADMIN_ROLES = ["Admin", "Bot Owner"] 

# --- RATE LIMITING CONFIGURATION (TIER 0) ---

MAX_MESSAGES_PER_WINDOW = 5 
RATE_LIMIT_WINDOW_SECONDS = 5 
TIMEOUT_DURATION_SECONDS = 120 

USER_MESSAGE_LOG = {} 

# --- 1. CONFIGURATION ---

# LLM Keys & Models
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY") 
PERPLEXITY_API_KEY = os.environ.get("PERPLEXITY_API_KEY")
GEMINI_MODEL = "gemini-2.5-flash"
PERPLEXITY_MODEL = "sonar"
MAX_OUTPUT_TOKENS = 30 

LLM_CLASSIFICATION_PROMPT_TEMPLATE = (
    "Analyze the following text for toxicity, hate speech, or abuse in any language or a harmful/inappropriate url. "
    "Return ONLY a single-line JSON object: "
    "{{\"is_bad\": [true/false], \"bad_word\": \"[The offensive word or phrase, or None]\"}} "
    "Text to analyze: \"{message}\""
)

# --- 2. POSTGRES DATABASE CONFIGURATION (NEW SECTION) ---

# Environment variables are automatically set by Railway
PG_HOST = os.environ.get("PGHOST")
PG_DATABASE = os.environ.get("PGDATABASE")
PG_USER = os.environ.get("PGUSER")
PG_PASSWORD = os.environ.get("PGPASSWORD")
PG_PORT = os.environ.get("PGPORT", "5432")

# Global variables to hold the in-memory sets (for fast O(1) checks)
LOCAL_PROFANITY_SET = set()
LOCAL_ALLOW_SET = set()


def initialize_db(conn):
    """Creates the necessary tables if they don't exist."""
    print("⏳ Initializing database tables...")
    with conn.cursor() as cur:
        # Create 'blocked_words' table
        cur.execute("""
            CREATE TABLE IF NOT EXISTS blocked_words (
                word TEXT PRIMARY KEY,
                added_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
            );
        """)
        # Create 'allowed_words' table
        cur.execute("""
            CREATE TABLE IF NOT EXISTS allowed_words (
                word TEXT PRIMARY KEY,
                added_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
            );
        """)
    conn.commit()
    print("✅ Database tables initialized.")

def load_data_from_db():
    """Loads all words from PostgreSQL into the global in-memory sets."""
    global LOCAL_PROFANITY_SET, LOCAL_ALLOW_SET
    
    if not PG_HOST:
        # This will be expected when running locally without Railway secrets
        print("⚠️ WARNING: PGHOST is not set. Assuming local/dummy mode.")
        return True # Allow execution to continue if DB is not essential initially
    
    try:
        # Use connection credentials injected by Railway
        conn = psycopg2.connect(host=PG_HOST, database=PG_DATABASE, user=PG_USER, password=PG_PASSWORD, port=PG_PORT)
        
        # NOTE: This call handles the one-time creation of the tables
        initialize_db(conn) 
        
        with conn.cursor() as cur:
            # Load Blocked Words
            cur.execute("SELECT word FROM blocked_words;")
            LOCAL_PROFANITY_SET = {row[0] for row in cur.fetchall()}

            # Load Allowed Words
            cur.execute("SELECT word FROM allowed_words;")
            LOCAL_ALLOW_SET = {row[0] for row in cur.fetchall()}
            
        conn.close()
        print("✅ Data successfully loaded from PostgreSQL.")
        return True
    except Exception as e:
        print(f"❌ FATAL DB ERROR: Failed to connect or load data: {e}")
        return False

# --- DUMMY DATA AND FILE IO ARE REMOVED ---

# --- 3. CORE LLM CALL FUNCTIONS & LEARNING LOGIC ---

def call_perplexity(api_key, model_name, prompt):
    # ... (function body remains the same) ...
    url = "https://api.perplexity.ai/chat/completions"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }
    data = {
        "model": model_name,
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": MAX_OUTPUT_TOKENS
    }
    try:
        response = requests.post(url, headers=headers, data=json.dumps(data))
        response.raise_for_status()
        content = response.json()['choices'][0]['message']['content']
        return content
    except Exception as e:
        pass
    return None

def call_gemini(api_key, model_name, prompt):
    # ... (function body remains the same) ...
    try:
        client = genai.Client(api_key=api_key)
        # config = {"max_output_tokens": MAX_OUTPUT_TOKENS} # Configuration can be inline
        
        response = client.models.generate_content(
            model=model_name,
            contents=prompt,
            config={"max_output_tokens": MAX_OUTPUT_TOKENS}
        )
        content = getattr(response, 'text', None)
        return content
    except Exception as e:
        pass
    return None

def process_llm_response(message, llm_output):
    """
    Parses the LLM JSON response and updates LOCAL_PROFANITY_SET or LOCAL_ALLOW_SET (DB Write).
    Returns True if BLOCKED, False if ALLOWED, None if UNKNOWN.
    """
    if not llm_output:
        return None
        
    print(f"LLM Raw Output: {llm_output}")
    try:
        json_match = re.search(r'\{.*\}', llm_output, re.DOTALL)
        data = json.loads(json_match.group(0) if json_match else llm_output)

        is_bad = data.get('is_bad')
        bad_word = data.get('bad_word', 'None')
        
        if is_bad is True:
            # --- ACTION: Add bad word to block list (DATABASE WRITE) ---
            if bad_word and bad_word.lower() != 'none':
                word_to_block = bad_word.lower().strip()
                if word_to_block not in LOCAL_PROFANITY_SET:
                    
                    # 🔑 DATABASE WRITE (BLOCKED WORD) 🔑
                    try:
                        conn = psycopg2.connect(host=PG_HOST, database=PG_DATABASE, user=PG_USER, password=PG_PASSWORD, port=PG_PORT)
                        with conn.cursor() as cur:
                            cur.execute(
                                "INSERT INTO blocked_words (word) VALUES (%s) ON CONFLICT (word) DO NOTHING;",
                                (word_to_block,)
                            )
                        conn.commit()
                        conn.close()
                        LOCAL_PROFANITY_SET.add(word_to_block) # Update in-memory set
                        print(f"🚨 LEARNING: Added '{word_to_block}' to DB.")
                    except Exception as e:
                        print(f"❌ DB WRITE ERROR: Failed to insert blocked word: {e}")
                        
            return True # Blocked
            
        elif is_bad is False:
            # --- ACTION: Add all words to allow list (DATABASE WRITE) ---
            words_to_allow = set(re.split(r'\s|\W', message.lower()))
            words_to_allow.discard('')
            
            # 🔑 DATABASE WRITE (ALLOWED WORDS) 🔑
            newly_allowed_count = 0
            words_to_insert = []
            
            for word in words_to_allow:
                if word and word not in LOCAL_ALLOW_SET:
                    words_to_insert.append((word,))
                    LOCAL_ALLOW_SET.add(word) # Update in-memory set
                    
            if words_to_insert:
                try:
                    conn = psycopg2.connect(host=PG_HOST, database=PG_DATABASE, user=PG_USER, password=PG_PASSWORD, port=PG_PORT)
                    with conn.cursor() as cur:
                        # Use executemany for efficiency
                        cur.executemany(
                            "INSERT INTO allowed_words (word) VALUES (%s) ON CONFLICT (word) DO NOTHING;",
                            words_to_insert
                        )
                    conn.commit()
                    conn.close()
                    newly_allowed_count = len(words_to_insert)
                except Exception as e:
                    print(f"❌ DB WRITE ERROR: Failed to insert allowed words: {e}")

            print(f"👍 LEARNING: Added {newly_allowed_count} unique words to DB.")
            return False # Allowed

    except (json.JSONDecodeError, AttributeError) as e:
        print(f"❌ ERROR: Failed to parse LLM JSON: {e}")
    
    return None # Unknown/Failed to process


# --- 4. TIERED MODERATION LOGIC (Functions remain the same) ---

def check_tier_0_rate_limit(user_id):
    """Tier 0.0: Checks if the user is spamming messages too quickly."""
    current_time = time.time()
    
    if user_id not in USER_MESSAGE_LOG:
        USER_MESSAGE_LOG[user_id] = []
        
    USER_MESSAGE_LOG[user_id] = [
        t for t in USER_MESSAGE_LOG[user_id] 
        if t > current_time - RATE_LIMIT_WINDOW_SECONDS
    ]
    
    is_spamming = len(USER_MESSAGE_LOG[user_id]) >= MAX_MESSAGES_PER_WINDOW
    
    USER_MESSAGE_LOG[user_id].append(current_time)
    
    return is_spamming 

def check_tier_0_allow(message_content, allow_set):
    """Tier 0.1: Checks if the message is an exact match on the allow list."""
    if message_content.lower().strip() in allow_set:
        return "T0.1: Exact Match on Allow List (Basic Conversation)"
    return None

def check_tier_0_all_words(message_content, allow_set):
    """Tier 0.2: Checks if EVERY word in the message is already in the ALLOW list."""
    words = set(re.split(r'\s|\W', message_content.lower()))
    words.discard('')
    if not words: return None
    
    unknown_words = words - allow_set
    if not unknown_words:
        return "T0.2: All words are known safe words (Bypassing LLM)"
    return None

def check_tier_1_spam(message_content):
    """Tier 1: Checks for basic spam, repetition, and flood patterns (Zero Tokens)."""
    
    if len(message_content) > 1000:
        return "T1: Max Length Exceeded (>1000 chars)"

    if len(message_content) >= 10:
        alpha_count = sum(c.isalpha() for c in message_content)
        if alpha_count / len(message_content) < 0.10:
            return "T1: Numeric/Symbol Spam (>90% non-alpha)"
            
    if re.search(r'(.)\1{3,}', message_content, re.IGNORECASE):
        return "T1: Excessive Character Repetition"
        
    if 2 <= len(message_content) <= 15: 
        if all(c.isalpha() or c.isspace() for c in message_content):
            unique_chars = set(c.lower() for c in message_content if c.isalpha())
            
            if len(unique_chars) < len(message_content) * 0.4:
                return "T1: Short Message Low Character Diversity (Likely Gibberish)"

    return None

def check_tier_2_profanity(message_content, profanity_set):
    """Tier 2: Checks for known vulgar keywords."""
    normalized_message = message_content.lower()
    words = set(re.split(r'\s|\W', normalized_message))
    
    for word in words:
        if word in profanity_set: return f"T2: Keyword Found ({word})"
        
    simplified_message = re.sub(r'[^a-z0-9]', '', normalized_message)
    if simplified_message in profanity_set: return f"T2: Simplified Keyword Match"
    return None


# --- 5. THE CORE MODERATION PIPELINE (Function remains the same) ---

def run_moderation_pipeline(message):
    """Runs the message through all tiers and returns True if blocked, False otherwise."""
    
    message_content = message.content

    print(f"\n========================================================")
    print(f"✉️ Analyzing Message: \"{message_content}\" by {message.author.name}")
    print("========================================================")

    if check_tier_0_rate_limit(message.author.id):
        return True 

    t0_result = check_tier_0_allow(message_content, LOCAL_ALLOW_SET)
    if t0_result:
        print(f"🛑 ALLOWED: {t0_result}")
        return False
    
    t1_result = check_tier_1_spam(message_content)
    if t1_result:
        print(f"🚫 BLOCKED: {t1_result}")
        return True 
    
    t2_result = check_tier_2_profanity(message_content, LOCAL_PROFANITY_SET)
    if t2_result:
        print(f"🚫 BLOCKED: {t2_result}")
        return True 
        
    t0_all_words_result = check_tier_0_all_words(message_content, LOCAL_ALLOW_SET)
    if t0_all_words_result:
        print(f"🛑 ALLOWED: {t0_all_words_result}")
        return False
    
    print("✔️ Tiers 0-2 Passed. Proceeding to LLM Nuance Check (Token Used)...")
    
    # T3: LLM Nuance Check
    llm_prompt = LLM_CLASSIFICATION_PROMPT_TEMPLATE.format(message=message_content)
    llm_response_content = None

    llm_response_content = call_perplexity(PERPLEXITY_API_KEY, PERPLEXITY_MODEL, llm_prompt)
    if not llm_response_content:
        llm_response_content = call_gemini(GEMINI_API_KEY, GEMINI_MODEL, llm_prompt)
    
    # Process LLM Response and Learn
    llm_status = process_llm_response(message_content, llm_response_content)
    
    if llm_status is True:
        return True # BLOCKED by LLM
    elif llm_status is False:
        print("\n✅ Moderation Complete (LLM Allowed/Learned).")
        return False # ALLOWED by LLM
    else:
        print("\n⚠️ WARNING: LLM failed. Defaulting to ALLOW to prevent false positive.")
        return False


# --- 6. DISCORD BOT IMPLEMENTATION (Plain Client) (Functions remain the same) ---

class ModBotClient(discord.Client):
    def __init__(self, *, intents: discord.Intents):
        super().__init__(intents=intents)
        self.deletion_lock = asyncio.Lock() 

    async def on_ready(self):
        print('-------------------------------------------')
        print(f'🤖 Bot Logged in as {self.user} (ID: {self.user.id})')
        print(f'✅ LOCAL_ALLOW_SET size: {len(LOCAL_ALLOW_SET)}')
        print(f'❌ LOCAL_PROFANITY_SET size: {len(LOCAL_PROFANITY_SET)}')
        print(f'⏱️ RATE LIMIT: {MAX_MESSAGES_PER_WINDOW} msgs / {RATE_LIMIT_WINDOW_SECONDS}s')
        print('-------------------------------------------')


    async def on_message(self, message: discord.Message):
        """Called every time a message is sent."""
        
        if message.author == self.user or message.author.bot:
            return

        # 1. 🛡️ RUN THE TIERED MODERATION PIPELINE
        is_blocked = run_moderation_pipeline(message)

        if is_blocked:
            user_log = USER_MESSAGE_LOG.get(message.author.id, [])
            
            if len(user_log) > MAX_MESSAGES_PER_WINDOW:
                
                async with self.deletion_lock:
                    # --- ACTION: RATE LIMIT SPAM BLOCK + TIMEOUT ---
                    
                    deleted_count = 0
                    
                    # 1. Delete all spam messages in the current window for the user
                    print(f"🧹 Attempting BULK delete of spam messages from {message.author.name}...")

                    try:
                        deleted_msgs = await message.channel.purge(
                            limit=MAX_MESSAGES_PER_WINDOW + 5,
                            check=lambda m: m.author.id == message.author.id and (time.time() - m.created_at.timestamp() < RATE_LIMIT_WINDOW_SECONDS)
                        )
                        deleted_count = len(deleted_msgs)
                        print(f"✅ BULK DELETE: Successfully deleted {deleted_count} messages.")

                    except discord.errors.Forbidden:
                        print(f"❌ ERROR: Bot lacks 'Manage Messages' permission for BULK deletion.")
                    except Exception as e:
                        print(f"⚠️ WARNING: An error occurred during purge: {e}")
                
                    # 2. Apply Timeout
                    try:
                        member: discord.Member = message.author
                        timeout_until = discord.utils.utcnow() + datetime.timedelta(seconds=TIMEOUT_DURATION_SECONDS)
                        await member.edit(timed_out_until=timeout_until, reason="Automatic Spam Detection (Rate Limit Exceeded)")
                        
                        # 3. Send warning message
                        warning_msg = f"⏱️ **{message.author.mention}** has been timed out for **{TIMEOUT_DURATION_SECONDS} seconds** due to **message spamming** (Deleted {deleted_count} messages)."
                        await message.channel.send(warning_msg, delete_after=15)
                        print(f"🚫 ACTION: T0.0 Rate Limit BLOCKED. User {message.author.name} timed out for {TIMEOUT_DURATION_SECONDS}s.")
                        
                    except discord.errors.Forbidden:
                        print(f"❌ ERROR: Bot does not have 'Moderate Members' (Timeout) permission.")
                
            else:
                # --- ACTION: CONTENT-BASED BLOCK (T1, T2, T3) ---
                try:
                    await message.delete() 
                    warning_message = f"🚫 **{message.author.mention}**, your message was automatically removed due to moderation policies (Content Check)."
                    await message.channel.send(warning_message, delete_after=10)
                except discord.errors.Forbidden:
                    print(f"❌ ERROR: Bot does not have 'Manage Messages' permission.")


# --- EXECUTION (Updated to load DB first) ---
if __name__ == "__main__":
    if not load_data_from_db():
        # If DB connection fails, stop execution
        print("❌ FATAL: Bot failed to initialize database connection/data loading. Exiting.")
    elif not DISCORD_BOT_TOKEN:
        print("❌ FATAL ERROR: DISCORD_BOT_TOKEN environment variable is not set. Exiting.")
    else:
        bot = ModBotClient(intents=intents)
        if not GEMINI_API_KEY or not PERPLEXITY_API_KEY:
            print("⚠️ WARNING: One or more LLM API keys are missing. LLM checks will fail.")
        bot.run(DISCORD_BOT_TOKEN)