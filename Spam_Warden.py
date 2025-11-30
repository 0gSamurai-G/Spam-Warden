# import os
# import json
# import re
# import requests
# from discord.ext import commands
# import discord
# import time
# import datetime 
# import asyncio
# from google import genai
# import psycopg2 # NEW: Import for PostgreSQL
# from psycopg2 import sql # Helps with safe SQL queries
# try:
#     from google.generativeai import APIError as GeminiAPIError
# except Exception:
#     class GeminiAPIError(Exception):
#         pass

# # --- 0. DISCORD CONFIGURATION ---
# ALLOWED_SERVERS = {1439561356960464979}
# DISCORD_BOT_TOKEN = os.environ.get("DISCORD_BOT_TOKEN")
# # Set intents for the bot (crucial for message content)
# intents = discord.Intents.default()
# intents.message_content = True 
# intents.members = True 

# # --- COMMAND ROLES CONFIGURATION (No longer used, but kept as configuration) ---
# MOD_ROLES = ["Admin", "Moderator"]
# ADMIN_ROLES = ["Admin", "Bot Owner"] 

# # --- RATE LIMITING CONFIGURATION (TIER 0) ---

# MAX_MESSAGES_PER_WINDOW = 5 
# RATE_LIMIT_WINDOW_SECONDS = 5 
# TIMEOUT_DURATION_SECONDS = 120 

# USER_MESSAGE_LOG = {} 

# # --- 1. CONFIGURATION ---
# bot = commands.Bot(command_prefix='!', intents=intents)

# # LLM Keys & Models
# GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY") 
# PERPLEXITY_API_KEY = os.environ.get("PERPLEXITY_API_KEY")
# GEMINI_MODEL = "gemini-2.5-flash"
# PERPLEXITY_MODEL = "sonar"
# MAX_OUTPUT_TOKENS = 30 

# LLM_CLASSIFICATION_PROMPT_TEMPLATE = (
#     "Analyze the following text for toxicity, hate speech, or abuse in any language or a harmful/inappropriate url. "
#     "Return ONLY a single-line JSON object: "
#     "{{\"is_bad\": [true/false], \"bad_word\": \"[The offensive word or phrase, or None]\"}} "
#     "Text to analyze: \"{message}\""
# )

# # --- 2. POSTGRES DATABASE CONFIGURATION (NEW SECTION) ---

# # Environment variables are automatically set by Railway
# PG_HOST = os.environ.get("PGHOST")
# PG_DATABASE = os.environ.get("PGDATABASE")
# PG_USER = os.environ.get("PGUSER")
# PG_PASSWORD = os.environ.get("PGPASSWORD")
# PG_PORT = os.environ.get("PGPORT", "5432")

# # Global variables to hold the in-memory sets (for fast O(1) checks)
# LOCAL_PROFANITY_SET = set()
# LOCAL_ALLOW_SET = set()


# def initialize_db(conn):
#     """Creates the necessary tables if they don't exist."""
#     print("⏳ Initializing database tables...")
#     with conn.cursor() as cur:
#         # Create 'blocked_words' table
#         cur.execute("""
#             CREATE TABLE IF NOT EXISTS blocked_words (
#                 word TEXT PRIMARY KEY,
#                 added_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
#             );
#         """)
#         # Create 'allowed_words' table
#         cur.execute("""
#             CREATE TABLE IF NOT EXISTS allowed_words (
#                 word TEXT PRIMARY KEY,
#                 added_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
#             );
#         """)
#     conn.commit()
#     print("✅ Database tables initialized.")

# def load_data_from_db():
#     """Loads all words from PostgreSQL into the global in-memory sets."""
#     global LOCAL_PROFANITY_SET, LOCAL_ALLOW_SET
    
#     if not PG_HOST:
#         # This will be expected when running locally without Railway secrets
#         print("⚠️ WARNING: PGHOST is not set. Assuming local/dummy mode.")
#         return True # Allow execution to continue if DB is not essential initially
    
#     try:
#         # Use connection credentials injected by Railway
#         conn = psycopg2.connect(host=PG_HOST, database=PG_DATABASE, user=PG_USER, password=PG_PASSWORD, port=PG_PORT)
        
#         # NOTE: This call handles the one-time creation of the tables
#         initialize_db(conn) 
        
#         with conn.cursor() as cur:
#             # Load Blocked Words
#             cur.execute("SELECT word FROM blocked_words;")
#             LOCAL_PROFANITY_SET = {row[0] for row in cur.fetchall()}

#             # Load Allowed Words
#             cur.execute("SELECT word FROM allowed_words;")
#             LOCAL_ALLOW_SET = {row[0] for row in cur.fetchall()}
            
#         conn.close()
#         print("✅ Data successfully loaded from PostgreSQL.")
#         return True
#     except Exception as e:
#         print(f"❌ FATAL DB ERROR: Failed to connect or load data: {e}")
#         return False

# # --- DUMMY DATA AND FILE IO ARE REMOVED ---

# # --- 3. CORE LLM CALL FUNCTIONS & LEARNING LOGIC ---

# def call_perplexity(api_key, model_name, prompt):
#     url = "https://api.perplexity.ai/chat/completions"
#     headers = {
#         # IMPORTANT: Ensure the key is correctly formatted
#         "Authorization": f"Bearer {api_key}",
#         "Content-Type": "application/json"
#     }
#     data = {
#         "model": model_name,
#         "messages": [{"role": "user", "content": prompt}],
#         "max_tokens": MAX_OUTPUT_TOKENS
#     }
#     try:
#         response = requests.post(url, headers=headers, data=json.dumps(data))
#         # This will raise an exception for bad status codes (4xx, 5xx)
#         response.raise_for_status() 
#         content = response.json()['choices'][0]['message']['content']
#         print("✅ Perplexity call successful.")
#         return content
#     except requests.exceptions.HTTPError as http_err:
#         # Catch 401, 403, 429 errors here
#         print(f"❌ PERPLEXITY HTTP ERROR (Code {http_err.response.status_code}): {http_err.response.text}")
#     except Exception as e:
#         # Catch other errors like JSONDecodeError or network issues
#         print(f"❌ PERPLEXITY GENERAL ERROR: {e}")
    
#     return None # Returns None on any failure, triggering Gemini fallback

# def call_gemini(api_key, model_name, prompt):
#     # ... (function body remains the same) ...
#     try:
#         client = genai.Client(api_key=api_key)
#         config = {"max_output_tokens": MAX_OUTPUT_TOKENS} # Configuration can be inline
        
#         response = client.models.generate_content(
#             model=model_name,
#             contents=prompt,
#         )
#         content = getattr(response, 'text', None)
#         return content
#     except Exception as e:
#         pass
#     return None

# def process_llm_response(message, llm_output):
#     """
#     Parses the LLM JSON response and updates LOCAL_PROFANITY_SET or LOCAL_ALLOW_SET (DB Write).
#     Returns True if BLOCKED, False if ALLOWED, None if UNKNOWN.
#     """
#     if not llm_output:
#         return None
        
#     print(f"LLM Raw Output: {llm_output}")
#     try:
#         json_match = re.search(r'\{.*\}', llm_output, re.DOTALL)
#         data = json.loads(json_match.group(0) if json_match else llm_output)

#         is_bad = data.get('is_bad')
#         bad_word = data.get('bad_word', 'None')
        
#         if is_bad is True:
#             # --- ACTION: Add bad word to block list (DATABASE WRITE) ---
#             if bad_word and bad_word.lower() != 'none':
#                 word_to_block = bad_word.lower().strip()
#                 if word_to_block not in LOCAL_PROFANITY_SET:
                    
#                     # 🔑 DATABASE WRITE (BLOCKED WORD) 🔑
#                     try:
#                         conn = psycopg2.connect(host=PG_HOST, database=PG_DATABASE, user=PG_USER, password=PG_PASSWORD, port=PG_PORT)
#                         with conn.cursor() as cur:
#                             cur.execute(
#                                 "INSERT INTO blocked_words (word) VALUES (%s) ON CONFLICT (word) DO NOTHING;",
#                                 (word_to_block,)
#                             )
#                         conn.commit()
#                         conn.close()
#                         LOCAL_PROFANITY_SET.add(word_to_block) # Update in-memory set
#                         print(f"🚨 LEARNING: Added '{word_to_block}' to DB.")
#                     except Exception as e:
#                         print(f"❌ DB WRITE ERROR: Failed to insert blocked word: {e}")
                        
#             return True # Blocked
            
#         elif is_bad is False:
#             # --- ACTION: Add all words to allow list (DATABASE WRITE) ---
#             words_to_allow = set(re.split(r'\s|\W', message.lower()))
#             words_to_allow.discard('')
            
#             # 🔑 DATABASE WRITE (ALLOWED WORDS) 🔑
#             newly_allowed_count = 0
#             words_to_insert = []
            
#             for word in words_to_allow:
#                 if word and word not in LOCAL_ALLOW_SET:
#                     words_to_insert.append((word,))
#                     LOCAL_ALLOW_SET.add(word) # Update in-memory set
                    
#             if words_to_insert:
#                 try:
#                     conn = psycopg2.connect(host=PG_HOST, database=PG_DATABASE, user=PG_USER, password=PG_PASSWORD, port=PG_PORT)
#                     with conn.cursor() as cur:
#                         # Use executemany for efficiency
#                         cur.executemany(
#                             "INSERT INTO allowed_words (word) VALUES (%s) ON CONFLICT (word) DO NOTHING;",
#                             words_to_insert
#                         )
#                     conn.commit()
#                     conn.close()
#                     newly_allowed_count = len(words_to_insert)
#                 except Exception as e:
#                     print(f"❌ DB WRITE ERROR: Failed to insert allowed words: {e}")

#             print(f"👍 LEARNING: Added {newly_allowed_count} unique words to DB.")
#             return False # Allowed

#     except (json.JSONDecodeError, AttributeError) as e:
#         print(f"❌ ERROR: Failed to parse LLM JSON: {e}")
    
#     return None # Unknown/Failed to process


# # --- 4. TIERED MODERATION LOGIC (Functions remain the same) ---

# def check_tier_0_rate_limit(user_id):
#     """Tier 0.0: Checks if the user is spamming messages too quickly."""
#     current_time = time.time()
    
#     if user_id not in USER_MESSAGE_LOG:
#         USER_MESSAGE_LOG[user_id] = []
        
#     USER_MESSAGE_LOG[user_id] = [
#         t for t in USER_MESSAGE_LOG[user_id] 
#         if t > current_time - RATE_LIMIT_WINDOW_SECONDS
#     ]
    
#     is_spamming = len(USER_MESSAGE_LOG[user_id]) >= MAX_MESSAGES_PER_WINDOW
    
#     USER_MESSAGE_LOG[user_id].append(current_time)
    
#     return is_spamming 

# def check_tier_0_allow(message_content, allow_set):
#     """Tier 0.1: Checks if the message is an exact match on the allow list."""
#     if message_content.lower().strip() in allow_set:
#         return "T0.1: Exact Match on Allow List (Basic Conversation)"
#     return None

# def check_tier_0_all_words(message_content, allow_set):
#     """Tier 0.2: Checks if EVERY word in the message is already in the ALLOW list."""
#     words = set(re.split(r'\s|\W', message_content.lower()))
#     words.discard('')
#     if not words: return None
    
#     unknown_words = words - allow_set
#     if not unknown_words:
#         return "T0.2: All words are known safe words (Bypassing LLM)"
#     return None

# # def check_tier_1_spam(message_content):
# #     """Tier 1: Checks for basic spam, repetition, and flood patterns (Zero Tokens)."""
    
# #     if len(message_content) > 1000:
# #         return "T1: Max Length Exceeded (>1000 chars)"

# #     if len(message_content) >= 10:
# #         alpha_count = sum(c.isalpha() for c in message_content)
# #         if alpha_count / len(message_content) < 0.10:
# #             return "T1: Numeric/Symbol Spam (>90% non-alpha)"
            
# #     if re.search(r'(.)\1{3,}', message_content, re.IGNORECASE):
# #         return "T1: Excessive Character Repetition"
        
# #     if 2 <= len(message_content) <= 15: 
# #         if all(c.isalpha() or c.isspace() for c in message_content):
# #             unique_chars = set(c.lower() for c in message_content if c.isalpha())
            
# #             if len(unique_chars) < len(message_content) * 0.4:
# #                 return "T1: Short Message Low Character Diversity (Likely Gibberish)"

# #     return None


# # def check_tier_1_spam(message_content):
# #     """Tier 1: Checks for basic spam, repetition, and flood patterns (Zero Tokens)."""
    
# #     if len(message_content) > 1000:
# #         return "T1: Max Length Exceeded (>1000 chars)"

# #     # ==========================================================
# #     # 🌟 FIX: Clean message content to allow Mentions and URLs 🌟
# #     # ==========================================================
    
# #     # 1. Remove Discord Mentions (User, Channel, Role, Everyone/Here)
# #     # Pattern: < followed by @, #, or :, then numbers/letters/symbols, ending with >
# #     # This ensures mentions like <@12345> are stripped out completely.
# #     clean_content = re.sub(r'<[#@!&]?[0-9a-zA-Z:]+>', '', message_content) 
    
# #     # 2. Remove URLs (common source of non-alpha characters like : / .)
# #     clean_content = re.sub(r'https?:\/\/\S+', '', clean_content)
    
# #     # 3. Strip leading/trailing whitespace
# #     clean_content = clean_content.strip()

# #     # Numeric/Symbol Spam Check (Applied to CLEANED content)
# #     if len(clean_content) >= 10:
# #         alpha_count = sum(c.isalpha() for c in clean_content)
        
# #         # Check ratio only if meaningful content remains
# #         if len(clean_content) > 0 and alpha_count / len(clean_content) < 0.10:
# #             return "T1: Numeric/Symbol Spam (>90% non-alpha)"
            
# #     # ==========================================================
# #     # END OF FIX. Remaining checks use the original message_content.
# #     # ==========================================================
        
# #     # Excessive Character Repetition Check (uses ORIGINAL message_content)
# #     if re.search(r'(.)\1{8,}', message_content, re.IGNORECASE):
# #         return "T1: Excessive Character Repetition"
    
# #     # Short Message Low Character Diversity Check (uses ORIGINAL message_content)
# #     if 2 <= len(message_content) <= 15: 
# #         if all(c.isalpha() or c.isspace() for c in message_content):
# #             unique_chars = set(c.lower() for c in message_content if c.isalpha())
            
# #             if len(unique_chars) < len(message_content) * 0.4:
# #                 return "T1: Short Message Low Character Diversity (Likely Gibberish)"

# #     return None


# import re

# def check_tier_1_spam(message_content):
#     """Tier 1: Checks for basic spam, repetition, and flood patterns (Zero Tokens)."""
    
#     if len(message_content) > 1000:
#         return "T1: Max Length Exceeded (>1000 chars)"

#     # ==========================================================
#     # 🌟 FIX: Clean message content to allow Mentions and URLs 🌟
#     # ==========================================================
    
#     # 1. Remove Discord Mentions (User, Channel, Role, Everyone/Here)
#     # Pattern: < followed by @, #, or :, then numbers/letters/symbols, ending with >
#     # This ensures mentions like <@12345> are stripped out completely.
#     clean_content = re.sub(r'<[#@!&]?[0-9a-zA-Z:]+>', '', message_content) 
    
#     # 2. Remove URLs (common source of non-alpha characters like : / .)
#     clean_content = re.sub(r'https?:\/\/\S+', '', clean_content)
    
#     # 3. Strip leading/trailing whitespace
#     clean_content = clean_content.strip()

#     # Numeric/Symbol Spam Check (Applied to CLEANED content)
#     if len(clean_content) >= 10:
#         alpha_count = sum(c.isalpha() for c in clean_content)
        
#         # Check ratio only if meaningful content remains
#         if len(clean_content) > 0 and alpha_count / len(clean_content) < 0.10:
#             return "T1: Numeric/Symbol Spam (>90% non-alpha)"
            
#     # ==========================================================
#     # END OF FIX. Remaining checks use the original message_content.
#     # ==========================================================
        
#     # Excessive Character Repetition Check (now requires 9+ consecutive chars)
#     if re.search(r'(.)\1{8,}', message_content, re.IGNORECASE):
#         return "T1: Excessive Character Repetition"
    
#     # 🚨 REMOVED: Short Message Low Character Diversity Check (Removed to prevent false positives)

#     return None

# def check_tier_2_profanity(message_content, profanity_set):
#     """Tier 2: Checks for known vulgar keywords."""
#     normalized_message = message_content.lower()
#     words = set(re.split(r'\s|\W', normalized_message))
    
#     for word in words:
#         if word in profanity_set: return f"T2: Keyword Found ({word})"
        
#     simplified_message = re.sub(r'[^a-z0-9]', '', normalized_message)
#     if simplified_message in profanity_set: return f"T2: Simplified Keyword Match"
#     return None


# # --- 5. THE CORE MODERATION PIPELINE (Function remains the same) ---

# def run_moderation_pipeline(message):
#     """Runs the message through all tiers and returns True if blocked, False otherwise."""
    
#     message_content = message.content

#     print(f"\n========================================================")
#     print(f"✉️ Analyzing Message: \"{message_content}\" by {message.author.name}")
#     print("========================================================")

#     if check_tier_0_rate_limit(message.author.id):
#         return True 

#     t0_result = check_tier_0_allow(message_content, LOCAL_ALLOW_SET)
#     if t0_result:
#         print(f"🛑 ALLOWED: {t0_result}")
#         return False
    
#     t1_result = check_tier_1_spam(message_content)
#     if t1_result:
#         print(f"🚫 BLOCKED: {t1_result}")
#         return True 
    
#     t2_result = check_tier_2_profanity(message_content, LOCAL_PROFANITY_SET)
#     if t2_result:
#         print(f"🚫 BLOCKED: {t2_result}")
#         return True 
        
#     t0_all_words_result = check_tier_0_all_words(message_content, LOCAL_ALLOW_SET)
#     if t0_all_words_result:
#         print(f"🛑 ALLOWED: {t0_all_words_result}")
#         return False
    
#     print("✔️ Tiers 0-2 Passed. Proceeding to LLM Nuance Check (Token Used)...")
    
#     # T3: LLM Nuance Check
#     llm_prompt = LLM_CLASSIFICATION_PROMPT_TEMPLATE.format(message=message_content)
#     llm_response_content = None

#     llm_response_content = call_perplexity(PERPLEXITY_API_KEY, PERPLEXITY_MODEL, llm_prompt)
#     if not llm_response_content:
#         llm_response_content = call_gemini(GEMINI_API_KEY, GEMINI_MODEL, llm_prompt)
    
#     # Process LLM Response and Learn
#     llm_status = process_llm_response(message_content, llm_response_content)
    
#     if llm_status is True:
#         return True # BLOCKED by LLM
#     elif llm_status is False:
#         print("\n✅ Moderation Complete (LLM Allowed/Learned).")
#         return False # ALLOWED by LLM
#     else:
#         print("\n⚠️ WARNING: LLM failed. Defaulting to ALLOW to prevent false positive.")
#         return False


# # --- 6. DISCORD BOT IMPLEMENTATION (Plain Client) (Functions remain the same) ---

# class ModBotClient(discord.Client):
#     def __init__(self, *, intents: discord.Intents):
#         super().__init__(intents=intents)
#         self.deletion_lock = asyncio.Lock() 

#     async def on_ready(self):
#         print('-------------------------------------------')
#         print(f'🤖 Bot Logged in as {self.user} (ID: {self.user.id})')
#         print(f'✅ LOCAL_ALLOW_SET size: {len(LOCAL_ALLOW_SET)}')
#         print(f'❌ LOCAL_PROFANITY_SET size: {len(LOCAL_PROFANITY_SET)}')
#         print(f'⏱️ RATE LIMIT: {MAX_MESSAGES_PER_WINDOW} msgs / {RATE_LIMIT_WINDOW_SECONDS}s')
#         print('-------------------------------------------')

#         unauthorized_guilds = []
#         for guild in bot.guilds:
#             if guild.id not in ALLOWED_SERVERS:
#                 unauthorized_guilds.append(guild.name)
#                 await guild.leave()
            
#         if unauthorized_guilds:
#             print(f"🚫 CLEANUP: Left the following unauthorized guilds on startup: {', '.join(unauthorized_guilds)}")

#         await bot.change_presence(activity=discord.Game(name="Moderating the Server"))


#     async def on_message(self, message: discord.Message):
#         """Called every time a message is sent."""
        
#         if message.author == self.user or message.author.bot:
#             return

#         # 1. 🛡️ RUN THE TIERED MODERATION PIPELINE
#         is_blocked = run_moderation_pipeline(message)

#         if is_blocked:
#             user_log = USER_MESSAGE_LOG.get(message.author.id, [])
            
#             if len(user_log) > MAX_MESSAGES_PER_WINDOW:
                
#                 async with self.deletion_lock:
#                     # --- ACTION: RATE LIMIT SPAM BLOCK + TIMEOUT ---
                    
#                     deleted_count = 0
                    
#                     # 1. Delete all spam messages in the current window for the user
#                     print(f"🧹 Attempting BULK delete of spam messages from {message.author.name}...")

#                     try:
#                         deleted_msgs = await message.channel.purge(
#                             limit=MAX_MESSAGES_PER_WINDOW + 5,
#                             check=lambda m: m.author.id == message.author.id and (time.time() - m.created_at.timestamp() < RATE_LIMIT_WINDOW_SECONDS)
#                         )
#                         deleted_count = len(deleted_msgs)
#                         print(f"✅ BULK DELETE: Successfully deleted {deleted_count} messages.")

#                     except discord.errors.Forbidden:
#                         print(f"❌ ERROR: Bot lacks 'Manage Messages' permission for BULK deletion.")
#                     except Exception as e:
#                         print(f"⚠️ WARNING: An error occurred during purge: {e}")
                
#                     # 2. Apply Timeout
#                     try:
#                         member: discord.Member = message.author
#                         timeout_until = discord.utils.utcnow() + datetime.timedelta(seconds=TIMEOUT_DURATION_SECONDS)
#                         await member.edit(timed_out_until=timeout_until, reason="Automatic Spam Detection (Rate Limit Exceeded)")
                        
#                         # 3. Send warning message
#                         warning_msg = f"⏱️ **{message.author.mention}** has been timed out for **{TIMEOUT_DURATION_SECONDS} seconds** due to **message spamming** (Deleted {deleted_count} messages)."
#                         await message.channel.send(warning_msg, delete_after=15)
#                         print(f"🚫 ACTION: T0.0 Rate Limit BLOCKED. User {message.author.name} timed out for {TIMEOUT_DURATION_SECONDS}s.")
                        
#                     except discord.errors.Forbidden:
#                         print(f"❌ ERROR: Bot does not have 'Moderate Members' (Timeout) permission.")
                
#             else:
#                 # --- ACTION: CONTENT-BASED BLOCK (T1, T2, T3) ---
#                 try:
#                     await message.delete() 
#                     warning_message = f"🚫 **{message.author.mention}**, your message was automatically removed due to moderation policies (Content Check)."
#                     await message.channel.send(warning_message, delete_after=10)
#                 except discord.errors.Forbidden:
#                     print(f"❌ ERROR: Bot does not have 'Manage Messages' permission.")


# @bot.event
# async def on_guild_join(guild):
#     """3. 🛡️ CHECK ON NEW INVITE"""
#     if guild.id not in ALLOWED_SERVERS:
#         print(f"❌ UNAUTHORIZED JOIN: Leaving Guild '{guild.name}' (ID: {guild.id})")
#         # Optional: Add a polite message here before leaving
#         await guild.leave()
#     else:
#         print(f"✅ ALLOWED JOIN: Staying in Guild '{guild.name}' (ID: {guild.id})")


# # --- EXECUTION (Updated to load DB first) ---
# if __name__ == "__main__":
#     if not load_data_from_db():
#         # If DB connection fails, stop execution
#         print("❌ FATAL: Bot failed to initialize database connection/data loading. Exiting.")
#     elif not DISCORD_BOT_TOKEN:
#         print("❌ FATAL ERROR: DISCORD_BOT_TOKEN environment variable is not set. Exiting.")
#     else:
#         bot = ModBotClient(intents=intents)
#         if not GEMINI_API_KEY or not PERPLEXITY_API_KEY:
#             print("⚠️ WARNING: One or more LLM API keys are missing. LLM checks will fail.")
#         bot.run(DISCORD_BOT_TOKEN)









# import os
# import json
# import re
# import requests
# from discord.ext import commands
# import discord
# import time
# import datetime 
# import asyncio
# from google import genai
# import psycopg2 
# from psycopg2 import sql 
# try:
#     from google.generativeai import APIError as GeminiAPIError
# except Exception:
#     class GeminiAPIError(Exception):
#         pass

# # --- 0. DISCORD CONFIGURATION ---
# ALLOWED_SERVERS = {1439561356960464979,1442817806344126496}
# DISCORD_BOT_TOKEN = os.environ.get("DISCORD_BOT_TOKEN")
# # Set intents for the bot (crucial for message content)
# intents = discord.Intents.default()
# intents.message_content = True 
# intents.members = True 

# # --- COMMAND ROLES CONFIGURATION ---
# MOD_ROLES = ["Admin", "Moderator"]
# ADMIN_ROLES = ["Admin", "Bot Owner"] 

# # --- RATE LIMITING CONFIGURATION (TIER 0) ---
# MAX_MESSAGES_PER_WINDOW = 5 
# RATE_LIMIT_WINDOW_SECONDS = 5 
# TIMEOUT_DURATION_SECONDS = 120 
# USER_MESSAGE_LOG = {} 

# # --- 1. CONFIGURATION ---
# # We keep this for command registration until the class is defined
# bot = commands.Bot(command_prefix='!', intents=intents,help_command=None)

# # 🌟 FIX: REPLACE GLOBAL STRING WITH GLOBAL DICTIONARY 🌟
# # Stores {guild_id: "low" | "mid" | "high" | "warden"}
# GUILD_STRICTNESS_MODES = {} 

# # LLM Keys & Models
# GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY") 
# PERPLEXITY_API_KEY = os.environ.get("PERPLEXITY_API_KEY")
# GEMINI_MODEL = "gemini-2.5-flash"
# PERPLEXITY_MODEL = "sonar"
# MAX_OUTPUT_TOKENS = 30 

# # -------------------------------------------------------------------
# # GLOBAL STRICTNESS STATE (Default to 'low')
# # REMOVED: LLM_STRICTNESS = 'low' (Now handled by per-guild dictionary lookup)

# # Utility function to get the current mode for a guild
# def get_current_mode(guild_id):
#     """Retrieves the strictness mode for a specific guild, defaulting to 'low'."""
#     # Use .get() with a default value to ensure we always return a valid mode
#     return GUILD_STRICTNESS_MODES.get(guild_id, "low")


# # 🟢 LOW (MILD) PROMPT: Ignores minor insults (The desired mild prompt)
# MILD_PROMPT = (
#     """Analyze the following text for **SEVERE** toxicity, **HATE SPEECH**, graphic content, **serious abuse**, or a harmful/inappropriate url.
# **Ignore minor insults, mild teasing, sarcasm, and conversational disagreements or non-severe terms (e.g., 'slacker', 'idiot' used casually).** Only return 'is_bad': true if the message clearly violates core safety policies.
# Return ONLY a single-line JSON object:
# {{"is_bad": [true/false], "bad_word": "[The offensive word or phrase, or None]"}}
# Text to analyze: "{message}"
# """
# )

# # 🟡 MEDIUM PROMPT: Moderate filtering, catches common toxicity.
# MEDIUM_PROMPT = (
#     """Analyze the following text for toxicity, hate speech, serious abuse, or a harmful/inappropriate url.
# **Treat minor insults (e.g., 'stupid', 'slacker') as harmful if repeated or clearly directed as an attack, but ignore simple playful sarcasm or non-hostile disagreement.** Only return 'is_bad': true if the content is clearly toxic or abusive.
# Return ONLY a single-line JSON object:
# {{"is_bad": [true/false], "bad_word": "[The offensive word or phrase, or None]"}}
# Text to analyze: "{message}"
# """
# )

# # 🔴 HIGH (STRICT) PROMPT: Catches any form of toxicity, including mild insults and harsh language.
# STRICT_PROMPT = (
#     """Analyze the following text for **ANY** toxicity, **ANY** hate speech, or **ANY** abuse in any language or a harmful/inappropriate url.
# **Flag all insults, even mild ones (e.g., 'slacker', 'idiot'), and harsh, non-friendly language.** Return 'is_bad': true if the content is toxic, abusive, or uses vulgarity.
# Return ONLY a single-line JSON object:
# {{"is_bad": [true/false], "bad_word": "[The offensive word or phrase, or None]"}}
# Text to analyze: "{message}"
# """
# )

# # --- MAP THE CURRENT MODE TO THE CORRECT PROMPT ---
# LLM_PROMPT_MAP = {
#     "low": MILD_PROMPT,
#     "mid": MEDIUM_PROMPT,
#     "high": STRICT_PROMPT,
#     "warden": STRICT_PROMPT, # Warden mode uses the strictest prompt
# }

# # --- 2. POSTGRES DATABASE CONFIGURATION ---
# PG_HOST = os.environ.get("PGHOST")
# PG_DATABASE = os.environ.get("PGDATABASE")
# PG_USER = os.environ.get("PGUSER")
# PG_PASSWORD = os.environ.get("PGPASSWORD")
# PG_PORT = os.environ.get("PGPORT", "5432")

# LOCAL_PROFANITY_SET = set()
# LOCAL_ALLOW_SET = set()

# def get_db_connection():
#     # ... (DB functions remain the same) ...
#     if not PG_HOST:
#         raise ConnectionError("PGHOST environment variable is not set. Cannot connect to DB.")
    
#     return psycopg2.connect(
#         host=PG_HOST, 
#         database=PG_DATABASE, 
#         user=PG_USER, 
#         password=PG_PASSWORD, 
#         port=PG_PORT
#     )

# def initialize_db(conn):
#     print("⏳ Initializing database tables...")
#     with conn.cursor() as cur:
#         cur.execute("""
#             CREATE TABLE IF NOT EXISTS blocked_words (
#                 word TEXT PRIMARY KEY,
#                 added_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
#             );
#         """)
#         cur.execute("""
#             CREATE TABLE IF NOT EXISTS allowed_words (
#                 word TEXT PRIMARY KEY,
#                 added_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
#             );
#         """)
#     conn.commit()
#     print("✅ Database tables initialized.")

# def load_data_from_db():
#     global LOCAL_PROFANITY_SET, LOCAL_ALLOW_SET
    
#     if not PG_HOST:
#         print("⚠️ WARNING: PGHOST is not set. Assuming local/dummy mode.")
#         return True 
    
#     try:
#         conn = get_db_connection()
#         initialize_db(conn) 
        
#         with conn.cursor() as cur:
#             cur.execute("SELECT word FROM blocked_words;")
#             LOCAL_PROFANITY_SET = {row[0] for row in cur.fetchall()}
#             cur.execute("SELECT word FROM allowed_words;")
#             LOCAL_ALLOW_SET = {row[0] for row in cur.fetchall()}
            
#         conn.close()
#         print("✅ Data successfully loaded from PostgreSQL.")
#         return True
#     except ConnectionError as ce:
#         print(f"❌ FATAL DB ERROR: {ce}")
#         return False
#     except Exception as e:
#         print(f"❌ FATAL DB ERROR: Failed to connect or load data: {e}")
#         return False

# # --- 3. CORE LLM CALL FUNCTIONS & LEARNING LOGIC ---

# def call_perplexity(api_key, model_name, prompt):
#     # ... (Perplexity function remains the same) ...
#     url = "https://api.perplexity.ai/chat/completions"
#     headers = {
#         "Authorization": f"Bearer {api_key}",
#         "Content-Type": "application/json"
#     }
#     data = {
#         "model": model_name,
#         "messages": [{"role": "user", "content": prompt}],
#         "max_tokens": MAX_OUTPUT_TOKENS
#     }
#     try:
#         response = requests.post(url, headers=headers, data=json.dumps(data))
#         response.raise_for_status() 
#         content = response.json()['choices'][0]['message']['content']
#         print("✅ Perplexity call successful.")
#         return content
#     except requests.exceptions.HTTPError as http_err:
#         print(f"❌ PERPLEXITY HTTP ERROR (Code {http_err.response.status_code}): {http_err.response.text}")
#     except Exception as e:
#         print(f"❌ PERPLEXITY GENERAL ERROR: {e}")
    
#     return None 

# def call_gemini(api_key, model_name, prompt):
#     # ... (Gemini function remains the same) ...
#     try:
#         client = genai.Client(api_key=api_key)
#         config = {"max_output_tokens": MAX_OUTPUT_TOKENS} 
        
#         response = client.models.generate_content(
#             model=model_name,
#             contents=prompt,
#         )
#         content = getattr(response, 'text', None)
#         print("✅ Gemini call successful.")
#         return content
#     except Exception as e:
#         print(f"❌ GEMINI ERROR: {e}")
#         pass
#     return None

# # 🛑 FIX: Added 'current_mode' parameter and removed global usage
# def process_llm_response(message, llm_output, current_mode):
    
#     if not llm_output:
#         return None
        
#     print(f"LLM Raw Output: {llm_output}")
#     try:
#         json_match = re.search(r'\{.*\}', llm_output, re.DOTALL)
#         data = json.loads(json_match.group(0) if json_match else llm_output)

#         is_bad = data.get('is_bad')
#         bad_word = data.get('bad_word', 'None')
        
#         if is_bad is True:
#             # 🛑 FIX: Use the passed 'current_mode'
#             if current_mode in ["high", "warden"]: 
#                 if bad_word and bad_word.lower() != 'none':
#                     word_to_block = bad_word.lower().strip()
#                     if word_to_block and word_to_block not in LOCAL_PROFANITY_SET:
                        
#                         try:
#                             conn = get_db_connection()
#                             with conn.cursor() as cur:
#                                 cur.execute(
#                                     "INSERT INTO blocked_words (word) VALUES (%s) ON CONFLICT (word) DO NOTHING;",
#                                     (word_to_block,)
#                                 )
#                             conn.commit()
#                             conn.close()
#                             LOCAL_PROFANITY_SET.add(word_to_block) 
#                             # 🛑 FIX: Use the passed 'current_mode' in print
#                             print(f"🚨 LEARNING: Added '{word_to_block}' to blocked_words DB (Mode: {current_mode}).")
#                         except Exception as e:
#                             print(f"❌ DB WRITE ERROR: Failed to insert blocked word: {e}")
#                 else:
#                     # 🛑 FIX: Use the passed 'current_mode' in print
#                     print(f"🚫 LEARNING SKIPPED: Blocked word not added to DB (Mode: {current_mode}).")
                        
#             return True 
            
#         elif is_bad is False:
#             # 🛑 FIX: Use the passed 'current_mode'
#             if current_mode in ["low", "warden"]:
#                 words_to_allow = set(re.split(r'\s|\W', message.lower()))
#                 words_to_allow.discard('')
                
#                 words_to_insert = []
                
#                 for word in words_to_allow:
#                     if word and word not in LOCAL_ALLOW_SET:
#                         words_to_insert.append((word,))
#                         LOCAL_ALLOW_SET.add(word) 
                        
#                 if words_to_insert:
#                     try:
#                         conn = get_db_connection()
#                         with conn.cursor() as cur:
#                             cur.executemany(
#                                 "INSERT INTO allowed_words (word) VALUES (%s) ON CONFLICT (word) DO NOTHING;",
#                                 words_to_insert
#                             )
#                             conn.commit()
#                             conn.close()
#                             # 🛑 FIX: Use the passed 'current_mode' in print
#                             print(f"👍 LEARNING: Added {len(words_to_insert)} unique words to allowed_words DB (Mode: {current_mode}).")
#                     except Exception as e:
#                             print(f"❌ DB WRITE ERROR: Failed to insert allowed words: {e}")
#                 else:
#                     # 🛑 FIX: Use the passed 'current_mode' in print
#                     print(f"💡 LEARNING SKIPPED: Allowed words not added to DB (Mode: {current_mode}).")

#             return False 

#     except (json.JSONDecodeError, AttributeError) as e:
#         print(f"❌ ERROR: Failed to parse LLM JSON: {e}")
    
#     return None 

# # --- 4. TIERED MODERATION LOGIC ---

# # Utility functions remain the same
# def has_mod_role(member: discord.Member):
#     return any(role.name in MOD_ROLES or role.name in ADMIN_ROLES for role in member.roles)

# def is_admin(member: discord.Member):
#     return any(role.name in ADMIN_ROLES for role in member.roles)

# def check_tier_0_rate_limit(user_id):
#     # ... (Rate limit function remains the same) ...
#     current_time = time.time()
    
#     if user_id not in USER_MESSAGE_LOG:
#         USER_MESSAGE_LOG[user_id] = []
        
#     USER_MESSAGE_LOG[user_id] = [
#         t for t in USER_MESSAGE_LOG[user_id] 
#         if t > current_time - RATE_LIMIT_WINDOW_SECONDS
#     ]
    
#     is_spamming = len(USER_MESSAGE_LOG[user_id]) >= MAX_MESSAGES_PER_WINDOW
    
#     USER_MESSAGE_LOG[user_id].append(current_time)
    
#     return is_spamming 

# def check_tier_0_allow(message_content, allow_set):
#     if message_content.lower().strip() in allow_set:
#         return "T0.1: Exact Match on Allow List (Basic Conversation)"
#     return None

# def check_tier_0_all_words(message_content, allow_set):
#     words = set(re.split(r'\s|\W', message_content.lower()))
#     words.discard('')
#     if not words: return None
    
#     unknown_words = words - allow_set
#     if not unknown_words:
#         return "T0.2: All words are known safe words (Bypassing LLM)"
#     return None

# def check_tier_1_spam(message_content):
#     if len(message_content) > 1000:
#         return "T1: Max Length Exceeded (>1000 chars)"

#     clean_content = re.sub(r'<[#@!&]?[0-9a-zA-Z:]+>', '', message_content) 
#     clean_content = re.sub(r'https?:\/\/\S+', '', clean_content).strip()

#     if len(clean_content) >= 10:
#         alpha_count = sum(c.isalpha() for c in clean_content)
#         if len(clean_content) > 0 and alpha_count / len(clean_content) < 0.10:
#             return "T1: Numeric/Symbol Spam (>90% non-alpha)"
            
#     if re.search(r'(.)\1{8,}', message_content, re.IGNORECASE):
#         return "T1: Excessive Character Repetition"
    
#     return None

# def check_tier_2_profanity(message_content, profanity_set):
#     normalized_message = message_content.lower()
#     words = set(re.split(r'\s|\W', normalized_message))
    
#     for word in words:
#         if word in profanity_set: return f"T2: Keyword Found ({word})"
        
#     simplified_message = re.sub(r'[^a-z0-9]', '', normalized_message)
#     if simplified_message in profanity_set: return f"T2: Simplified Keyword Match"
#     return None

# # --- 5. THE CORE MODERATION PIPELINE ---

# def run_moderation_pipeline(message):
#     if message.guild is None: 
#         # Cannot moderate DMs or messages without a guild context
#         return False
        
#     message_content = message.content
#     # 🛑 FIX: Get the mode for the specific guild
#     current_strictness_mode = get_current_mode(message.guild.id) 

#     print(f"\n========================================================")
#     # 🛑 FIX: Use the specific guild mode in log
#     print(f"✉️ Analyzing Message: \"{message_content}\" by {message.author.name} (Mode: {current_strictness_mode.upper()})")
#     print("========================================================")
    
#     # Check for Warden Mode access (using is_admin for the specific request)
#     # 🛑 FIX: Use the specific guild mode for warden check
#     if current_strictness_mode == "warden" and not is_admin(message.author):
#         print("🚫 BLOCKED: T0.3 Warden Mode Active.")
#         return True

#     if check_tier_0_rate_limit(message.author.id):
#         return True 

#     t0_result = check_tier_0_allow(message_content, LOCAL_ALLOW_SET)
#     if t0_result:
#         print(f"🛑 ALLOWED: {t0_result}")
#         return False
    
#     t1_result = check_tier_1_spam(message_content)
#     if t1_result:
#         print(f"🚫 BLOCKED: {t1_result}")
#         return True 
    
#     t2_result = check_tier_2_profanity(message_content, LOCAL_PROFANITY_SET)
#     if t2_result:
#         print(f"🚫 BLOCKED: {t2_result}")
#         return True 
        
#     t0_all_words_result = check_tier_0_all_words(message_content, LOCAL_ALLOW_SET)
#     if t0_all_words_result:
#         print(f"🛑 ALLOWED: {t0_all_words_result}")
#         return False
    
#     print("✔️ Tiers 0-2 Passed. Proceeding to LLM Nuance Check (Token Used)...")
    
#     # 🌟 FIX: SELECT THE PROMPT BASED ON THE CURRENT GUILD MODE
#     selected_prompt_template = LLM_PROMPT_MAP.get(current_strictness_mode.lower(), MILD_PROMPT)
#     llm_prompt = selected_prompt_template.format(message=message_content)
#     llm_response_content = None

#     llm_response_content = call_perplexity(PERPLEXITY_API_KEY, PERPLEXITY_MODEL, llm_prompt)
#     if not llm_response_content:
#         llm_response_content = call_gemini(GEMINI_API_KEY, GEMINI_MODEL, llm_prompt)
    
#     # 🛑 FIX: Pass the current_strictness_mode to process_llm_response
#     llm_status = process_llm_response(message_content, llm_response_content, current_strictness_mode)
    
#     if llm_status is True:
#         return True 
#     elif llm_status is False:
#         print("\n✅ Moderation Complete (LLM Allowed/Learned).")
#         return False 
#     else:
#         print("\n⚠️ WARNING: LLM failed. Defaulting to ALLOW to prevent false positive.")
#         return False

# # --- 6. DISCORD BOT IMPLEMENTATION (Plain Client) and COMMANDS ---

# # 🌟 KEY FIX: Inherit from commands.Bot 🌟
# class ModBotClient(commands.Bot):
#     def __init__(self, command_prefix, *, intents: discord.Intents):
#         super().__init__(command_prefix=command_prefix, intents=intents)
#         self.deletion_lock = asyncio.Lock() 

#     async def on_ready(self):
#         # 🛑 FIX: Initialize GUILD_STRICTNESS_MODES for allowed guilds
#         for guild in self.guilds:
#             if guild.id in ALLOWED_SERVERS and guild.id not in GUILD_STRICTNESS_MODES:
#                 GUILD_STRICTNESS_MODES[guild.id] = "low" # Default mode on startup
                
#         print('-------------------------------------------')
#         print(f'🤖 Bot Logged in as {self.user} (ID: {self.user.id})')
#         print(f'✅ LOCAL_ALLOW_SET size: {len(LOCAL_ALLOW_SET)}')
#         print(f'❌ LOCAL_PROFANITY_SET size: {len(LOCAL_PROFANITY_SET)}')
#         print(f'⏱️ RATE LIMIT: {MAX_MESSAGES_PER_WINDOW} msgs / {RATE_LIMIT_WINDOW_SECONDS}s')
#         # 🛑 FIX: Use a generic mode status since it's per-guild now
#         print(f'⚙️ MODE STATUS: Configured for {len(GUILD_STRICTNESS_MODES)} guilds (Default: LOW)')
#         print('-------------------------------------------')

#         unauthorized_guilds = []
#         for guild in self.guilds:
#             if guild.id not in ALLOWED_SERVERS:
#                 unauthorized_guilds.append(guild.name)
#                 await guild.leave()
            
#         if unauthorized_guilds:
#             print(f"🚫 CLEANUP: Left the following unauthorized guilds on startup: {', '.join(unauthorized_guilds)}")

#         # Use a generic activity status
#         await self.change_presence(activity=discord.Game(name=f"AI Moderation"))

#     async def on_message(self, message: discord.Message):
#         """Called every time a message is sent."""
        
#         if message.author == self.user or message.author.bot or message.guild is None:
#             return
            
#         # The commands.Bot class handles commands by itself if the message is NOT a command.
#         # We need to process commands FIRST using the parent class's logic.
#         if message.content.startswith(self.command_prefix):
#             await self.process_commands(message)
#             return

#         # 1. 🛡️ RUN THE TIERED MODERATION PIPELINE
#         is_blocked = run_moderation_pipeline(message)
        
#         # 🛑 FIX: Get the mode for the specific guild to use in the warning message
#         current_mode_for_warning = get_current_mode(message.guild.id)


#         if is_blocked:
#             user_log = USER_MESSAGE_LOG.get(message.author.id, [])
            
#             if len(user_log) > MAX_MESSAGES_PER_WINDOW: 
                
#                 async with self.deletion_lock:
#                     # --- ACTION: RATE LIMIT SPAM BLOCK + TIMEOUT ---
#                     deleted_count = 0
#                     print(f"🧹 Attempting BULK delete of spam messages from {message.author.name}...")

#                     try:
#                         deleted_msgs = await message.channel.purge(
#                             limit=MAX_MESSAGES_PER_WINDOW + 5,
#                             check=lambda m: m.author.id == message.author.id and (time.time() - m.created_at.timestamp() < RATE_LIMIT_WINDOW_SECONDS)
#                         )
#                         deleted_count = len(deleted_msgs)
#                         print(f"✅ BULK DELETE: Successfully deleted {deleted_count} messages.")

#                     except discord.errors.Forbidden:
#                         print(f"❌ ERROR: Bot lacks 'Manage Messages' permission for BULK deletion.")
#                     except Exception as e:
#                         print(f"⚠️ WARNING: An error occurred during purge: {e}")
                
#                     try:
#                         member: discord.Member = message.author
#                         timeout_until = discord.utils.utcnow() + datetime.timedelta(seconds=TIMEOUT_DURATION_SECONDS)
#                         await member.edit(timed_out_until=timeout_until, reason="Automatic Spam Detection (Rate Limit Exceeded)")
                        
#                         warning_msg = f"⏱️ **{message.author.mention}** has been timed out for **{TIMEOUT_DURATION_SECONDS} seconds** due to **message spamming** (Deleted {deleted_count} messages)."
#                         await message.channel.send(warning_msg, delete_after=15)
#                         print(f"🚫 ACTION: T0.0 Rate Limit BLOCKED. User {message.author.name} timed out for {TIMEOUT_DURATION_SECONDS}s.")
                        
#                     except discord.errors.Forbidden:
#                         print(f"❌ ERROR: Bot does not have 'Moderate Members' (Timeout) permission.")
                
#             else:
#                 # --- ACTION: CONTENT-BASED BLOCK (T1, T2, T3, Warden) ---
#                 try:
#                     await message.delete() 
#                     # 🛑 FIX: Use the specific guild mode in the warning message
#                     warning_message = f"🚫 **{message.author.mention}**, your message was automatically removed due to moderation policies (Content Check). Mode: {current_mode_for_warning.upper()}"
#                     await message.channel.send(warning_message, delete_after=10)
#                 except discord.errors.Forbidden:
#                     print(f"❌ ERROR: Bot does not have 'Manage Messages' permission.")


# # Commands are still registered to the global 'bot' object, but we will pass its 
# # command list to the new ModBotClient instance before running.

# @bot.event # This event still works on the global 'bot' instance
# async def on_guild_join(guild):
#     """3. 🛡️ CHECK ON NEW INVITE"""
#     if guild.id not in ALLOWED_SERVERS:
#         print(f"❌ UNAUTHORIZED JOIN: Leaving Guild '{guild.name}' (ID: {guild.id})")
#         await guild.leave()
#     else:
#         # 🛑 FIX: Set the default mode for the newly joined guild
#         GUILD_STRICTNESS_MODES[guild.id] = "low"
#         print(f"✅ ALLOWED JOIN: Staying in Guild '{guild.name}' (ID: {guild.id}). Mode set to default 'low'.")

# # 🌟 CUSTOM CHECK (Adjusted for Admin/Owner Only) 🌟
# def admin_only_check():
#     """Custom check to ensure the command is run only by an Admin or Bot Owner."""
#     async def predicate(ctx):
#         # The check must use the global is_admin function
#         if not is_admin(ctx.author): 
#             await ctx.send("🚫 You must be an **Admin** or **Bot Owner** to change the strictness mode.", delete_after=10)
#             return False
#         # Additionally, ensure it's in a guild
#         if ctx.guild is None:
#             await ctx.send("🚫 This command can only be run inside a server.", delete_after=10)
#             return False
#         return True
#     return commands.check(predicate)

# @bot.command(name='low')
# @admin_only_check()
# async def set_low_mode(ctx):
#     # 🛑 FIX: Set the mode for the specific guild
#     GUILD_STRICTNESS_MODES[ctx.guild.id] = "low"
#     await ctx.send("🟢 Strictness mode set to **!low** (Mild). Learning **Allowed** words is **ON**. Blocking learning is OFF.")
#     # Removed global change_presence, as mode is now per-guild

# @bot.command(name='mid')
# @admin_only_check()
# async def set_mid_mode(ctx):
#     # 🛑 FIX: Set the mode for the specific guild
#     GUILD_STRICTNESS_MODES[ctx.guild.id] = "mid"
#     await ctx.send("🟡 Strictness mode set to **!mid** (Medium). **No new words** are learned or saved to the database.")
#     # Removed global change_presence

# @bot.command(name='high')
# @admin_only_check()
# async def set_high_mode(ctx):
#     # 🛑 FIX: Set the mode for the specific guild
#     GUILD_STRICTNESS_MODES[ctx.guild.id] = "high"
#     await ctx.send("🔴 Strictness mode set to **!high** (Strict). Learning **Blocked** words is **ON**. Allowing learning is OFF.")
#     # Removed global change_presence

# @bot.command(name='warden')
# @admin_only_check()
# async def set_warden_mode(ctx):
#     # 🛑 FIX: Set the mode for the specific guild
#     GUILD_STRICTNESS_MODES[ctx.guild.id] = "warden"
#     await ctx.send("⚫ Strictness mode set to **!warden** (Max Security). **All learning** is **ON**, and **non-admin/non-owner messages** are **instantly blocked**.")
#     # Removed global change_presence
    
# @bot.command(name='status')
# async def get_status(ctx):
#     if ctx.guild is None:
#         await ctx.send("🚫 This command can only be run inside a server.")
#         return
        
#     # 🛑 FIX: Get the mode for the specific guild
#     current_mode = get_current_mode(ctx.guild.id)
    
#     embed = discord.Embed(title=f"🤖 Moderation Bot Status - {ctx.guild.name}", color=0x00ff00)
#     embed.add_field(name="Current Mode", value=f"**{current_mode.upper()}**", inline=False)
    
#     if current_mode == "low":
#         desc = "Mild Security. Learns **Allowed** words from non-toxic messages (Self-correction)."
#     elif current_mode == "mid":
#         desc = "Standard Security. No word learning is performed (Stable Operation)."
#     elif current_mode == "high":
#         desc = "Strict Security. Learns **Blocked** words from toxic messages (Data Collection)."
#     elif current_mode == "warden":
#         desc = "**MAX SECURITY**. Learns **both** allowed and blocked words. **Blocks all non-Admin/Owner messages.**"
#     else:
#         desc = "Unknown mode (Defaulting to LOW)."

#     embed.add_field(name="Mode Description", value=desc, inline=False)
#     embed.add_field(name="Profanity List Size", value=f"{len(LOCAL_PROFANITY_SET)} words", inline=True)
#     embed.add_field(name="Allow List Size", value=f"{len(LOCAL_ALLOW_SET)} words", inline=True)
#     await ctx.send(embed=embed)


# # --- EXECUTION ---
# if __name__ == "__main__":
#     try:
#         if not load_data_from_db():
#             print("❌ FATAL: Bot failed to initialize database connection/data loading. Exiting.")
#         elif not DISCORD_BOT_TOKEN:
#             print("❌ FATAL ERROR: DISCORD_BOT_TOKEN environment variable is not set. Exiting.")
#         else:
            
#             # 🌟 KEY FIX: Instantiate ModBotClient (which is now commands.Bot) 
#             # and pass the prefix and intents.
#             client_runner = ModBotClient(command_prefix='!', intents=intents)
            
#             if not GEMINI_API_KEY or not PERPLEXITY_API_KEY:
#                 print("⚠️ WARNING: One or more LLM API keys are missing. LLM checks will fail.")
            
#             # 🌟 KEY FIX: TRANSFER COMMANDS TO THE NEW BOT INSTANCE 🌟
#             # We must manually transfer the commands registered on the temporary 'bot' 
#             # object to the final 'client_runner' object, which is now the actual bot.
#             for command in bot.commands:
#                 client_runner.add_command(command)

#             # NOTE: We can now use client_runner.run() because it is a commands.Bot instance.
#             client_runner.run(DISCORD_BOT_TOKEN)
            
#     except ConnectionError:
#         print("❌ FATAL: Cannot run without PostgreSQL configuration.")
#     except Exception as e:
#         print(f"❌ FATAL UNCAUGHT ERROR: {e}")








import os
import json
import re
import requests
from discord.ext import commands
import discord
import time
import datetime 
import asyncio
from google import genai
import psycopg2 
from psycopg2 import sql 
try:
    from google.generativeai import APIError as GeminiAPIError
except Exception:
    class GeminiAPIError(Exception):
        pass

# --- 0. DISCORD CONFIGURATION ---
ALLOWED_SERVERS = {1439561356960464979,1442817806344126496}
DISCORD_BOT_TOKEN = os.environ.get("DISCORD_BOT_TOKEN")
# Set intents for the bot (crucial for message content)
intents = discord.Intents.default()
intents.message_content = True 
intents.members = True 

# --- COMMAND ROLES CONFIGURATION ---
MOD_ROLES = ["Admin", "Moderator"]
ADMIN_ROLES = ["Admin", "Bot Owner"] 

# --- RATE LIMITING CONFIGURATION (TIER 0) ---
MAX_MESSAGES_PER_WINDOW = 5 
RATE_LIMIT_WINDOW_SECONDS = 5 
TIMEOUT_DURATION_SECONDS = 120 
USER_MESSAGE_LOG = {} 

# --- 1. CONFIGURATION ---
# We keep this for command registration until the class is defined
bot = commands.Bot(command_prefix='!', intents=intents,help_command=None)

# Stores {guild_id: "low" | "mid" | "high" | "warden"}
GUILD_STRICTNESS_MODES = {} 

# LLM Keys & Models
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY") 
PERPLEXITY_API_KEY = os.environ.get("PERPLEXITY_API_KEY")
GEMINI_MODEL = "gemini-2.5-flash"
PERPLEXITY_MODEL = "sonar"
MAX_OUTPUT_TOKENS = 30 

# Utility function to get the current mode for a guild
def get_current_mode(guild_id):
    """Retrieves the strictness mode for a specific guild, defaulting to 'low'."""
    # Use .get() with a default value to ensure we always return a valid mode
    return GUILD_STRICTNESS_MODES.get(guild_id, "low")


# 🟢 LOW (MILD) PROMPT: Ignores minor insults (The desired mild prompt)
MILD_PROMPT = (
    """First, **DETECT THE LANGUAGE** of the following text and use that language context for the analysis. Analyze the text for **EXTREME SEVERE** toxicity, **EXTREME HATE SPEECH**, graphic content, **EXTREME serious abuse**, or a EXTREME harmful/inappropriate url.
**Ignore insults, mild teasing, sarcasm, and conversational disagreements or non-severe terms (e.g., 'slacker', 'idiot' used casually).** Only return 'is_bad': true if the message clearly violates core safety policies **in the detected language.**
Return ONLY a single-line JSON object:
{{"is_bad": [true/false], "bad_word": "[The offensive word or phrase, or None]"}}
Text to analyze: "{message}"
"""
)

# 🟡 MEDIUM PROMPT: Moderate filtering, catches common toxicity.
MEDIUM_PROMPT = (
    """First, **DETECT THE LANGUAGE** of the following text and use that language context for the analysis. Analyze the text for toxicity, hate speech, serious abuse, or a harmful/inappropriate url.
**Treat minor insults (e.g., 'stupid', 'slacker') as harmful if repeated or clearly directed as an attack, but ignore simple playful sarcasm or non-hostile disagreement.** Only return 'is_bad': true if the content is clearly toxic or abusive **in the detected language.**
Return ONLY a single-line JSON object:
{{"is_bad": [true/false], "bad_word": "[The offensive word or phrase, or None]"}}
Text to analyze: "{message}"
"""
)

# 🔴 HIGH (STRICT) PROMPT: Catches any form of toxicity, including mild insults and harsh language.
STRICT_PROMPT = (
    """First, **DETECT THE LANGUAGE** of the following text and use that language context for the analysis. Analyze the text for **ANY** toxicity, **ANY** hate speech, or **ANY** abuse in any language or a harmful/inappropriate url.
**Flag all insults, even mild ones (e.g., 'slacker', 'idiot'), and harsh, non-friendly language.** Return 'is_bad': true if the content is toxic, abusive, or uses vulgarity **in the detected language.**
Return ONLY a single-line JSON object:
{{"is_bad": [true/false], "bad_word": "[The offensive word or phrase, or None]"}}
Text to analyze: "{message}"
"""
)

# --- MAP THE CURRENT MODE TO THE CORRECT PROMPT ---
LLM_PROMPT_MAP = {
    "low": MILD_PROMPT,
    "mid": MEDIUM_PROMPT,
    "high": STRICT_PROMPT,
    "warden": STRICT_PROMPT, # Warden mode uses the strictest prompt
}

# --- 2. POSTGRES DATABASE CONFIGURATION ---
PG_HOST = os.environ.get("PGHOST")
PG_DATABASE = os.environ.get("PGDATABASE")
PG_USER = os.environ.get("PGUSER")
PG_PASSWORD = os.environ.get("PGPASSWORD")
PG_PORT = os.environ.get("PGPORT", "5432")

LOCAL_PROFANITY_SET = set()
LOCAL_ALLOW_SET = set()

def get_db_connection():
    if not PG_HOST:
        raise ConnectionError("PGHOST environment variable is not set. Cannot connect to DB.")
    
    return psycopg2.connect(
        host=PG_HOST, 
        database=PG_DATABASE, 
        user=PG_USER, 
        password=PG_PASSWORD, 
        port=PG_PORT
    )

def initialize_db(conn):
    print("⏳ Initializing database tables...")
    with conn.cursor() as cur:
        cur.execute("""
            CREATE TABLE IF NOT EXISTS blocked_words (
                word TEXT PRIMARY KEY,
                added_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
            );
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS allowed_words (
                word TEXT PRIMARY KEY,
                added_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
            );
        """)
    conn.commit()
    print("✅ Database tables initialized.")

def load_data_from_db():
    global LOCAL_PROFANITY_SET, LOCAL_ALLOW_SET
    
    if not PG_HOST:
        print("⚠️ WARNING: PGHOST is not set. Assuming local/dummy mode.")
        return True 
    
    try:
        conn = get_db_connection()
        initialize_db(conn) 
        
        with conn.cursor() as cur:
            cur.execute("SELECT word FROM blocked_words;")
            LOCAL_PROFANITY_SET = {row[0] for row in cur.fetchall()}
            cur.execute("SELECT word FROM allowed_words;")
            LOCAL_ALLOW_SET = {row[0] for row in cur.fetchall()}
            
        conn.close()
        print("✅ Data successfully loaded from PostgreSQL.")
        return True
    except ConnectionError as ce:
        print(f"❌ FATAL DB ERROR: {ce}")
        return False
    except Exception as e:
        print(f"❌ FATAL DB ERROR: Failed to connect or load data: {e}")
        return False

# --- 3. CORE LLM CALL FUNCTIONS & LEARNING LOGIC (Synchronous) ---

def call_perplexity(api_key, model_name, prompt):
    """Synchronous call to Perplexity API using requests."""
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
        # requests.post is a synchronous/blocking call
        response = requests.post(url, headers=headers, data=json.dumps(data), timeout=10) # Added timeout
        response.raise_for_status() 
        content = response.json()['choices'][0]['message']['content']
        print("✅ Perplexity call successful.")
        return content
    except requests.exceptions.HTTPError as http_err:
        print(f"❌ PERPLEXITY HTTP ERROR (Code {http_err.response.status_code}): {http_err.response.text}")
    except Exception as e:
        print(f"❌ PERPLEXITY GENERAL ERROR: {e}")
    
    return None 

def call_gemini(api_key, model_name, prompt):
    """Synchronous call to Gemini API using google-genai client."""
    try:
        # The genai client call is synchronous/blocking
        client = genai.Client(api_key=api_key)
        config = {"max_output_tokens": MAX_OUTPUT_TOKENS} 
        
        response = client.models.generate_content(
            model=model_name,
            contents=prompt,
        )
        content = getattr(response, 'text', None)
        print("✅ Gemini call successful.")
        return content
    except Exception as e:
        print(f"❌ GEMINI ERROR: {e}")
        pass
    return None

# Database write utility (Synchronous)
def insert_blocked_word_sync(word_to_block):
    try:
        conn = get_db_connection()
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO blocked_words (word) VALUES (%s) ON CONFLICT (word) DO NOTHING;",
                (word_to_block,)
            )
        conn.commit()
        conn.close()
        LOCAL_PROFANITY_SET.add(word_to_block) 
        return True
    except Exception as e:
        print(f"❌ DB WRITE ERROR: Failed to insert blocked word: {e}")
        return False

# Database write utility (Synchronous)
def insert_allowed_words_sync(words_to_insert):
    if not words_to_insert:
        return True
    try:
        conn = get_db_connection()
        with conn.cursor() as cur:
            cur.executemany(
                "INSERT INTO allowed_words (word) VALUES (%s) ON CONFLICT (word) DO NOTHING;",
                words_to_insert
            )
            conn.commit()
        conn.close()
        # Update LOCAL_ALLOW_SET outside of the DB interaction
        for word_tuple in words_to_insert:
            LOCAL_ALLOW_SET.add(word_tuple[0])
        return len(words_to_insert)
    except Exception as e:
        print(f"❌ DB WRITE ERROR: Failed to insert allowed words: {e}")
        return 0

# 🛑 KEY FIX: ALL LLM/DB INTERACTION IS NOW HANDLED ASYNCHRONOUSLY 🛑
async def process_llm_response(message, llm_output, current_mode):
    """Processes LLM output and handles asynchronous DB learning."""
    
    if not llm_output:
        return None
        
    print(f"LLM Raw Output: {llm_output}")
    try:
        json_match = re.search(r'\{.*\}', llm_output, re.DOTALL)
        # Attempt to clean up and parse the JSON response
        data_str = json_match.group(0) if json_match else llm_output.strip()
        data = json.loads(data_str)

        is_bad = data.get('is_bad')
        bad_word = data.get('bad_word', 'None')
        
        if is_bad is True:
            if current_mode in ["high", "warden"]: 
                if bad_word and bad_word.lower() != 'none':
                    word_to_block = bad_word.lower().strip()
                    if word_to_block and word_to_block not in LOCAL_PROFANITY_SET:
                        
                        # 🛑 ASYNC DB WRITE: Blocked Word
                        success = await asyncio.to_thread(insert_blocked_word_sync, word_to_block)
                        
                        if success:
                            print(f"🚨 LEARNING: Added '{word_to_block}' to blocked_words DB (Mode: {current_mode}).")
                        else:
                            print(f"❌ LEARNING FAILED: DB write failed for blocked word.")
                else:
                    print(f"🚫 LEARNING SKIPPED: Blocked word not added to DB (Mode: {current_mode}).")
                            
            return True 
            
        elif is_bad is False:
            if current_mode in ["low", "warden"]:
                words_to_allow = set(re.split(r'\s|\W', message.lower()))
                words_to_allow.discard('')
                
                words_to_insert = []
                for word in words_to_allow:
                    if word and word not in LOCAL_ALLOW_SET:
                        words_to_insert.append((word,))
                        
                if words_to_insert:
                    # 🛑 ASYNC DB WRITE: Allowed Words
                    count = await asyncio.to_thread(insert_allowed_words_sync, words_to_insert)

                    if count > 0:
                        print(f"👍 LEARNING: Added {count} unique words to allowed_words DB (Mode: {current_mode}).")
                    else:
                        print(f"❌ LEARNING FAILED: DB write failed for allowed words.")

                else:
                    print(f"💡 LEARNING SKIPPED: Allowed words not added to DB (Mode: {current_mode}).")

            return False 

    except (json.JSONDecodeError, AttributeError, ValueError) as e:
        print(f"❌ ERROR: Failed to parse LLM JSON or unexpected value: {e}. Raw Output: {llm_output}")
    
    return None 

# --- 4. TIERED MODERATION LOGIC ---

# Utility functions remain the same
def has_mod_role(member: discord.Member):
    return any(role.name in MOD_ROLES or role.name in ADMIN_ROLES for role in member.roles)

def is_admin(member: discord.Member):
    return any(role.name in ADMIN_ROLES for role in member.roles)

def check_tier_0_rate_limit(user_id):
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
    if message_content.lower().strip() in allow_set:
        return "T0.1: Exact Match on Allow List (Basic Conversation)"
    return None

def check_tier_0_all_words(message_content, allow_set):
    words = set(re.split(r'\s|\W', message_content.lower()))
    words.discard('')
    if not words: return None
    
    unknown_words = words - allow_set
    if not unknown_words:
        return "T0.2: All words are known safe words (Bypassing LLM)"
    return None

def check_tier_1_spam(message_content):
    if len(message_content) > 1000:
        return "T1: Max Length Exceeded (>1000 chars)"

    clean_content = re.sub(r'<[#@!&]?[0-9a-zA-Z:]+>', '', message_content) 
    clean_content = re.sub(r'https?:\/\/\S+', '', clean_content).strip()

    if len(clean_content) >= 10:
        alpha_count = sum(c.isalpha() for c in clean_content)
        if len(clean_content) > 0 and alpha_count / len(clean_content) < 0.10:
            return "T1: Numeric/Symbol Spam (>90% non-alpha)"
            
    if re.search(r'(.)\1{8,}', message_content, re.IGNORECASE):
        return "T1: Excessive Character Repetition"
    
    return None

def check_tier_2_profanity(message_content, profanity_set):
    normalized_message = message_content.lower()
    words = set(re.split(r'\s|\W', normalized_message))
    
    for word in words:
        if word in profanity_set: return f"T2: Keyword Found ({word})"
        
    simplified_message = re.sub(r'[^a-z0-9]', '', normalized_message)
    if simplified_message in profanity_set: return f"T2: Simplified Keyword Match"
    return None

# --- 5. THE CORE MODERATION PIPELINE (Async) ---

async def run_moderation_pipeline(message):
    """
    Asynchronous moderation pipeline. 
    Synchronous LLM calls are wrapped in asyncio.to_thread().
    """
    if message.guild is None: 
        return False
        
    message_content = message.content
    current_strictness_mode = get_current_mode(message.guild.id) 

    print(f"\n========================================================")
    print(f"✉️ Analyzing Message: \"{message_content}\" by {message.author.name} (Mode: {current_strictness_mode.upper()})")
    print("========================================================")
    
    # Check for Warden Mode access
    if current_strictness_mode == "warden" and not is_admin(message.author):
        print("🚫 BLOCKED: T0.3 Warden Mode Active.")
        return True

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
    
    selected_prompt_template = LLM_PROMPT_MAP.get(current_strictness_mode.lower(), MILD_PROMPT)
    llm_prompt = selected_prompt_template.format(message=message_content)
    llm_response_content = None

    # 🛑 KEY FIX: Wrap synchronous LLM calls in asyncio.to_thread()
    # 1. Try Perplexity first
    llm_response_content = await asyncio.to_thread(
        call_perplexity, PERPLEXITY_API_KEY, PERPLEXITY_MODEL, llm_prompt
    )
    
    # 2. Fallback to Gemini if Perplexity failed
    if not llm_response_content:
        llm_response_content = await asyncio.to_thread(
            call_gemini, GEMINI_API_KEY, GEMINI_MODEL, llm_prompt
        )
    
    # 🛑 KEY FIX: Await the asynchronous process_llm_response
    llm_status = await process_llm_response(message_content, llm_response_content, current_strictness_mode)
    
    if llm_status is True:
        return True 
    elif llm_status is False:
        print("\n✅ Moderation Complete (LLM Allowed/Learned).")
        return False 
    else:
        print("\n⚠️ WARNING: LLM/DB failed. Defaulting to ALLOW to prevent false positive.")
        return False

# --- 6. DISCORD BOT IMPLEMENTATION (Plain Client) and COMMANDS ---

class ModBotClient(commands.Bot):
    def __init__(self, command_prefix, *, intents: discord.Intents):
        super().__init__(command_prefix=command_prefix, intents=intents)
        self.deletion_lock = asyncio.Lock() 

    async def on_ready(self):
        for guild in self.guilds:
            if guild.id in ALLOWED_SERVERS and guild.id not in GUILD_STRICTNESS_MODES:
                GUILD_STRICTNESS_MODES[guild.id] = "low" # Default mode on startup
                
        print('-------------------------------------------')
        print(f'🤖 Bot Logged in as {self.user} (ID: {self.user.id})')
        print(f'✅ LOCAL_ALLOW_SET size: {len(LOCAL_ALLOW_SET)}')
        print(f'❌ LOCAL_PROFANITY_SET size: {len(LOCAL_PROFANITY_SET)}')
        print(f'⏱️ RATE LIMIT: {MAX_MESSAGES_PER_WINDOW} msgs / {RATE_LIMIT_WINDOW_SECONDS}s')
        print(f'⚙️ MODE STATUS: Configured for {len(GUILD_STRICTNESS_MODES)} guilds (Default: LOW)')
        print('-------------------------------------------')

        unauthorized_guilds = []
        for guild in self.guilds:
            if guild.id not in ALLOWED_SERVERS:
                unauthorized_guilds.append(guild.name)
                await guild.leave()
            
        if unauthorized_guilds:
            print(f"🚫 CLEANUP: Left the following unauthorized guilds on startup: {', '.join(unauthorized_guilds)}")

        await self.change_presence(activity=discord.Game(name=f"AI Moderation"))

    async def on_message(self, message: discord.Message):
        """Called every time a message is sent."""
        
        if message.author == self.user or message.author.bot or message.guild is None:
            return
            
        if message.content.startswith(self.command_prefix):
            await self.process_commands(message)
            return

        # 1. 🛡️ RUN THE TIERED MODERATION PIPELINE
        # 🛑 KEY FIX: AWAIT the asynchronous moderation pipeline call
        is_blocked = await run_moderation_pipeline(message)
        
        current_mode_for_warning = get_current_mode(message.guild.id)


        if is_blocked:
            user_log = USER_MESSAGE_LOG.get(message.author.id, [])
            
            if len(user_log) > MAX_MESSAGES_PER_WINDOW: 
                
                async with self.deletion_lock:
                    # --- ACTION: RATE LIMIT SPAM BLOCK + TIMEOUT ---
                    deleted_count = 0
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
                
                    try:
                        member: discord.Member = message.author
                        timeout_until = discord.utils.utcnow() + datetime.timedelta(seconds=TIMEOUT_DURATION_SECONDS)
                        await member.edit(timed_out_until=timeout_until, reason="Automatic Spam Detection (Rate Limit Exceeded)")
                        
                        warning_msg = f"⏱️ **{message.author.mention}** has been timed out for **{TIMEOUT_DURATION_SECONDS} seconds** due to **message spamming** (Deleted {deleted_count} messages)."
                        await message.channel.send(warning_msg, delete_after=15)
                        print(f"🚫 ACTION: T0.0 Rate Limit BLOCKED. User {message.author.name} timed out for {TIMEOUT_DURATION_SECONDS}s.")
                        
                    except discord.errors.Forbidden:
                        print(f"❌ ERROR: Bot does not have 'Moderate Members' (Timeout) permission.")
                
            else:
                # --- ACTION: CONTENT-BASED BLOCK (T1, T2, T3, Warden) ---
                try:
                    await message.delete() 
                    warning_message = f"🚫 **{message.author.mention}**, your message was automatically removed due to moderation policies (Content Check). Mode: {current_mode_for_warning.upper()}"
                    await message.channel.send(warning_message, delete_after=10)
                except discord.errors.Forbidden:
                    print(f"❌ ERROR: Bot does not have 'Manage Messages' permission.")


# Commands are still registered to the global 'bot' object, but we will pass its 
# command list to the new ModBotClient instance before running.

@bot.event # This event still works on the global 'bot' instance
async def on_guild_join(guild):
    """3. 🛡️ CHECK ON NEW INVITE"""
    if guild.id not in ALLOWED_SERVERS:
        print(f"❌ UNAUTHORIZED JOIN: Leaving Guild '{guild.name}' (ID: {guild.id})")
        await guild.leave()
    else:
        GUILD_STRICTNESS_MODES[guild.id] = "low"
        print(f"✅ ALLOWED JOIN: Staying in Guild '{guild.name}' (ID: {guild.id}). Mode set to default 'low'.")

# 🌟 CUSTOM CHECK (Adjusted for Admin/Owner Only) 🌟
def admin_only_check():
    """Custom check to ensure the command is run only by an Admin or Bot Owner."""
    async def predicate(ctx):
        if not is_admin(ctx.author): 
            await ctx.send("🚫 You must be an **Admin** or **Bot Owner** to change the strictness mode.", delete_after=10)
            return False
        if ctx.guild is None:
            await ctx.send("🚫 This command can only be run inside a server.", delete_after=10)
            return False
        return True
    return commands.check(predicate)

@bot.command(name='low')
@admin_only_check()
async def set_low_mode(ctx):
    GUILD_STRICTNESS_MODES[ctx.guild.id] = "low"
    await ctx.send("🟢 Strictness mode set to **!low** (Mild). Learning **Allowed** words is **ON**. Blocking learning is OFF.")

@bot.command(name='mid')
@admin_only_check()
async def set_mid_mode(ctx):
    GUILD_STRICTNESS_MODES[ctx.guild.id] = "mid"
    await ctx.send("🟡 Strictness mode set to **!mid** (Medium). **No new words** are learned or saved to the database.")

@bot.command(name='high')
@admin_only_check()
async def set_high_mode(ctx):
    GUILD_STRICTNESS_MODES[ctx.guild.id] = "high"
    await ctx.send("🔴 Strictness mode set to **!high** (Strict). Learning **Blocked** words is **ON**. Allowing learning is OFF.")

@bot.command(name='warden')
@admin_only_check()
async def set_warden_mode(ctx):
    GUILD_STRICTNESS_MODES[ctx.guild.id] = "warden"
    await ctx.send("⚫ Strictness mode set to **!warden** (Max Security). **All learning** is **ON**, and **non-admin/non-owner messages** are **instantly blocked**.")
    
@bot.command(name='status')
async def get_status(ctx):
    if ctx.guild is None:
        await ctx.send("🚫 This command can only be run inside a server.")
        return
        
    current_mode = get_current_mode(ctx.guild.id)
    
    embed = discord.Embed(title=f"🤖 Moderation Bot Status - {ctx.guild.name}", color=0x00ff00)
    embed.add_field(name="Current Mode", value=f"**{current_mode.upper()}**", inline=False)
    
    if current_mode == "low":
        desc = "Mild Security. Learns **Allowed** words from non-toxic messages (Self-correction)."
    elif current_mode == "mid":
        desc = "Standard Security. No word learning is performed (Stable Operation)."
    elif current_mode == "high":
        desc = "Strict Security. Learns **Blocked** words from toxic messages (Data Collection)."
    elif current_mode == "warden":
        desc = "**MAX SECURITY**. Learns **both** allowed and blocked words. **Blocks all non-Admin/Owner messages.**"
    else:
        desc = "Unknown mode (Defaulting to LOW)."

    embed.add_field(name="Mode Description", value=desc, inline=False)
    embed.add_field(name="Profanity List Size", value=f"{len(LOCAL_PROFANITY_SET)} words", inline=True)
    embed.add_field(name="Allow List Size", value=f"{len(LOCAL_ALLOW_SET)} words", inline=True)
    await ctx.send(embed=embed)


# --- EXECUTION ---
if __name__ == "__main__":
    try:
        if not load_data_from_db():
            print("❌ FATAL: Bot failed to initialize database connection/data loading. Exiting.")
        elif not DISCORD_BOT_TOKEN:
            print("❌ FATAL ERROR: DISCORD_BOT_TOKEN environment variable is not set. Exiting.")
        else:
            
            client_runner = ModBotClient(command_prefix='!', intents=intents)
            
            if not GEMINI_API_KEY or not PERPLEXITY_API_KEY:
                print("⚠️ WARNING: One or more LLM API keys are missing. LLM checks will fail.")
            
            # Transfer commands from the temporary 'bot' object to the final 'client_runner'
            for command in bot.commands:
                client_runner.add_command(command)

            client_runner.run(DISCORD_BOT_TOKEN)
            
    except ConnectionError:
        print("❌ FATAL: Cannot run without PostgreSQL configuration.")
    except Exception as e:
        print(f"❌ FATAL UNCAUGHT ERROR: {e}")