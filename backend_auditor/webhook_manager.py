import os
import requests
import time
import json
from loguru import logger
from constants import SHARED_DATA_DIR
from file_utils import safe_write_report

class WebhookManager:
    def __init__(self, webhook_url):
        self.webhook_url = webhook_url
        self.state_file = SHARED_DATA_DIR / "states" / "auditor_webhook_state.json"
        self.colors = [
            0x00FFFF, # Cyan
            0xFF00FF, # Magenta
            0xFFD700, # Gold
            0x39FF14, # Neon Green
            0xFFA500, # Orange
            0x3498DB, # Blue
            0xFFFFFF  # White
        ]

    def _get_next_color(self):
        color_index = 0
        os.makedirs(self.state_file.parent, exist_ok=True)
        
        if self.state_file.exists():
            try:
                with open(self.state_file, 'r') as f:
                    state = json.load(f)
                    color_index = state.get('color_index', 0)
            except Exception as e:
                logger.error(f"Failed to read webhook state: {e}")
                
        color = self.colors[color_index % len(self.colors)]
        
        try:
            with open(self.state_file, 'w') as f:
                json.dump({'color_index': (color_index + 1) % len(self.colors)}, f)
        except Exception as e:
            logger.error(f"Failed to write webhook state: {e}")
            
        return color

    def translate_roles(self, role_ids_str, role_map):
        ids = [r.strip() for r in role_ids_str.replace("'", "").split(',') if r.strip()]
        names = [role_map.get(rid, f"Unknown ({rid})") for rid in ids]
        return ", ".join(names) if names else "None"

    def send_report(self, sections):
        if not self.webhook_url:
            logger.info("No Discord Webhook URL configured. Skipping report.")
            return
            
        if not sections:
            return 
            
        embeds = []
        current_time = int(time.time())
        current_desc = f"# ⚠️ Daily Clan Audit Report \n<t:{current_time}:F>\n_Note: In-game changes (rank updates, leaving/joining) can take up to a few days to propagate to the spreadsheet._\n\n"
        run_color = self._get_next_color()
        
        def add_text(text):
            nonlocal current_desc, embeds
            if not text: return
            if len(text) > 1900: text = text[:1897] + "..."
            if len(current_desc) + len(text) > 1900:
                if current_desc.strip():
                    embeds.append({"description": current_desc.strip(), "color": run_color})
                current_desc = text
            else:
                current_desc += text

        def chunk_and_add_section(title, items, description=""):
            formatted_desc = f"_{description.strip()}_\n" if description and description.strip() else ""
            
            if not items:
                add_text(f"## {title}\n{formatted_desc}-# ✅ No issues found.\n\n")
                return
                
            try:
                max_items = int(os.getenv('REPORT_ITEM_LIMIT', 10))
            except ValueError:
                max_items = 10
                
            total_items = len(items)
            display_items = items[:max_items]
            
            if total_items > max_items:
                remaining = total_items - max_items
                summary_line = f"-# showing {max_items} of {total_items} ({remaining} omitted)\n\n"
            else:
                summary_line = f"-# showing {total_items} of {total_items}\n\n"
                
            add_text(f"## {title}\n{formatted_desc}{summary_line}")
            
            for item in display_items:
                # We do not strip trailing whitespace here so that audit_logic can inject its own \n gaps
                add_text(item + "\n")
            
            add_text("\n") # Ensure a clean gap before the next section header

        for section in sections:
            chunk_and_add_section(section['title'], section['lines'], section.get('description', ''))
            
        if current_desc.strip():
            embeds.append({"description": current_desc.strip(), "color": run_color})

        # Discord limits total characters across all embeds in a message to 6000.
        # By chunking embeds at 1900 chars and sending 3 per request (5700 chars max), we guarantee delivery.
        for i in range(0, len(embeds), 3):
            embed_chunk = embeds[i:i+3]
            res = requests.post(self.webhook_url, json={"embeds": embed_chunk})
            if res.status_code >= 400:
                logger.error(f"Failed to send Discord webhook chunk {i//3 + 1} ({res.status_code}): {res.text}")
            else:
                logger.success(f"Sent Discord Webhook Report chunk {i//3 + 1}/{(len(embeds)-1)//3 + 1}.")
            time.sleep(1)

    def save_full_report(self, sections, filepath=None):
        """Saves the complete, untruncated audit report to a local Markdown file."""
        if not sections:
            return
            
        if filepath is None:
            filepath = SHARED_DATA_DIR / "reports" / "latest_audit_report.md"

        os.makedirs(os.path.dirname(filepath), exist_ok=True)
        
        date_str = time.strftime('%Y-%m-%d %H:%M:%S UTC', time.gmtime())
        md_content = f"# ⚠️ Daily Clan Audit Report\n**Generated:** {date_str}\n_Note: In-game changes (rank updates, leaving/joining) can take up to a few days to propagate to the spreadsheet._\n\n"
        
        for section in sections:
            title = section.get('title', 'Unknown Section')
            lines = section.get('lines', [])
            description = section.get('description', '').strip()
            
            md_content += f"## {title}\n"
            if description:
                md_content += f"_{description}_\n"
                
            if not lines:
                md_content += "* ✅ No issues found.\n\n"
            else:
                md_content += f"**Total Issues:** {len(lines)}\n\n"
                for line in lines:
                    md_content += f"{line}\n"
                md_content += "\n"
                
        if safe_write_report(filepath, md_content):
            logger.success(f"Saved full, untruncated audit report to {filepath}")
