import asyncio
import json
import os
import sys
from pathlib import Path
import pandas as pd

import discord
from loguru import logger
try:
    import tomllib
except ImportError:
    import tomli as tomllib  # type: ignore

from shared_utils import (
    load_config, PROJECT_ROOT, get_db_engine, DATA_DIR, STATES_DIR, SHARED_CONFIG_DIR, SECRETS_PATH,
    finish_script
)
from loguru_setup import loguru_setup

# --- Constants & Paths ---
SCRIPT_NAME = "6_post_pbs_to_discord"
ENV_SUFFIX = os.getenv("ENV_NAME", "prod").lower()
STATE_FILE_PATH = STATES_DIR / f'discord_pb_message_ids_{ENV_SUFFIX}.json'


# --- Helper Functions ---

def load_state(path: Path):
    """Loads message ID state from a JSON file."""
    if not path.exists():
        return {}
    try:
        with path.open('r', encoding='utf-8') as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError) as e:
        logger.warning(f"Could not load state file at '{path}'. Starting fresh. Error: {e}")
        return {}

def save_state(path: Path, state: dict):
    """Saves message ID state to a JSON file."""
    try:
        with path.open('w', encoding='utf-8') as f:
            json.dump(state, f, indent=4)
    except IOError as e:
        logger.error(f"Error: Could not save state to '{path}': {e}")

def create_embed_for_group(group, has_records=True, timestamp=None, warnings_list=None):
    """Creates a discord.Embed object for a given group of records."""
    group_title = group.get('title', 'Personal Bests')
    embed = discord.Embed(
        color=discord.Color.blue() if has_records else discord.Color.dark_grey()
    )

    header = f"# **{group_title}**"

    if not has_records:
        embed.description = f"{header}\nNo records to display in this category."
        if timestamp:
            embed.timestamp = timestamp
            embed.set_footer(text="Updated")
        return embed
    
    description_parts = [header]
    for record in group.get('records', []):
        record_name = record.get('name', 'Unnamed Record')
        time = record.get('time', 'N/A')
        holder = record.get('holder', [])
        date = record.get('date')  # Will be None if not set
        discord_emoji = record.get('discord_emoji', '')
        metric_label = record.get('label', 'Time')

        holder_str = ", ".join(holder) if holder else 'N/A'

        # Build the lines for this specific record
        record_details = [
            f"* **{metric_label}:** {time}",
            f"* **Holder(s):** {holder_str}"
        ]
        if pd.notna(date) and str(date).strip().lower() not in ['nan', 'none', '']:
            record_details.append(f"* *{date}*")

        # Build the title line, adding the emoji if it exists
        if discord_emoji:
            title_line = f"{discord_emoji} **{record_name}**"
        else:
            title_line = f"⚔️ **{record_name}**"

        part = f"{title_line}\n" + "\n".join(record_details)
        description_parts.append(part)

    description = "\n\n".join(description_parts)
    
    if len(description) > 3500:
        warn_msg = f"Embed description for '{group.get('title')}' is getting long ({len(description)} chars). Consider manually splitting this group in the TOML config."
        logger.warning(warn_msg)
        if warnings_list is not None:
            warnings_list.append(warn_msg)
        
    if len(description) > 4096: # Discord's description character limit
        description = description[:4080] + "\n...*truncated*"
        warn_msg = f"Embed description for '{group.get('title')}' was truncated as it exceeded the 4096 character limit."
        logger.warning(warn_msg)
        if warnings_list is not None:
            warnings_list.append(warn_msg)
    
    embed.description = description
    if timestamp:
        # The official way to add a timestamp to an embed.
        # It will appear next to the footer text (e.g., "Updated • Today at 5:30 PM")
        embed.timestamp = timestamp
        embed.set_footer(text="Updated")
    return embed

# --- Main Logic ---

class PBPosterClient(discord.Client):
    def __init__(self, *, intents: discord.Intents, pb_config: dict, pb_df: pd.DataFrame, secrets: dict, state: dict, name_to_id: dict):
        super().__init__(intents=intents)
        self.pb_config = pb_config
        self.state = state
        self.pb_df = pb_df
        self.secrets = secrets
        self.name_to_id = name_to_id
        self.run_warnings = []
        self.groups_processed = 0
        self.messages_posted = 0
        self.messages_updated = 0
        self.has_failed = False

    async def on_ready(self):
        logger.info(f'Logged in as {self.user} (ID: {self.user.id})')
        logger.info('------')

        try:
            await self.update_pbs()
        except Exception as e:
            logger.error(f"An unexpected error occurred during update: {e}", exc_info=True)
            self.run_warnings.append(f"FATAL ERROR during update: {e}")
            self.has_failed = True
        finally:
            logger.info("Processing complete. Closing connection.")
            await self.close()

    def embeds_are_equal(self, embed1: discord.Embed, embed2: discord.Embed) -> bool:
        """Compares two embeds, ignoring dynamic fields like timestamp, footer, and attachment details."""
        d1 = embed1.to_dict()
        d2 = embed2.to_dict()
        
        # Remove dynamic/transient fields
        for d in (d1, d2):
            d.pop('timestamp', None)
            d.pop('footer', None)
            d.pop('type', None) # Discord sometimes adds 'type': 'rich' on fetch
            
            # Normalize thumbnail keys to only compare the URL
            if 'thumbnail' in d and 'url' in d['thumbnail']:
                d['thumbnail'] = {'url': d['thumbnail']['url']}
                
            # Normalize image keys to only compare the URL
            if 'image' in d and 'url' in d['image']:
                d['image'] = {'url': d['image']['url']}
                
        # Handle attachment:// path mapping vs fetched CDN URLs
        if 'thumbnail' in d1 and 'thumbnail' in d2:
            u1 = d1['thumbnail'].get('url', '')
            u2 = d2['thumbnail'].get('url', '')
            if u1.startswith('attachment://') and u2:
                filename = u1.replace('attachment://', '')
                if filename in u2:
                    d2['thumbnail']['url'] = u1
                    
        return d1 == d2

    async def update_pbs(self):
        """Fetches, creates, or edits PB messages in the configured channel."""
        channel_id_val = self.secrets.get('discord_pb_channel_id')
        if not channel_id_val or ("YOUR_DATA_CHANNEL_ID_HERE" in str(channel_id_val)):
            logger.error(f"Error: 'discord_pb_channel_id' not set in '{SECRETS_PATH.name}'.")
            return

        try:
            channel_id = int(channel_id_val)
        except (ValueError, TypeError):
            logger.error(f"Error: 'discord_pb_channel_id' ID '{channel_id_val}' is not a valid integer.")
            return

        channel = self.get_channel(channel_id)
        if not isinstance(channel, discord.TextChannel):
            logger.error(f"Error: Channel with ID {channel_id} not found or is not a text channel.")
            return

        logger.info(f"Operating in channel: #{channel.name} ({channel.id})")

        # Get a single timestamp for this entire update run for consistency
        update_timestamp = pd.Timestamp.now().to_pydatetime()

        db_records_map = self.pb_df.set_index('Task').to_dict('index') if not self.pb_df.empty else {}

        # Start with the list of groups defined in the TOML config
        group_definitions = list(self.pb_config.get('groups', []))

        # --- Always add the "Miscellaneous/Other" group to the list to be processed ---
        other_group_name = self.pb_config.get('other_group_name', 'Miscellaneous PBs')
        other_group_df = self.pb_df[self.pb_df['Group'] == other_group_name]

        # Create a list of record definitions from the tasks, sorted alphabetically for consistency.
        # This will be an empty list if there are no misc records, which is the desired behavior.
        other_records = [{'name': task} for task in sorted(other_group_df['Task'].unique())]
        
        group_definitions.append({
            'title': other_group_name,
            'Image': None, # No image for the misc group
            'records': other_records
        })

        # Now loop through the potentially expanded list of groups
        for group_from_toml in group_definitions:
            self.groups_processed += 1
            group_title = group_from_toml.get('title')
            if not group_title:
                logger.warning("Skipping a group with no title.")
                continue

            # --- Build the group data for the embed, merging DB data ---
            embed_group_data = {
                'title': group_title,
                'Image': group_from_toml.get('Image'),
                'records': []
            }

            # Iterate through the records defined in the TOML to maintain order
            for record_from_toml in group_from_toml.get('records', []):
                task_name = record_from_toml.get('name')
                if not task_name:
                    continue

                # Get the emoji from the TOML record. It might be blank.
                discord_emoji = record_from_toml.get('discord_emoji', '')
                metric_label = record_from_toml.get('label', 'Time')
                display_name = record_from_toml.get('display_name', task_name)

                db_record = db_records_map.get(task_name)
                if db_record:
                    # Use the up-to-date data from the database
                    # The 'Holder' column is a comma-separated string, convert to list
                    holder_val = db_record.get('Holder', '')
                    holder_list = [h.strip() for h in holder_val.split(',')] if holder_val else []
                    
                    mapped_holders = []
                    for h in holder_list:
                        if self.name_to_id and h in self.name_to_id:
                            mapped_holders.append(f"<@{self.name_to_id[h]}>")
                        else:
                            mapped_holders.append(h)

                    embed_group_data['records'].append({
                        'name': display_name,
                        'time': db_record.get('Time', '0:00'),
                        'holder': mapped_holders,
                        'date': db_record.get('Date'),
                        'discord_emoji': discord_emoji,
                        'label': metric_label
                    })
                else:
                    # No record in the DB for this task, use a default placeholder
                    embed_group_data['records'].append({
                        'name': display_name,
                        'time': '0:00',
                        'holder': [],
                        'date': None,
                        'discord_emoji': discord_emoji,
                        'label': metric_label
                    })

            # Check if any of the records we are about to display have a holder.
            # This correctly handles cases where a group exists but all its records are empty (e.g. after blacklisting).
            has_db_records = any(r.get('holder') for r in embed_group_data['records'])

            message_id = self.state.get(group_title)
            embed = create_embed_for_group(embed_group_data, has_records=has_db_records, timestamp=update_timestamp, warnings_list=self.run_warnings)
            
            # --- Append Recent Clan Records to Miscellaneous Group ---
            if group_title == other_group_name:
                recent_count = self.pb_config.get('recent_PB_count', 0)
                if recent_count > 0 and not self.pb_df.empty:
                    # Filter for records with a date (excludes historical ones without dates)
                    df_recent = self.pb_df[self.pb_df['Date'].notna()].copy()
                    if not df_recent.empty:
                        df_recent.sort_values(by='Date', ascending=False, inplace=True)
                        top_recent = df_recent.head(recent_count)
                        
                        recent_lines = []
                        for _, row in top_recent.iterrows():
                            # Format: Name/s (bold) \n * Content (italic)
                            holder_val = str(row['Holder'])
                            holder_list = [h.strip() for h in holder_val.split(',')] if holder_val else []
                            mapped_holders = []
                            for h in holder_list:
                                if self.name_to_id and h in self.name_to_id:
                                    mapped_holders.append(f"<@{self.name_to_id[h]}>")
                                else:
                                    mapped_holders.append(h)
                            
                            mapped_holder_str = ", ".join(mapped_holders) if mapped_holders else "N/A"
                            recent_lines.append(f"* **{mapped_holder_str}**\n  * *{row['Task']} - {row['Time']}*")
                        
                        if recent_lines:
                            separator = "\n\n" + "─" * 20 + "\n\n"
                            header = "## **🏆 Newest Clan Records**\n"
                            recent_section = header + "\n".join(recent_lines)
                            
                            # If the misc section is empty, keep a placeholder so the "Newest" section 
                            # is clearly separated from the "Miscellaneous" title.
                            if "No records to display in this category." in embed.description:
                                current_desc = f"## **{group_title}**\n*No miscellaneous records to display.*"
                            else:
                                current_desc = embed.description
                            
                            new_desc = current_desc + separator + recent_section
                            
                            if len(new_desc) > 4096:
                                new_desc = new_desc[:4093] + "..."
                            
                            embed.description = new_desc

            image_path_str = group_from_toml.get('Image')
            discord_file = None
            if image_path_str:
                # Image paths in config are relative to the project root
                image_path = SHARED_CONFIG_DIR / image_path_str
                if image_path.exists():
                    file_name = image_path.name
                    discord_file = discord.File(image_path, filename=file_name)
                    embed.set_thumbnail(url=f"attachment://{file_name}")
                else:
                    logger.warning(f"Warning: Image file not found at '{image_path}' for group '{group_title}'.")

            try:
                if message_id:
                    message = await channel.fetch_message(message_id)
                    # Note: Editing a message does not allow changing the attached file.
                    # If you change the image in the config, you must delete the old
                    # message in Discord to force the script to post a new one with the new image.
                    if message.embeds and self.embeds_are_equal(embed, message.embeds[0]):
                        logger.info(f"Embed for '{group_title}' is unchanged. Skipping update.")
                    else:
                        await message.edit(embed=embed)
                        self.messages_updated += 1
                        logger.info(f"Updated embed for '{group_title}'.")
                else:
                    new_message = await channel.send(embed=embed, file=discord_file)
                    self.state[group_title] = new_message.id
                    self.messages_posted += 1
                    logger.info(f"Posted new embed for '{group_title}' (Message ID: {new_message.id}).")

            except discord.NotFound:
                logger.warning(f"Message for '{group_title}' not found (ID: {message_id}). Posting a new one.")
                new_message = await channel.send(embed=embed, file=discord_file)
                self.state[group_title] = new_message.id
                self.messages_posted += 1
            except discord.Forbidden as e:
                warn_msg = f"Insufficient permissions for group '{group_title}'. Check bot permissions. Details: {e}"
                logger.error(f"Error: {warn_msg}")
                self.run_warnings.append(warn_msg)
            except discord.HTTPException as e:
                warn_msg = f"An HTTP error occurred for group '{group_title}'. Details: {e}"
                logger.error(f"Error: {warn_msg}")
                self.run_warnings.append(warn_msg)

async def main():
    """Main entry point for the script."""
    config = load_config()
    loguru_setup(config, PROJECT_ROOT)
    logger.info(f"{f' Starting 6_post_pbs_to_discord.py ':=^80}")

    secrets = config.get('secrets', {})
    
    try:
        token_val = secrets.get('discord_bot_token')
        if not token_val or "YOUR_DISCORD_BOT_TOKEN_HERE" in str(token_val):
            raise ValueError(f"Bot token not found or not set in '{SECRETS_PATH}'")

        pb_config_filename = config.get('historical_data', {}).get('personal_bests_file')
        if not pb_config_filename:
            raise ValueError("Error: 'personal_bests_file' not defined in [historical_data] section of config.toml")
        pb_config_path = SHARED_CONFIG_DIR / pb_config_filename

        with open(pb_config_path, "rb") as f:
            pb_config = tomllib.load(f)
        logger.info(f"Successfully loaded PB config from {pb_config_path.name}")

        # --- Load Processed PB Data from Database ---
        optimised_db_uri = config.get('databases', {}).get('optimised_db_uri')
        if not optimised_db_uri:
            raise ValueError("Error: 'optimised_db_uri' not defined in [databases] section of config.toml")

        # --- Determine the newest database for Blue/Green deployment by checking for an '_alt' version ---
        newest_uri = None
        try:
            # URI format is assumed to be 'sqlite:///path/to/db.file'
            main_path = DATA_DIR / Path(optimised_db_uri.split('///', 1)[-1]).name
            
            # Construct the alternate database path by adding '_alt' before the file extension
            alt_filename = f"{main_path.stem}_alt{main_path.suffix}"
            alt_path = main_path.with_name(alt_filename)

            main_mod_time = main_path.stat().st_mtime if main_path.exists() else -1
            alt_mod_time = alt_path.stat().st_mtime if alt_path.exists() else -1

            if main_mod_time > alt_mod_time:
                newest_uri = optimised_db_uri
                logger.info(f"Using main database, it's the newest: {main_path.name}")
            elif alt_mod_time > -1:
                # Reconstruct the URI for the alternate database
                newest_uri = f"sqlite:///{alt_path.as_posix()}"
                logger.info(f"Using alternate database, it's the newest: {alt_path.name}")
            elif main_mod_time > -1: # Fallback to main if alt doesn't exist
                newest_uri = optimised_db_uri
                logger.info(f"Using main database, alternate not found: {main_path.name}")

        except OSError as e:
            logger.error(f"Could not access database files to check timestamps: {e}")

        optimised_engine = get_db_engine(newest_uri) if newest_uri else None
        pb_df = pd.DataFrame() # Default to empty DataFrame
        if optimised_engine:
            try:
                pb_df = pd.read_sql_table('personal_bests_summary', optimised_engine)
                logger.info(f"Successfully loaded {len(pb_df)} processed PBs from the database.")
            except ValueError as e:
                # This happens if the table doesn't exist
                logger.warning(f"Could not load 'personal_bests_summary' table. It may not have been created yet. Error: {e}")
            finally:
                optimised_engine.dispose()
        else:
            logger.error("Could not create database engine for optimised DB. Proceeding without PB data.")

        state = load_state(STATE_FILE_PATH)
        
        name_to_id = {}
        
        ds_config = config.get('dashboard_settings', {})
        pb_settings = ds_config.get('personal_bests', {})
        ping_discord_users = pb_settings.get('ping_discord_users_for_pbs', False)
        
        # Fallback checks in case the setting was placed in a different TOML section
        if not ping_discord_users:
            ping_discord_users = ds_config.get('ping_discord_users_for_pbs', False)
        if not ping_discord_users:
            ping_discord_users = config.get('roster_sync', {}).get('ping_discord_users_for_pbs', False)

        use_enriched_db = config.get('roster_sync', {}).get('use_enriched_db_for_dashboard', False)

        if ping_discord_users and use_enriched_db:
            roster_file = DATA_DIR.parent / "exports" / "roster_export.json"
            if roster_file.exists():
                try:
                    with open(roster_file, 'r', encoding='utf-8') as f:
                        roster_payload = json.load(f)
                        for user in roster_payload.get('members', []):
                            d_name = user.get('discord_name')
                            d_id = user.get('discord_id')
                            if d_id:
                                d_id_str = str(d_id).replace("'", "")
                                if d_name:
                                    name_to_id[d_name] = d_id_str
                    logger.info(f"Loaded {len(name_to_id)} Discord ID mappings for PB pings.")
                except Exception as e:
                    logger.warning(f"Could not load roster_export.json for discord ping mapping: {e}")
            else:
                logger.warning(f"Roster file not found for discord ping mapping at: {roster_file}")
        elif ping_discord_users and not use_enriched_db:
            logger.warning("ping_discord_users_for_pbs is True, but use_enriched_db_for_dashboard is False. Pings will be disabled.")
        elif not ping_discord_users:
            logger.info("Discord pings are disabled in config (ping_discord_users_for_pbs = False).")

        client = PBPosterClient(
            intents=discord.Intents.default(),
            pb_config=pb_config,
            pb_df=pb_df,
            secrets=secrets,
            state=state,
            name_to_id=name_to_id
        )

        await client.start(token_val)
        
        summary_lines = [
            f"**PB Posting Results:**",
            f"- Groups Processed: `{client.groups_processed}`",
            f"- Messages Created: `{client.messages_posted}`",
            f"- Messages Updated: `{client.messages_updated}`"
        ]
        
        if client.has_failed:
            project_name = config.get('general', {}).get('project_name', 'Unnamed Project')
            failed_msg = f"**❌ {project_name}: {SCRIPT_NAME} FAILED**\n\n" + "\n".join(summary_lines)
            finish_script(SCRIPT_NAME, config, failed_msg, client.run_warnings)
        else:
            finish_script(SCRIPT_NAME, config, summary_lines, client.run_warnings)

    except Exception as e:
        finish_script(SCRIPT_NAME, config, exception=e)
        raise e
    finally:
        if 'client' in locals() and hasattr(client, 'state'):
            save_state(STATE_FILE_PATH, client.state)
            logger.info("State saved.")
            
        logger.info(f"{f' Finished 6_post_pbs_to_discord.py ':=^80}")

if __name__ == '__main__':
    asyncio.run(main())