import os
from loguru import logger
from constants import SystemFlag, SHARED_DATA_DIR
from file_utils import safe_write_report

class BaseAudit:
    """
    Base class for all audits to ensure a consistent interface and encapsulate logic.
    
    Audit Types:
    - 'member': Runs once for EVERY row in the Database. Used to evaluate individual users, 
                apply System Flags to their row, and generate specific webhook report lines.
    - 'global': Runs exactly ONCE per execution. Does NOT evaluate specific database rows 
                and cannot apply System Flags. Used to generate bulk webhook reports 
                based on the overall API state (e.g., listing all untracked WOM accounts).
    """
    title = None
    description = ""
    type = "member"
    enabled = True
    enable_webhook = True

    def execute(self, context, member=None):
        """Evaluates the audit logic. Must return a dict with results."""
        raise NotImplementedError("Audits must implement the execute method.")
        
    def post_execute(self, context):
        """Optional hook that runs after all members are evaluated. Returns a list of report lines."""
        return None
        
    @staticmethod
    def fmt_name(name):
        """Formats a user's name or RSN as bold text."""
        if not name or str(name).strip() == '': return "**Unknown**"
        return f"**{str(name).strip()}**"
        
    @staticmethod
    def fmt_rank(rank):
        """Formats ranks or roles as inline code blocks, safely handling lists or comma strings."""
        if not rank or str(rank).strip() in ['', 'None']: return "`None`"
        if isinstance(rank, list):
            items = [str(r).strip() for r in rank if str(r).strip()]
        else:
            items = [r.strip() for r in str(rank).split(',') if r.strip()]
        if not items: return "`None`"
        return ", ".join(f"`{r}`" for r in items)
        
    @staticmethod
    def fmt_id(val):
        """Formats IDs (like WOM IDs) as italic text."""
        if not val or str(val).strip() == '': return "*Unknown*"
        return f"*{str(val).strip()}*"
        
    @staticmethod
    def get_target_clan_accounts(member, target_clan_name):
        """
        Extracts ALL RSNs, but masks the Game Rank as 'Unknown' for accounts that are NOT in the target clan.
        Returns a tuple of lists: (all_rsns, masked_ranks)
        """
        rsns_list = [r.strip() for r in str(member.get('RSNs', '')).split(',')]
        game_ranks_list = [r.strip() for r in str(member.get('Game Ranks', '')).split(',')]
        account_clans = [c.strip() for c in str(member.get('Account Clan', '')).split(',')]
        
        target_rsns = []
        target_ranks = []
        
        for i in range(max(len(rsns_list), len(game_ranks_list), len(account_clans))):
            rsn = rsns_list[i] if i < len(rsns_list) and rsns_list[i] else "Unknown"
            rank = game_ranks_list[i] if i < len(game_ranks_list) and game_ranks_list[i] else "Unknown"
            clan = account_clans[i] if i < len(account_clans) and account_clans[i] else "Unknown"
            
            target_rsns.append(rsn)
            if target_clan_name and clan.lower() == target_clan_name.lower():
                target_ranks.append(rank)
            else:
                target_ranks.append("Unknown")
                
        return target_rsns, target_ranks

    def build_member_header(self, member, context, rsn_displays=None):
        """Generates a standardized header for member audits."""
        d_name = str(member.get('Discord Name', '')).strip()
        d_id = str(member.get('Discord ID', '')).replace("'", "").strip()
        discord_name = d_name if d_name else (d_id if d_id else "Unknown")
        
        discord_name_display = self.fmt_name(discord_name)
        if SystemFlag.NOT_IN_DISCORD.value in context.get('current_flags', []):
            discord_name_display += " *(Not in Discord)*"
            
        clan_rank = str(member.get('Clan Rank', '')).strip()
        discord_ranks = str(member.get('Discord Ranks', '')).strip()
        
        webhook = context.get('webhook')
        role_map = context.get('role_map', {})
        managed_role_ids = context.get('managed_role_ids', set())
        
        user_roles = [r.strip() for r in discord_ranks.replace("'", "").split(',') if r.strip()]
        managed_user_roles = [r for r in user_roles if r in managed_role_ids]
        actual_roles_str = webhook.translate_roles(",".join(managed_user_roles), role_map) if (webhook and managed_user_roles) else "None"
            
        header = f"• {discord_name_display} | Discord: {self.fmt_rank(actual_roles_str)} | Sheet: {self.fmt_rank(clan_rank)}"
        if rsn_displays:
            header += f"\n*RSNs:* {', '.join(rsn_displays)}"
            
        return header


class GlobalDataIntegrityAudit(BaseAudit):
    title = '🚨 Database Integrity Errors'
    description = "Critical database errors detected. Usually caused by manual spreadsheet edits (e.g., Scientific Notation, duplicate rows). Admins should fix these immediately via the raw Sheet."
    type = 'global'

    def execute(self, context, member=None):
        all_members = context.get('all_members', [])
        
        issues = []
        seen_ids = set()
        seen_wom_ids = {}
        
        for row_idx, r_member in enumerate(all_members):
            real_row_num = row_idx + 2  # Assuming row 1 is headers
            
            d_id_raw = str(r_member.get('Discord ID', '')).strip()
            d_id_clean = d_id_raw.replace("'", "")
            d_name = str(r_member.get('Discord Name', '')).strip() or "Unknown"
            row_label = f"**{d_name}** (Row {real_row_num})"
            
            # Check for empty ID
            if not d_id_clean:
                issues.append(f"• {row_label}: Missing Primary Key (Discord ID)")
                continue
                
            # Check for Duplicates
            if d_id_clean in seen_ids:
                issues.append(f"• {row_label}: Duplicate Discord ID (`{d_id_clean}`)")
            seen_ids.add(d_id_clean)
            
            # Check for Scientific Notation / Corruption
            if "E+" in d_id_clean.upper() or "." in d_id_clean:
                issues.append(f"• {row_label}: Corrupted Discord ID (Scientific Notation: `{d_id_raw}`)")
            elif not d_id_clean.isdigit():
                issues.append(f"• {row_label}: Invalid Discord ID characters (`{d_id_raw}`)")
                
            # Check WOM IDs for invalid chars or accidental cross-user duplication
            wom_ids_str = str(r_member.get('WOM IDs', '')).strip()
            if wom_ids_str:
                for w in wom_ids_str.split(','):
                    w_clean = w.strip()
                    if not w_clean: continue
                    if not w_clean.isdigit():
                        issues.append(f"• {row_label}: Invalid WOM ID (`{w_clean}`)")
                    elif w_clean in seen_wom_ids:
                        issues.append(f"• {row_label}: Duplicate WOM ID (`{w_clean}`) - Already assigned to row {seen_wom_ids[w_clean]}")
                    else:
                        seen_wom_ids[w_clean] = real_row_num

        if issues:
            return {'report_lines': issues}
        return None


class GlobalBannedAudit(BaseAudit):
    title = '⛔ Banned Accounts'
    description = "Accounts are banned in-game but still taking up a clan slot. Generally safe to remove."
    type = 'global'

    def execute(self, context, member=None):
        banned_members = context.get('banned_members', [])
        lines = [f"• {self.fmt_name(m['rsn'])} (WOM ID: {self.fmt_id(m['wom_id'])})" for m in banned_members]
        return {'report_lines': lines}


class GlobalUntrackedAudit(BaseAudit):
    title = '👤 Unlinked In-Game Accounts'
    description = "In-game accounts listed in the WOM clan but not linked to any Discord user. The WOM ID may be linked via the Web App or CLI tools."
    type = 'global'

    def execute(self, context, member=None):
        untracked_members = context.get('untracked_members', [])
        lines = [f"• {self.fmt_name(m['rsn'])} (WOM ID: {self.fmt_id(m['wom_id'])})" for m in untracked_members]
        return {'report_lines': lines}

class GlobalWomUpdateFailedAudit(BaseAudit):
    title = '⚠️ WOM Update Failures'
    description = "These players have not been updated on WOM in 7+ days, and the automated attempt to force an update failed (e.g. they changed their name, got banned, or dropped off the hiscores). Please review."
    type = 'global'

    def execute(self, context, member=None):
        failed_updates = context.get('failed_wom_updates', {})
        if not failed_updates:
            return None
            
        all_members = context.get('all_members', [])
        wom_to_member = {}
        for m in all_members:
            wids = [w.strip() for w in str(m.get('WOM IDs', '')).split(',') if w.strip()]
            for w in wids:
                wom_to_member[w] = m
                
        lines = []
        for wid, data in failed_updates.items():
            rsn = data['rsn']
            last_changed = data.get('last_changed')
            date_str = last_changed[:10] if last_changed else "Unknown"
            
            matched_member = wom_to_member.get(str(wid))
            if matched_member:
                d_name = str(matched_member.get('Discord Name', '')).strip()
                d_id = str(matched_member.get('Discord ID', '')).replace("'", "").strip()
                discord_name = d_name if d_name else (d_id if d_id else "Unknown")
                
                discord_name_display = discord_name
                if SystemFlag.NOT_IN_DISCORD.value in str(matched_member.get('System Flags', '')):
                    discord_name_display += " (Not in Discord)"
                    
                lines.append(f"• {discord_name_display} - RSNs: {rsn} ({date_str})")
            else:
                lines.append(f"• Unlinked Account - RSNs: {rsn} ({date_str})")
                
        return {'report_lines': lines}


class MemberNotInClanAudit(BaseAudit):
    title = '🚪 Missing from In-Game Clan'
    description = "Has a clan rank or Discord role and linked OSRS accounts, but none are currently in the WOM clan. Add 'Ignore Error: Clan Departure' or 'On Leave' to Admin Flags to dismiss this warning."
    type = 'member'

    def execute(self, context, member):
        target_clan_name = context.get('target_clan_name', '')
        clan_rank = str(member.get('Clan Rank', '')).strip()
        
        discord_ranks = str(member.get('Discord Ranks', '')).strip()
        all_req_roles = context.get('all_req_roles', set())
        has_req_discord_role = any(r.strip() in all_req_roles for r in discord_ranks.replace("'", "").split(',') if r.strip())
        
        wom_ids_str = str(member.get('WOM IDs', '')).strip()
        has_wom_ids = bool([w for w in wom_ids_str.split(',') if w.strip()])
        
        if (clan_rank or has_req_discord_role) and has_wom_ids:
            account_clans = [c.strip() for c in str(member.get('Account Clan', '')).split(',') if c.strip()]
            
            if account_clans:
                active_in_target = any(c.lower() == target_clan_name.lower() for c in account_clans)
                if not active_in_target:
                    
                    rsns_list = [r.strip() for r in str(member.get('RSNs', 'Unknown')).split(',')]
                    game_ranks_list = [r.strip() for r in str(member.get('Game Ranks', '')).split(',')]
                    account_displays = []
                    
                    for i in range(max(len(rsns_list), len(account_clans), len(game_ranks_list))):
                        rsn = rsns_list[i] if i < len(rsns_list) and rsns_list[i] else "Unknown"
                        clan = account_clans[i] if i < len(account_clans) and account_clans[i] else "Unknown"
                        rank = game_ranks_list[i] if i < len(game_ranks_list) and game_ranks_list[i] else "Unknown"
                        
                        if rsn == "Unknown" and clan == "Unknown": continue
                        
                        if clan and clan.lower() not in ['none', 'unknown', target_clan_name.lower()]:
                            account_displays.append(f"{self.fmt_name(rsn)} (in {self.fmt_rank(clan)} rank {self.fmt_rank(rank)})")
                        else:
                            account_displays.append(self.fmt_name(rsn))
                            
                    # report_line = self.build_member_header(member, context, account_displays)
                    d_name = str(member.get('Discord Name', '')).strip()
                    d_id = str(member.get('Discord ID', '')).replace("'", "").strip()
                    discord_name = d_name if d_name else (d_id if d_id else "Unknown")
                    formatted_rsns = ", ".join(account_displays) if account_displays else "Unknown"
                    
                    discord_name_display = self.fmt_name(discord_name)
                    if SystemFlag.NOT_IN_DISCORD.value in context.get('current_flags', []):
                        discord_name_display += " *(Not in Discord)*"
                        
                    report_line = f"• {discord_name_display} - RSNs: {formatted_rsns}"
                    return {
                        'flag_to_add': SystemFlag.NOT_IN_WOM_CLAN.value, 
                        'flag_to_remove': None, 
                        'report_line': report_line
                    }
            
        return {'flag_to_add': None, 'flag_to_remove': SystemFlag.NOT_IN_WOM_CLAN.value, 'report_line': None}


class MemberReturnedAudit(BaseAudit):
    title = '👋 Returning Members Detected'
    description = "Member is currently active in the clan, but marked as departed or on leave. Please clear their Admin Flags so their ranks can be audited normally."
    type = 'member'

    def execute(self, context, member):
        admin_flags_str = str(member.get('Admin Flags', ''))
        admin_flags = [f.strip() for f in admin_flags_str.split(',') if f.strip()]
        
        departure_flags = [f for f in admin_flags if f in ['Ignore Error: Clan Departure', 'On Leave']]
        
        if not departure_flags:
            return {'flag_to_add': None, 'flag_to_remove': None, 'report_line': None}
            
        target_clan_name = context.get('target_clan_name', '')
        if not target_clan_name:
            return {'flag_to_add': None, 'flag_to_remove': None, 'report_line': None}
            
        account_clans = [c.strip() for c in str(member.get('Account Clan', '')).split(',')]
        active_in_target = any(c.lower() == target_clan_name.lower() for c in account_clans if c)
        
        if active_in_target:
            rsns_list = [r.strip() for r in str(member.get('RSNs', 'Unknown')).split(',')]
            game_ranks_list = [r.strip() for r in str(member.get('Game Ranks', '')).split(',')]
            account_clans = [c.strip() for c in str(member.get('Account Clan', '')).split(',')]
            account_displays = []
            
            for i in range(max(len(rsns_list), len(account_clans), len(game_ranks_list))):
                rsn = rsns_list[i] if i < len(rsns_list) and rsns_list[i] else "Unknown"
                clan = account_clans[i] if i < len(account_clans) and account_clans[i] else "Unknown"
                rank = game_ranks_list[i] if i < len(game_ranks_list) and game_ranks_list[i] else "Unknown"
                
                if rsn == "Unknown" and clan == "Unknown": continue
                
                if clan and clan.lower() not in ['none', 'unknown']:
                    account_displays.append(f"{self.fmt_name(rsn)} (in {self.fmt_rank(clan)} rank {self.fmt_rank(rank)})")
                else:
                    account_displays.append(self.fmt_name(rsn))
                    
            report_line = self.build_member_header(member, context, account_displays) + "\n"
            
            flags_display = ", ".join(f"`{f}`" for f in departure_flags)
            report_line += f"> * Remove Admin Flag: {flags_display}\n"
            
            return {
                'flag_to_add': None, 
                'flag_to_remove': None, 
                'report_line': report_line
            }
            
        return {'flag_to_add': None, 'flag_to_remove': None, 'report_line': None}


class MemberNoRsnLinkedAudit(BaseAudit):
    title = '⚠️ Ranked Members Missing RSNs'
    description = "These members have a Clan Rank (spreadsheet) or Discord roles, but have no OSRS accounts linked in the database."
    type = 'member'

    def execute(self, context, member):
        clan_rank = str(member.get('Clan Rank', '')).strip()
        
        discord_ranks = str(member.get('Discord Ranks', '')).strip()
        all_req_roles = context.get('all_req_roles', set())
        has_req_discord_role = any(r.strip() in all_req_roles for r in discord_ranks.replace("'", "").split(',') if r.strip())
        
        wom_ids_str = str(member.get('WOM IDs', '')).strip()
        has_wom_ids = bool([w for w in wom_ids_str.split(',') if w.strip()])
        
        if (clan_rank or has_req_discord_role) and not has_wom_ids:
            report_line = self.build_member_header(member, context)
            
            return {
                'flag_to_add': SystemFlag.MISSING_RSNS.value, 
                'flag_to_remove': None, 
                'report_line': report_line
            }
            
        return {'flag_to_add': None, 'flag_to_remove': SystemFlag.MISSING_RSNS.value, 'report_line': None}


class GeneralRankMismatchAudit(BaseAudit):
    title = '⚖️ Rank & Role Mismatches'
    description = "Identifies discrepancies between the Google Sheet, Discord Roles, and In-Game Ranks. Attempts to identify the error source."
    type = 'member'

    def execute(self, context, member):
        parsed_rules = context.get('rank_rules_parsed')
        webhook = context.get('webhook')
        role_map = context.get('role_map', {})
        managed_role_ids = context.get('managed_role_ids', set())
        
        if not parsed_rules:
            return None
            
        current_flags = context.get('current_flags', [])
        if SystemFlag.NOT_IN_WOM_CLAN.value in current_flags or SystemFlag.NOT_IN_DISCORD.value in current_flags:
            return {'flag_to_add': None, 'flag_to_remove': [SystemFlag.RANK_MISMATCH.value, "In-Game Rank Mismatch"], 'report_line': None}
            
        wom_ids_str = str(member.get('WOM IDs', '')).strip()
        if not wom_ids_str:
            # Setup Audit handles these cases
            return {'flag_to_add': None, 'flag_to_remove': [SystemFlag.RANK_MISMATCH.value, "In-Game Rank Mismatch"], 'report_line': None}
            
        target_clan_name = context.get('target_clan_name', '')
        clan_rank = str(member.get('Clan Rank', '')).strip()
        rsns_list, game_ranks_list = self.get_target_clan_accounts(member, target_clan_name)
        clean_ranks = [r for r in game_ranks_list if r and r != 'Unknown']
        
        user_roles = [r.strip() for r in str(member.get('Discord Ranks', '')).replace("'", "").split(',') if r.strip()]
        managed_user_roles = [r for r in user_roles if r in managed_role_ids]
        
        def evaluate(target_rank):
            rule = parsed_rules.get(target_rank)
            if not rule: return False, ["Invalid Sheet Rank"], False, ["Invalid Sheet Rank"], []
            
            d_issues = []
            missing_req = [r for r in rule['req_roles'] if r not in user_roles]
            has_exc = [r for r in rule['exc_roles'] if r in user_roles]
            auth_roles = set(rule['req_roles'] + rule['all_roles'])
            unauth_managed = [r for r in user_roles if r in managed_role_ids and r not in auth_roles]
            
            bad_roles_ids = list(set(has_exc + unauth_managed))
            
            if missing_req:
                missing_names = [role_map.get(r, f"Unknown ({r})") for r in missing_req]
                d_issues.append(f"Missing roles: {self.fmt_rank(missing_names)}")
                
            if bad_roles_ids:
                bad_names = [role_map.get(r, f"Unknown ({r})") for r in bad_roles_ids]
                d_issues.append(f"Remove roles: {self.fmt_rank(bad_names)}")
            
            ig_issues = []
            main_rank = rule['main_rank']
            allowed_all = ([main_rank] if main_rank else []) + rule['alt_ranks']
            
            if main_rank and main_rank not in clean_ranks:
                ig_issues.append(f"Missing Main Rank {self.fmt_rank(main_rank)}")
                
            unauth_alts = []
            for i in range(max(len(rsns_list), len(game_ranks_list))):
                rsn = rsns_list[i] if i < len(rsns_list) and rsns_list[i] else "Unknown"
                rank = game_ranks_list[i] if i < len(game_ranks_list) and game_ranks_list[i] else "Unknown"
                if rank != 'Unknown' and rank not in allowed_all:
                    unauth_alts.append({'rsn': rsn, 'rank': rank})
                    
            if unauth_alts: ig_issues.append("Incorrect alt ranks")
            
            return len(d_issues) == 0, d_issues, len(ig_issues) == 0, ig_issues, unauth_alts

        is_mismatch = False
        report_type = ""
        d_issues = ig_issues = unauth_alts = []
        target_rank = clan_rank
        
        if clan_rank:
            d_ok, d_issues, ig_ok, ig_issues, unauth_alts = evaluate(clan_rank)
            if not d_ok and ig_ok:
                is_mismatch = True; report_type = "discord"
            elif d_ok and not ig_ok:
                is_mismatch = True; report_type = "ingame"
            elif not d_ok and not ig_ok:
                is_mismatch = True; report_type = "general"
        else:
            guessed_rank = None
            for r_name, rule in parsed_rules.items():
                if rule['req_roles'] and all(rr in user_roles for rr in rule['req_roles']):
                    guessed_rank = r_name
                    break
                    
            if guessed_rank:
                target_rank = guessed_rank
                d_ok, d_issues, ig_ok, ig_issues, unauth_alts = evaluate(guessed_rank)
                if ig_ok:
                    is_mismatch = True; report_type = "sheet_missing"
                else:
                    is_mismatch = True; report_type = "general"
            else:
                if managed_user_roles or clean_ranks:
                    is_mismatch = True; report_type = "general"
            
        if is_mismatch:
            account_tuples = []
            for i in range(max(len(rsns_list), len(game_ranks_list))):
                rsn = rsns_list[i] if i < len(rsns_list) and rsns_list[i] else "Unknown"
                rank = game_ranks_list[i] if i < len(game_ranks_list) and game_ranks_list[i] else "Unknown"
                if rsn != "Unknown" or rank != "Unknown": account_tuples.append((rsn, rank))
                
            rsn_displays = []
            for r, rk in account_tuples:
                if rk == "Unknown":
                    rsn_displays.append(self.fmt_name(r))
                else:
                    rsn_displays.append(f"{self.fmt_name(r)} {self.fmt_rank(rk)}")
                    
            report_line = self.build_member_header(member, context, rsn_displays) + "\n"
            
            rule = parsed_rules.get(target_rank)
            
            if report_type == "discord":
                for issue in d_issues: report_line += f"> * {issue}\n"
                expected_discord = webhook.translate_roles(",".join(rule['req_roles']), role_map) if rule else "None"
                report_line += f">   * Expected Roles: {self.fmt_rank(expected_discord)}\n"
                
            elif report_type == "ingame":
                for issue in ig_issues:
                    if "Missing Main Rank" in issue: report_line += f"> * {issue}\n"
                for alt in unauth_alts:
                    report_line += f"> * Incorrect rank: {self.fmt_name(alt['rsn'])} {self.fmt_rank(alt['rank'])}\n"
                expected_ig = self.fmt_rank(([rule['main_rank']] if rule and rule.get('main_rank') else []) + (rule['alt_ranks'] if rule else []))
                report_line += f">   * Expected: {expected_ig}\n"
                
            elif report_type == "sheet_missing":
                report_line += f"> * Sheet Rank is missing, but Discord and In-Game align.\n"
                report_line += f">   * Expected Sheet Rank: {self.fmt_rank(target_rank)}\n"
                
            elif report_type == "general":
                if not clan_rank and not managed_user_roles:
                    report_line += f"> * Unranked Member (Missing Sheet Rank and Discord Roles)\n"
                else:
                    report_line += f"> * General Mismatch (Review all platforms)\n"
                
            return {
                'flag_to_add': SystemFlag.RANK_MISMATCH.value, 
                'flag_to_remove': "In-Game Rank Mismatch", # Gracefully scrub the deprecated flag 
                'report_line': report_line
            }
            
        return {'flag_to_add': None, 'flag_to_remove': [SystemFlag.RANK_MISMATCH.value, "In-Game Rank Mismatch"], 'report_line': None}

class MemberMultipleClansAudit(BaseAudit):
    title = '⚔️ Multiple Clans Detected'
    description = "Member has at least one account in the target clan, but also has accounts in other clans. Add 'Multiple Clans' to Admin Flags to dismiss this warning."
    type = 'member'

    def execute(self, context, member):
        target_clan_name = context.get('target_clan_name', '')
        if not target_clan_name or target_clan_name == 'Unknown Clan':
            return {'flag_to_add': None, 'flag_to_remove': SystemFlag.MULTIPLE_CLANS.value, 'report_line': None}
            
        account_clans = [c.strip() for c in str(member.get('Account Clan', '')).split(',')]
        
        # Verify they are actually an active member of your clan first
        active_in_target = any(c.lower() == target_clan_name.lower() for c in account_clans if c)
        if not active_in_target:
            return {'flag_to_add': None, 'flag_to_remove': SystemFlag.MULTIPLE_CLANS.value, 'report_line': None}
            
        rsns_list = [r.strip() for r in str(member.get('RSNs', 'Unknown')).split(',')]
        game_ranks_list = [r.strip() for r in str(member.get('Game Ranks', 'Unknown')).split(',')]
        offending_accounts = []
        all_accounts_display = []
        
        for i in range(max(len(rsns_list), len(account_clans), len(game_ranks_list))):
            rsn = rsns_list[i] if i < len(rsns_list) and rsns_list[i] else "Unknown"
            clan = account_clans[i] if i < len(account_clans) and account_clans[i] else "Unknown"
            rank = game_ranks_list[i] if i < len(game_ranks_list) and game_ranks_list[i] else "Unknown"
            
            if rsn == "Unknown" and clan == "Unknown": continue
            
            if clan and clan.lower() == target_clan_name.lower():
                all_accounts_display.append(f"{self.fmt_name(rsn)} {self.fmt_rank(rank)}")
            else:
                all_accounts_display.append(self.fmt_name(rsn))
            
            if clan and clan.lower() not in ['none', 'unknown', target_clan_name.lower()]:
                offending_accounts.append(f"{self.fmt_name(rsn)} in {self.fmt_rank(clan)} rank {self.fmt_rank(rank)}")
                
        if offending_accounts:
            report_line = self.build_member_header(member, context, all_accounts_display) + "\n"
            report_line += f"> * Other clans: {', '.join(offending_accounts)}\n"
            
            return {'flag_to_add': SystemFlag.MULTIPLE_CLANS.value, 'flag_to_remove': None, 'report_line': report_line}
            
        return {'flag_to_add': None, 'flag_to_remove': SystemFlag.MULTIPLE_CLANS.value, 'report_line': None}


class MemberLeftDiscordAudit(BaseAudit):
    title = '🏃 Left Discord but still in Clan'
    description = "Member has left the Discord server but still has active accounts in the WOM clan."
    type = 'member'

    def execute(self, context, member):
        # FUTURE EXPANSION HOOK:
        # If the schema is updated to include 'Discord Status' and 'Discord Left Date',
        # we can replace the flag check below with: if member.get('Discord Status') == 'Left':
        # and use datetime math on 'Discord Left Date' to format the report (e.g., "Left 7 days ago").
        
        current_flags = context.get('current_flags', [])
        if SystemFlag.NOT_IN_DISCORD.value not in current_flags:
            return {'flag_to_add': None, 'flag_to_remove': None, 'report_line': None}
            
        target_clan_name = context.get('target_clan_name', '')
        target_rsns, target_ranks = self.get_target_clan_accounts(member, target_clan_name)
        
        rsn_displays = []
        active_accounts = []
        for rsn, rank in zip(target_rsns, target_ranks):
            if rank != "Unknown":
                formatted = f"{self.fmt_name(rsn)} {self.fmt_rank(rank)}"
                active_accounts.append(formatted)
                rsn_displays.append(formatted)
            else:
                rsn_displays.append(self.fmt_name(rsn))
                
        if active_accounts:
            report_line = self.build_member_header(member, context, rsn_displays) + "\n"
            report_line += f"> * Active accounts: {', '.join(active_accounts)}\n"
            
            # Returning the flag here allows the Webhook Manager to suppress this line if "Not in Discord" is in their Admin Flags
            return {'flag_to_add': SystemFlag.NOT_IN_DISCORD.value, 'flag_to_remove': None, 'report_line': report_line}
            
        return {'flag_to_add': None, 'flag_to_remove': None, 'report_line': None}


class MemberAltLimitAudit(BaseAudit):
    title = '👥 Clan Account Limits Exceeded'
    description = "Members who have more active accounts in the WOM clan than their rank allows. Limits are configured via the Web App."
    type = 'member'

    def execute(self, context, member):
        target_clan_name = context.get('target_clan_name', '')
        if not target_clan_name:
            return {'flag_to_add': None, 'flag_to_remove': None, 'report_line': None}
            
        parsed_rules = context.get('rank_rules_parsed', {})
        clan_rank = str(member.get('Clan Rank', '')).strip()
        
        # Default to 1 if they have no rank or their rank isn't found
        max_accounts = 1
        if clan_rank and clan_rank in parsed_rules:
            max_accounts = parsed_rules[clan_rank].get('max_accounts', 1)
            
        rsns_list = [r.strip() for r in str(member.get('RSNs', 'Unknown')).split(',')]
        account_clans = [c.strip() for c in str(member.get('Account Clan', '')).split(',')]
        game_ranks_list = [r.strip() for r in str(member.get('Game Ranks', '')).split(',')]
        
        active_accounts = []
        raw_active_rsns = []
        
        for i in range(max(len(rsns_list), len(account_clans), len(game_ranks_list))):
            rsn = rsns_list[i] if i < len(rsns_list) and rsns_list[i] else "Unknown"
            clan = account_clans[i] if i < len(account_clans) and account_clans[i] else "Unknown"
            rank = game_ranks_list[i] if i < len(game_ranks_list) and game_ranks_list[i] else "Unknown"
            
            if rsn == "Unknown" and clan == "Unknown": continue
            
            if clan.lower() == target_clan_name.lower():
                active_accounts.append(f"{self.fmt_name(rsn)} (in {self.fmt_rank(clan)} rank {self.fmt_rank(rank)})")
                raw_active_rsns.append(f"`{rsn}`")
                
        if len(active_accounts) > max_accounts:
            # Accumulate data for the separate Markdown purge report
            violators_list = context.get('alt_limit_violators')
            report_line = self.build_member_header(member, context, active_accounts) + "\n"
            report_line += f"> * Limit exceeded: Found {len(active_accounts)} accounts, allowed {max_accounts}\n"            
            if violators_list is not None:
                violators_list.append({
                    'discord_id': str(member.get('Discord ID', '')).replace("'", "").strip(),
                    'discord_name': str(member.get('Discord Name', '')).strip(),
                    'clan_rank': clan_rank,
                    'max_accounts': max_accounts,
                    'raw_active_rsns': raw_active_rsns,
                    'report_line': report_line
                })
            
            return {
                'flag_to_add': None,
                'flag_to_remove': None,
                    'report_line': report_line
            }
            
        return {'flag_to_add': None, 'flag_to_remove': None, 'report_line': None}


class MemberBannedInClanAudit(BaseAudit):
    title = None
    type = 'member'
    enable_webhook = False

    def execute(self, context, member):
        banned_wom_ids = context.get('banned_wom_ids', set())
        wom_ids_str = str(member.get('WOM IDs', ''))
        wids = [w.strip() for w in wom_ids_str.split(',') if w.strip()]
        
        is_banned = any(wid in banned_wom_ids for wid in wids)
        
        return {
            'flag_to_add': SystemFlag.BANNED_IN_CLAN.value if is_banned else None, 
            'flag_to_remove': SystemFlag.BANNED_IN_CLAN.value if not is_banned else None, 
            'report_line': None
        }

class MemberArchivedAudit(BaseAudit):
    title = None # This audit is silent and does not generate a webhook section
    type = 'member'
    enable_webhook = False

    def execute(self, context, member):
        clan_rank = str(member.get('Clan Rank', '')).strip()
        
        # Check for managed discord roles
        discord_ranks = str(member.get('Discord Ranks', '')).strip()
        managed_role_ids = context.get('managed_role_ids', set())
        user_roles = [r.strip() for r in discord_ranks.replace("'", "").split(',') if r.strip()]
        has_managed_role = any(r in managed_role_ids for r in user_roles)
        
        # Check if in target clan
        target_clan_name = context.get('target_clan_name', '')
        account_clans = [c.strip().lower() for c in str(member.get('Account Clan', '')).split(',') if c.strip()]
        is_in_clan = target_clan_name.lower() in account_clans if target_clan_name else False
        
        # Archive if they have no sheet rank, no managed discord roles, and no accounts in the clan
        should_be_archived = not clan_rank and not has_managed_role and not is_in_clan
        
        return {
            'flag_to_add': SystemFlag.ARCHIVED.value if should_be_archived else None,
            'flag_to_remove': SystemFlag.ARCHIVED.value if not should_be_archived else None,
            'report_line': None
        }


# The active instantiated audits.
# The order of this list dictates the order they appear in the Discord Webhook.
ACTIVE_AUDITS = [
    # This audit runs first to flag inactive members. Subsequent audits will skip these members for performance.
    MemberArchivedAudit(),
    MemberNotInClanAudit(),
    MemberReturnedAudit(),
    GlobalUntrackedAudit(),
    GlobalWomUpdateFailedAudit(),
    GlobalBannedAudit(),
    MemberLeftDiscordAudit(),
    GeneralRankMismatchAudit(),
    # MemberNoRsnLinkedAudit(),    
    MemberMultipleClansAudit(),
    MemberAltLimitAudit(),
    MemberBannedInClanAudit(),
    GlobalDataIntegrityAudit()
]

def _generate_alt_purge_report(context):
    """Private helper to format and save the Alt Account Limit ping list."""
    violators = context.get('alt_limit_violators', [])
    if not violators:
        return
        
    # rank_rules_parsed is ordered Highest -> Lowest (matching Reference_Data). 
    # We reverse the keys to group Lowest -> Highest.
    rank_order = list(context.get('rank_rules_parsed', {}).keys())
    rank_order.reverse()
    
    grouped_violators = {rank: [] for rank in rank_order}
    ungrouped_violators = []
    
    for v in violators:
        rank = v['clan_rank']
        if rank in grouped_violators:
            grouped_violators[rank].append(v)
        else:
            ungrouped_violators.append(v)
            
    lines = [
        "# 👥 Alt Account Limit Purge List",
        "> Copy and paste the sections below into Discord to ping members who need to remove an alt account.",
        ""
    ]
    
    for rank in rank_order:
        rank_violators = grouped_violators[rank]
        if not rank_violators: continue
        
        max_accs = context['rank_rules_parsed'][rank]['max_accounts']
        lines.append(f"### {rank} (Allowed: {max_accs} Account{'s' if max_accs != 1 else ''})")
        
        for v in rank_violators:
            accounts_str = ", ".join(v['raw_active_rsns'])
            lines.append(f"* <@{v['discord_id']}> - Accounts in clan: {accounts_str}")
        lines.append("")
        
    report_path = SHARED_DATA_DIR / "reports" / "alt_limit_pings.md"
    os.makedirs(report_path.parent, exist_ok=True)
    safe_write_report(report_path, "\n".join(lines))

def audit_roster(db_manager, rank_rules, audit_logs, context):
    logger.info("Executing Roster Audits...")
    all_members = db_manager.get_all_records('Database')
    batch_updates = []
    
    # Enrich the context with parsed rules and derived state
    context['managed_role_ids'] = set()
    context['all_req_roles'] = set()
    context['all_members'] = all_members
    context['alt_limit_violators'] = []
    
    banned_members = context.get('banned_members', [])
    context['banned_wom_ids'] = {str(m['wom_id']) for m in banned_members}
    
    if rank_rules:
        context['rank_rules_parsed'] = {}
        for rule in rank_rules:
            rank_name = str(rule.get('Clan Rank', '')).strip()
            if not rank_name: continue
            
            # Explicitly replace hidden formatting quotes to fix the matching bug
            req_roles = [r.strip().replace("'", "") for r in str(rule.get('Required Discord Roles', '')).split(',') if r.strip()]
            all_roles = [r.strip().replace("'", "") for r in str(rule.get('Allowed Discord Roles', '')).split(',') if r.strip()]
            exc_roles = [r.strip().replace("'", "") for r in str(rule.get('Excluded Discord Roles', '')).split(',') if r.strip()]
            main_rank = str(rule.get('Main In-Game Rank', '')).strip()
            alt_ranks = [r.strip() for r in str(rule.get('Allowed Alt Ranks', '')).split(',') if r.strip()]
            max_accounts_raw = str(rule.get('Max Clan Accounts', '1')).strip()
            max_accounts = int(max_accounts_raw) if max_accounts_raw.isdigit() else 1
            
            context['managed_role_ids'].update(req_roles + all_roles + exc_roles)
            context['all_req_roles'].update(req_roles)
            context['rank_rules_parsed'][rank_name] = {
                'req_roles': req_roles,
                'all_roles': all_roles,
                'exc_roles': exc_roles,
                'main_rank': main_rank,
                'alt_ranks': alt_ranks,
                'max_accounts': max_accounts
            }
    else:
        logger.warning("No rank rules found in Reference_Data. Skipping Rank Mismatch logic.")

    # Initialize report_data dict in the exact order defined by ACTIVE_AUDITS
    report_data = {
        audit.title: {'lines': [], 'description': audit.description} 
        for audit in ACTIVE_AUDITS if audit.title
    }

    # Execute Global Audits
    for audit in ACTIVE_AUDITS:
        if audit.type == 'global' and audit.enabled:
            result = audit.execute(context)
            if result and result.get('report_lines'):
                if audit.enable_webhook and audit.title:
                    report_data[audit.title]['lines'].extend(result['report_lines'])

    # Sort members from Lowest Rank (including Unranked) to Highest Rank.
    # This guarantees that lower-ranked members are processed and reported first,
    # meaning if truncation occurs, highest-ranked members are omitted.
    rank_order = list(context.get('rank_rules_parsed', {}).keys())
    
    def get_rank_weight(mem):
        rank = str(mem.get('Clan Rank', '')).strip()
        try:
            return len(rank_order) - rank_order.index(rank)
        except ValueError:
            return 0  # Unranked/Unknown gets evaluated first
            
    sorted_members = sorted(all_members, key=get_rank_weight)

    for member in sorted_members:
        discord_id = str(member.get('Discord ID', '')).replace("'", "")
        discord_name = member.get('Discord Name', discord_id)
        sys_flags = str(member.get('System Flags', ''))
        admin_flags = str(member.get('Admin Flags', ''))
        
        current_flags_list = [f.strip() for f in sys_flags.split(',') if f.strip() and f.strip() != SystemFlag.OK.value]
        context['current_flags'] = current_flags_list.copy()
        new_flags_list = current_flags_list.copy()
        
        for audit in ACTIVE_AUDITS:
            if audit.type == 'global' or not audit.enabled:
                continue
                
            # If the user has been flagged as Archived by the MemberArchivedAudit (which runs first),
            # we can safely skip all subsequent member-level audits for performance.
            if not isinstance(audit, MemberArchivedAudit) and SystemFlag.ARCHIVED.value in new_flags_list:
                continue

            result = audit.execute(context, member)
            if not result:
                continue
                
            flag_add = result.get('flag_to_add')
            flag_rm = result.get('flag_to_remove')
            rep_line = result.get('report_line')
            rep_title = audit.title
            
            # Handle Flag Additions
            is_suppressed = False
            if flag_add:
                if flag_add not in new_flags_list and flag_add not in admin_flags:
                    new_flags_list.append(flag_add)
                    audit_logs.append(f"Flag Added - {discord_name} ({discord_id}): Flagged as '{flag_add}'.")
                
                is_suppressed = (
                    flag_add in admin_flags or 
                    (flag_add == SystemFlag.RANK_MISMATCH.value and 'On Leave' in admin_flags) or
                    (flag_add == SystemFlag.NOT_IN_WOM_CLAN.value and ('Ignore Error: Clan Departure' in admin_flags or 'On Leave' in admin_flags))
                )

            if rep_line and rep_title and not is_suppressed and audit.enable_webhook:
                report_data[rep_title]['lines'].append(rep_line)
            
            # Handle Flag Removals
            if flag_rm:
                rm_list = flag_rm if isinstance(flag_rm, list) else [flag_rm]
                for rm in rm_list:
                    if rm in new_flags_list:
                        new_flags_list.remove(rm)
                        audit_logs.append(f"Flag Removed - {discord_name} ({discord_id}): Cleared '{rm}' flag.")
                    
            context['current_flags'] = new_flags_list

        # Construct new flags string and queue update if changed
        new_sys_flags = ", ".join(new_flags_list) if new_flags_list else SystemFlag.OK.value
        if new_sys_flags != sys_flags:
            batch_updates.append({'id': discord_id, 'col_name': 'System Flags', 'value': new_sys_flags})

    # Execute Post-Audit hooks (e.g., sorting collected lines)
    for audit in ACTIVE_AUDITS:
        if audit.enabled and hasattr(audit, 'post_execute'):
            post_lines = audit.post_execute(context)
            if post_lines and audit.title and audit.enable_webhook:
                report_data[audit.title]['lines'].extend(post_lines)

    # Generate the Markdown ping list
    _generate_alt_purge_report(context)

    if batch_updates:
        db_manager.batch_update_by_id('Database', 'Discord ID', batch_updates)
        logger.success(f"Executed {len(batch_updates)} flag updates to the database.")
        
    # Flatten into webhook_manager section format
    report_sections = []
    for title, data in report_data.items():
        report_sections.append({"title": title, "lines": data['lines'], "description": data['description']})
        
    return report_sections