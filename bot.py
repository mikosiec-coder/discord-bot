# bot.py
from __future__ import annotations

import os
import logging
import re
import math
from typing import Dict, Optional, List, Tuple

import discord
from discord import app_commands
from dotenv import load_dotenv

# ========== ENV ==========
load_dotenv(override=True)
TOKEN = (os.getenv("DISCORD_TOKEN") or "").strip()
GUILD_ID = os.getenv("GUILD_ID")
OWNER_ID = os.getenv("OWNER_ID")

if not TOKEN or len(TOKEN) < 50:
    raise RuntimeError("Brak/niepoprawny DISCORD_TOKEN w .env.")

GUILD: Optional[discord.Object] = discord.Object(id=int(GUILD_ID)) if GUILD_ID else None

# ========== CLIENT ==========
intents = discord.Intents.default()

class MyClient(discord.Client):
    def __init__(self) -> None:
        super().__init__(intents=intents)
        self.tree = app_commands.CommandTree(self)

    async def setup_hook(self) -> None:
        if GUILD:
            cmds = await self.tree.sync(guild=GUILD)
            logging.info(f"Synced {len(cmds)} guild cmds to {GUILD.id}")
        else:
            cmds = await self.tree.sync()
            logging.info(f"Synced {len(cmds)} global cmds")

client = MyClient()
tree = client.tree

# ===================== WSPÓLNE =====================
def fmt_int(x: float | int) -> str:
    return f"{int(round(float(x))):,}".replace(",", " ")

def _to_int(s: str) -> int:
    try: return int(re.sub(r"[^\d-]", "", str(s)) or "0")
    except: return 0

# ==============================================================
# ======================== /PATRONAT ===========================
# ==============================================================

COST_PER_POINT = {
    "charter": 1, "construction": 3, "sceat": 4, "upgrade": 9,
    "samurai_medals": 50, "samurai_tokens": 1380, "khan_medals": 3400, "khan_tablets": 1950,
}
LEVEL_COSTS = [310, 915, 2030, 3600, 5280, 6650, 9300, 13300, 14600, 25200]
PUBLIC_ORDER    = [4100, 4300, 4600, 4700, 4750, 4800, 4850, 4900, 4950, 5000]
MELEE_BONUS     = [1, 2, 3, 4, 5, 6, 7, 10, 13, 15]
RANGED_BONUS    = [1, 2, 3, 4, 5, 6, 7, 10, 13, 15]
COURTYARD_BONUS = [0, 0, 0, 0, 1, 3, 6, 9, 12, 15]

PL_NAME = {
    "charter": "Żetony patronatu",
    "construction": "Żetony budowy",
    "sceat": "Groszaki",
    "upgrade": "Żetony ulepszenia",
    "samurai_medals": "Medale Samuraja",
    "samurai_tokens": "Żetony Samuraja",
    "khan_medals": "Medale Chana",
    "khan_tablets": "Tabliczki Nomada",
}
EMOJI_NAME = {
    "charter": ["Patronat"],
    "construction": ["zetony_budowy"],
    "sceat": ["groszaki"],
    "upgrade": ["zetony_ulepszenia"],
    "samurai_medals": ["Medale_samuraja"],
    "samurai_tokens": ["Tokeny_samuraja"],
    "khan_medals": ["Medale_chana"],
    "khan_tablets": ["tabliczki_nomada","tabliczki_chana"],
    "decor": ["Dekorka"],
    "rubies": ["rubiny"],
}
UNICODE_FALLBACK = {
    "charter": "💠", "construction": "🧱", "sceat": "🪙", "upgrade": "🛠️",
    "samurai_medals": "🎖️", "samurai_tokens": "🔶",
    "khan_medals": "🏅", "khan_tablets": "🪪",
    "decor": "🏛️", "rubies": "💎",
}
def get_emoji(guild: "discord.Guild | None", key: str) -> str:
    names = EMOJI_NAME.get(key, [])
    if guild:
        for n in names:
            e = discord.utils.get(guild.emojis, name=n)
            if e: return str(e)
    return UNICODE_FALLBACK.get(key, "•")

def calc_points(**spent) -> float:
    return sum((float(v) / COST_PER_POINT[k]) for k, v in spent.items() if v)

def walk_levels(start_level: int, start_progress: float, gained: float):
    level = max(0, min(10, int(start_level)))
    progress = max(0.0, float(start_progress))
    pool = max(0.0, float(gained))
    if level >= 10:
        return 10, 0.0, None, progress + pool
    while level < 10:
        need = LEVEL_COSTS[level] - progress
        if pool >= need:
            pool -= need
            level += 1
            progress = 0.0
            if level == 10:
                return 10, 0.0, None, pool
        else:
            progress += pool
            pool = 0.0
            break
    to_next = LEVEL_COSTS[level] - progress if level < 10 else None
    return level, progress, to_next, None

# Rubiny – pakiety do Żetonów patronatu
P_PACKS: List[dict] = [
    {"amount": 32500, "price": 625000, "limit": 1},
    {"amount": 3250,  "price": 70000,  "limit": 1},
    {"amount": 3250,  "price": 79000,  "limit": 2},
    {"amount": 3250,  "price": 85000,  "limit": 3},
    {"amount": 325,   "price": 7000,   "limit": 3},
    {"amount": 325,   "price": 7900,   "limit": 10},
    {"amount": 325,   "price": 8800,   "limit": 50},
    {"amount": 35,    "price": 700,    "limit": 5},
    {"amount": 35,    "price": 800,    "limit": 10},
    {"amount": 35,    "price": 900,    "limit": 50},
]
SINGLE_PRICE = 35

def best_ruby_cost_for_charters(required: int) -> Tuple[int, str, float]:
    required = max(0, int(required))
    if required == 0:
        return 0, "", 0.0
    packs = [dict(p) for p in P_PACKS]
    packs.sort(key=lambda p: (p["price"] / p["amount"], -p["amount"]))
    remaining = required
    total_cost = 0
    buys: List[Tuple[int,int,int]] = []
    for p in packs:
        if remaining <= 0: break
        max_full = min(p["limit"], remaining // p["amount"])
        if max_full > 0:
            total_cost += max_full * p["price"]
            remaining -= max_full * p["amount"]
            buys.append((p["amount"], p["price"], max_full))
            p["limit"] -= max_full
    while remaining > 0:
        best_i = -1
        best_eff = SINGLE_PRICE
        for i, p in enumerate(packs):
            if p["limit"] <= 0: continue
            s = min(p["amount"], remaining)
            eff = p["price"] / s
            if eff < best_eff - 1e-9:
                best_eff = eff; best_i = i
        if best_i == -1:
            total_cost += remaining * SINGLE_PRICE
            buys.append((1, SINGLE_PRICE, remaining))
            remaining = 0
        else:
            p = packs[best_i]
            total_cost += p["price"]
            buys.append((p["amount"], p["price"], 1))
            remaining = max(0, remaining - p["amount"])
            p["limit"] -= 1
    agg: Dict[Tuple[int,int], int] = {}
    for amt, price, cnt in buys:
        agg[(amt, price)] = agg.get((amt, price), 0) + cnt
    items = sorted(agg.items(), key=lambda kv: (kv[0][1] / kv[0][0], -kv[0][0]))
    plan = "\n".join(f"{cnt}× {amt} za {fmt_int(price)}" for (amt, price), cnt in items)
    avg = total_cost / required if required > 0 else 0.0
    return int(round(total_cost)), plan, avg

SESSIONS: Dict[int, dict] = {}
def _new_session() -> dict:
    return {
        "charter":0,"construction":0,"sceat":0,"upgrade":0,
        "samurai_medals":0,"samurai_tokens":0,"khan_medals":0,"khan_tablets":0,
        "current_level":0,"current_progress":0,"target_level":0,
    }
def _get_session(uid: int) -> dict:
    if uid not in SESSIONS: SESSIONS[uid] = _new_session()
    return SESSIONS[uid]

SPEND_ORDER = [
    "charter", "sceat", "construction", "upgrade",
    "samurai_medals", "samurai_tokens", "khan_medals", "khan_tablets"
]

def _render_spent_lines(guild: "discord.Guild | None", s: dict) -> str:
    parts = []
    for k in SPEND_ORDER:
        v = s.get(k, 0)
        if v and int(v) > 0:
            parts.append(f"{get_emoji(guild,k)} **{PL_NAME[k]}:** {fmt_int(v)}")
    return "\n".join(parts) if parts else "—"

def _make_embed(guild: "discord.Guild | None", session: dict, show_result: bool=False) -> "discord.Embed":
    gained = calc_points(
        charter=session["charter"], construction=session["construction"],
        sceat=session["sceat"], upgrade=session["upgrade"],
        samurai_medals=session["samurai_medals"], samurai_tokens=session["samurai_tokens"],
        khan_medals=session["khan_medals"], khan_tablets=session["khan_tablets"],
    )
    lvl, prog, to_next, overflow = walk_levels(session["current_level"], session["current_progress"], gained)

    embed = discord.Embed(title=f"{get_emoji(guild,'decor')} Dekoracja — panel", color=0x2ecc71)
    embed.add_field(name="🧾 Wydatki", value=_render_spent_lines(guild, session), inline=False)

    if session["current_level"] > 0 or session["current_progress"] > 0:
        embed.add_field(
            name="🧭 Stan początkowy",
            value=f"Poziom: **{session['current_level']}**\nPunkty w poziomie: **{fmt_int(session['current_progress'])}**",
            inline=True
        )

    embed.add_field(name="🧮 Łączne pkt.", value=f"**{fmt_int(gained)}**", inline=True)

    if show_result:
        if lvl < 10:
            postep = f"❗ Nadwyżka: **{fmt_int(prog)}**\n⏭️ Brakuje: **{fmt_int(to_next)}**"
        else:
            extra = overflow if overflow is not None else 0
            postep = f"❗ Nadwyżka po maks.: **{fmt_int(extra)}**"
        show_level = max(1, lvl); idx = show_level - 1
        stats = f"({MELEE_BONUS[idx]}/{RANGED_BONUS[idx]}/{COURTYARD_BONUS[idx]})"
        postep += f"\n🏛️ Poziom dekoracji: **{show_level}**  {stats}"
        embed.add_field(name="📈 Postęp", value=postep, inline=False)

    avg_charter = 0.0
    if session["charter"] > 0:
        rubies, plan, avg = best_ruby_cost_for_charters(session["charter"])
        avg_charter = avg
        embed.add_field(
            name=f"{get_emoji(guild,'rubies')} Koszt rubinów",
            value=f"Rubiny: **{fmt_int(rubies)}**\nPlan:\n{plan}" if plan else f"Rubiny: **{fmt_int(rubies)}**",
            inline=False
        )

    if show_result and session.get("target_level", 0):
        target = int(session["target_level"])
        if lvl >= 10:
            need_pts = 0
        else:
            need_pts = LEVEL_COSTS[lvl] - prog
            for lv in range(lvl+1, target):
                need_pts += LEVEL_COSTS[lv]
        if need_pts > 0:
            rubies2, plan2, _ = best_ruby_cost_for_charters(need_pts)
            embed.add_field(
                name=f"🎯 Koszt do poziomu {target} (żetony patronatu)",
                value=(f"Żetony patronatu: **{fmt_int(need_pts)}**\n"
                       f"{get_emoji(guild,'rubies')} Rubiny: **{fmt_int(rubies2)}**\n"
                       f"Plan:\n{plan2}") if plan2 else
                      (f"Żetony patronatu: **{fmt_int(need_pts)}**\n"
                       f"{get_emoji(guild,'rubies')} Rubiny: **{fmt_int(rubies2)}**"),
                inline=False
            )
        elif target <= lvl:
            embed.add_field(
                name="🎯 Cel już osiągnięty",
                value=f"Masz co najmniej poziom **{target}**.",
                inline=False
            )

    if avg_charter > 0:
        embed.set_footer(text=f"Średni koszt 1 pkt: {avg_charter:.2f} rub.")

    return embed

# --- Modale (patronat) ---
class SpendingModal1(discord.ui.Modal, title="Wydatki — 1/2"):
    def __init__(self, session: dict):
        super().__init__(custom_id="patronat:modal_spend1")
        self.session = session
        self.charter = discord.ui.TextInput(label="Żetony patronatu", default=str(session['charter']), required=False)
        self.sceat = discord.ui.TextInput(label="Groszaki", default=str(session['sceat']), required=False)
        self.construction = discord.ui.TextInput(label="Żetony budowy", default=str(session['construction']), required=False)
        self.upgrade = discord.ui.TextInput(label="Żetony ulepszenia", default=str(session['upgrade']), required=False)
        for it in (self.charter, self.sceat, self.construction, self.upgrade): self.add_item(it)
    async def on_submit(self, interaction: discord.Interaction):
        try:
            s = self.session
            s["charter"] = _to_int(self.charter.value)
            s["sceat"] = _to_int(self.sceat.value)
            s["construction"] = _to_int(self.construction.value)
            s["upgrade"] = _to_int(self.upgrade.value)
            await interaction.response.send_message("Zapisano (1/2). Kliknij **Zapisz** w panelu.", ephemeral=True)
        except Exception as e:
            logging.exception("Modal1 error: %s", e)
            await interaction.response.send_message("Błąd przy zapisie (1/2).", ephemeral=True)

class SpendingModal2(discord.ui.Modal, title="Wydatki — 2/2"):
    def __init__(self, session: dict):
        super().__init__(custom_id="patronat:modal_spend2")
        self.session = session
        self.samurai_medals = discord.ui.TextInput(label="Medale Samuraja", default=str(session['samurai_medals']), required=False)
        self.samurai_tokens = discord.ui.TextInput(label="Żetony Samuraja", default=str(session['samurai_tokens']), required=False)
        self.khan_medals = discord.ui.TextInput(label="Medale Chana", default=str(session['khan_medals']), required=False)
        self.khan_tablets = discord.ui.TextInput(label="Tabliczki Nomada", default=str(session['khan_tablets']), required=False)
        for it in (self.samurai_medals, self.samurai_tokens, self.khan_medals, self.khan_tablets): self.add_item(it)
    async def on_submit(self, interaction: discord.Interaction):
        try:
            s = self.session
            s["samurai_medals"] = _to_int(self.samurai_medals.value)
            s["samurai_tokens"] = _to_int(self.samurai_tokens.value)
            s["khan_medals"] = _to_int(self.khan_medals.value)
            s["khan_tablets"] = _to_int(self.khan_tablets.value)
            await interaction.response.send_message("Zapisano (2/2). Kliknij **Zapisz** w panelu.", ephemeral=True)
        except Exception as e:
            logging.exception("Modal2 error: %s", e)
            await interaction.response.send_message("Błąd przy zapisie (2/2).", ephemeral=True)

class StateModal(discord.ui.Modal, title="LVL dekoracji"):
    def __init__(self, session: dict):
        super().__init__(custom_id="patronat:modal_state")
        self.session = session
        self.level = discord.ui.TextInput(label="Obecny poziom (0–10)", default=str(session['current_level']), required=False, max_length=2)
        self.progress = discord.ui.TextInput(label="Punkty wbite w poziom", default=str(session['current_progress']), required=False)
        self.target = discord.ui.TextInput(label="Docelowy poziom (1–10)", default=str(session['target_level']), required=False, max_length=2)
        self.add_item(self.level); self.add_item(self.progress); self.add_item(self.target)
    async def on_submit(self, interaction: discord.Interaction):
        try:
            self.session["current_level"] = max(0, min(10, _to_int(self.level.value)))
            self.session["current_progress"] = max(0, _to_int(self.progress.value))
            self.session["target_level"] = max(0, min(10, _to_int(self.target.value)))
            await interaction.response.send_message("Parametry poziomu zapisane. Kliknij **Zapisz**.", ephemeral=True)
        except Exception as e:
            logging.exception("StateModal error: %s", e)
            await interaction.response.send_message("Błąd przy zapisie poziomu.", ephemeral=True)

class DekorView(discord.ui.View):
    def __init__(self, owner_id: int):
        super().__init__(timeout=600)
        self.owner_id = owner_id
    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.owner_id:
            await interaction.response.send_message("To prywatny panel innego użytkownika.", ephemeral=True); return False
        return True
    @discord.ui.button(label="1", style=discord.ButtonStyle.primary, emoji="🧾", custom_id="patronat:btn_spend1")
    async def set_spend1(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(SpendingModal1(_get_session(self.owner_id)))
    @discord.ui.button(label="2", style=discord.ButtonStyle.primary, emoji="💰", custom_id="patronat:btn_spend2")
    async def set_spend2(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(SpendingModal2(_get_session(self.owner_id)))
    @discord.ui.button(label="LVL dekoracji", style=discord.ButtonStyle.secondary, emoji="🧭", custom_id="patronat:btn_state")
    async def set_state(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(StateModal(_get_session(self.owner_id)))
    @discord.ui.button(label="Zapisz", style=discord.ButtonStyle.success, emoji="🔄", custom_id="patronat:btn_save")
    async def save(self, interaction: discord.Interaction, button: discord.ui.Button):
        try:
            embed = _make_embed(interaction.guild, _get_session(self.owner_id), show_result=True)
            await interaction.response.edit_message(embed=embed, view=self)
        except Exception as e:
            logging.exception("Save error: %s", e)
            try: await interaction.response.send_message("Błąd przy zapisie/odświeżeniu.", ephemeral=True)
            except: pass
    @discord.ui.button(label="Wyczyść", style=discord.ButtonStyle.danger, emoji="🧹", custom_id="patronat:btn_clear")
    async def clear(self, interaction: discord.Interaction, button: discord.ui.Button):
        SESSIONS[self.owner_id] = _new_session()
        embed = _make_embed(interaction.guild, SESSIONS[self.owner_id], show_result=False)
        await interaction.response.edit_message(embed=embed, view=self)

# Komenda /patronat
_cmd_kwargs = {"name": "patronat", "description": "Panel liczenia dekoracji (prywatny)"}
if GUILD: _cmd_kwargs["guild"] = GUILD
@tree.command(**_cmd_kwargs)
async def patronat(interaction: discord.Interaction):
    try:
        s = _get_session(interaction.user.id)
        view = DekorView(interaction.user.id)
        embed = _make_embed(interaction.guild, s, show_result=False)
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)
    except Exception as e:
        logging.exception("/patronat error: %s", e)
        await interaction.response.send_message("Nie udało się otworzyć panelu. Spróbuj ponownie.", ephemeral=True)

# ==============================================================
# ========================== /LIGA =============================
# ==============================================================

# Medale (od najlepszego do najsłabszego)
MEDALS = [
    ("gold",   "Złoty",     1000, "🥇"),
    ("silver", "Srebrny",    950, "🥈"),
    ("bronze", "Brązowy",    850, "🥉"),
    ("glass",  "Szklany",    700, "🪟"),
    ("copper", "Miedziany",  500, "🟠"),
    ("stone",  "Kamienny",   300, "🪨"),
    ("wood",   "Drewniany",  100, "🪵"),
]
MEDAL_POINTS = {k:p for k,_,p,_ in MEDALS}

# Custom emoji na serwerze:
MEDAL_CUSTOM = {
    "gold":   ["zloty_medal"],
    "silver": ["srebrny_medal"],
    "bronze": ["brazowy_medal"],
    "glass":  ["szklany_medal"],
    "copper": ["miedziany_medal"],
    "stone":  ["kamienny_medal"],
    "wood":   ["drewniany_medal"],
}
def get_medal_emoji(guild: "discord.Guild | None", key: str) -> str:
    names = MEDAL_CUSTOM.get(key, [])
    if guild:
        for n in names:
            e = discord.utils.get(guild.emojis, name=n)
            if e: return str(e)
    for k,_,_,e in MEDALS:
        if k == key:
            return e
    return "🔸"

TITLES = [
    "Zadziora", "Awanturnik", "Rozrabiaka", "Wprawny Rozrabiaka",
    "Łowca", "Łowca Głów", "Wytrawny Łowca", "Mistrzowski Łowca",
    "Strażnik", "Strażnik Zamkowy", "Strażnik Dworu", "Strażnik Tronu",
    "Wojownik", "Dzielny Wojownik", "Doświadczony Wojownik", "Bohaterski Wojownik",
    "Pan Wojny", "Wielki Pan Wojny", "Najwyższy Pan Wojny", "Pan Wojny Totalnej",
    "Niszczyciel",
]
TITLE_EMOJI = "🏆"  # podmień na swoje

def liga_points(s: dict) -> int:
    return sum(int(s.get(k,0))*MEDAL_POINTS[k] for k in MEDAL_POINTS)

def title_from_points(total: int) -> Tuple[int, str, Optional[str], int, int]:
    idx = min(total // 2000, len(TITLES)-1)
    cur = TITLES[idx]
    nxt = TITLES[idx+1] if idx+1 < len(TITLES) else None
    in_block = total % 2000
    need = 0 if nxt is None else (2000 - in_block if in_block>0 else 2000)
    return idx, cur, nxt, in_block, need

# porządek od najsłabszego do najmocniejszego:
WEAK_FIRST = list(reversed(MEDALS))  # wood ... gold

def weakest_single_medal_key(need: int) -> Optional[str]:
    for k, n, p, e in WEAK_FIRST:
        if p >= need:
            return k
    return None

def weakest_two_medals_keys(need: int) -> Tuple[str, str]:
    for j in range(len(WEAK_FIRST)):          # najsilniejszy w parze
        for i in range(j + 1):                # drugi nie silniejszy niż j
            k1, n1, p1, e1 = WEAK_FIRST[i]
            k2, n2, p2, e2 = WEAK_FIRST[j]
            if p1 + p2 >= need:
                return k1, k2
    return WEAK_FIRST[0][0], WEAK_FIRST[0][0]

LIGA_SESSIONS: Dict[int, dict] = {}
def _new_liga() -> dict:
    return {k:0 for k,_,_,_ in MEDALS}
def _get_liga(uid: int) -> dict:
    if uid not in LIGA_SESSIONS: LIGA_SESSIONS[uid] = _new_liga()
    return LIGA_SESSIONS[uid]

def _render_medals(session: dict, guild: "discord.Guild | None") -> str:
    parts = []
    for k, n, p, e in MEDALS:
        cnt = int(session.get(k,0))
        if cnt>0:
            parts.append(f"{get_medal_emoji(guild,k)} × **{fmt_int(cnt)}**")
    return "\n".join(parts) if parts else "—"

def _make_liga_embed(guild: "discord.Guild | None", session: dict) -> discord.Embed:
    total = liga_points(session)
    idx, cur, nxt, in_block, need = title_from_points(total)

    embed = discord.Embed(title="🏰 Liga — tytuły z medali", color=0x5865F2)
    embed.add_field(name="🎖️ Medale", value=_render_medals(session, guild), inline=False)

    if nxt:
        embed.add_field(name="🏆 Tytuł", value=f"{TITLE_EMOJI} **{cur}** → następny: **{nxt}**", inline=True)
        postep = f"❗ Nadwyżka: **{fmt_int(in_block)}**\n⏭️ Brakuje: **{fmt_int(need)}**\n"
        one_key = weakest_single_medal_key(need)
        if one_key:
            postep += f"🗓️ Dziś wystarczy: {get_medal_emoji(guild, one_key)} ({MEDAL_POINTS[one_key]})"
        else:
            k1, k2 = weakest_two_medals_keys(need)
            postep += (f"🗓️ Dziś za mało; w 2 dni: "
                       f"{get_medal_emoji(guild, k1)} + {get_medal_emoji(guild, k2)} "
                       f"({MEDAL_POINTS[k1]}+{MEDAL_POINTS[k2]})")
        embed.add_field(name="📈 Postęp", value=postep, inline=False)
    else:
        embed.add_field(name="🏆 Tytuł", value=f"{TITLE_EMOJI} **{cur}** (MAX)", inline=True)
        embed.add_field(name="📈 Postęp", value=f"❗ Nadwyżka po maks.: **{fmt_int(in_block)}**", inline=False)

    return embed

# ---- Modale (liga) ----
class LigaModal1(discord.ui.Modal, title="Medale — 1/2"):
    def __init__(self, session: dict):
        super().__init__(custom_id="liga:modal1")
        self.s = session
        self.gold = discord.ui.TextInput(label="Złoty", default=str(session.get("gold",0)), required=False)
        self.silver = discord.ui.TextInput(label="Srebrny", default=str(session.get("silver",0)), required=False)
        self.bronze = discord.ui.TextInput(label="Brązowy", default=str(session.get("bronze",0)), required=False)
        self.glass = discord.ui.TextInput(label="Szklany", default=str(session.get("glass",0)), required=False)
        for it in (self.gold,self.silver,self.bronze,self.glass): self.add_item(it)
    async def on_submit(self, interaction: discord.Interaction):
        try:
            self.s["gold"] = _to_int(self.gold.value)
            self.s["silver"] = _to_int(self.silver.value)
            self.s["bronze"] = _to_int(self.bronze.value)
            self.s["glass"] = _to_int(self.glass.value)
            await interaction.response.send_message("Zapisano medale (1/2). Kliknij **Zapisz** w panelu.", ephemeral=True)
        except Exception as e:
            logging.exception("LigaModal1 error: %s", e)
            await interaction.response.send_message("Błąd przy zapisie (1/2).", ephemeral=True)

class LigaModal2(discord.ui.Modal, title="Medale — 2/2"):
    def __init__(self, session: dict):
        super().__init__(custom_id="liga:modal2")
        self.s = session
        self.copper = discord.ui.TextInput(label="Miedziany", default=str(session.get("copper",0)), required=False)
        self.stone  = discord.ui.TextInput(label="Kamienny", default=str(session.get("stone",0)), required=False)
        self.wood   = discord.ui.TextInput(label="Drewniany", default=str(session.get("wood",0)), required=False)
        for it in (self.copper,self.stone,self.wood): self.add_item(it)
    async def on_submit(self, interaction: discord.Interaction):
        try:
            self.s["copper"] = _to_int(self.copper.value)
            self.s["stone"]  = _to_int(self.stone.value)
            self.s["wood"]   = _to_int(self.wood.value)
            await interaction.response.send_message("Zapisano medale (2/2). Kliknij **Zapisz** w panelu.", ephemeral=True)
        except Exception as e:
            logging.exception("LigaModal2 error: %s", e)
            await interaction.response.send_message("Błąd przy zapisie (2/2).", ephemeral=True)

class LigaView(discord.ui.View):
    def __init__(self, owner_id: int):
        super().__init__(timeout=600)
        self.owner_id = owner_id
    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.owner_id:
            await interaction.response.send_message("To prywatny panel innego użytkownika.", ephemeral=True); return False
        return True
    @discord.ui.button(label="1", style=discord.ButtonStyle.primary, emoji="🎖️", custom_id="liga:btn1")
    async def btn1(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(LigaModal1(_get_liga(self.owner_id)))
    @discord.ui.button(label="2", style=discord.ButtonStyle.primary, emoji="🏅", custom_id="liga:btn2")
    async def btn2(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(LigaModal2(_get_liga(self.owner_id)))
    @discord.ui.button(label="Zapisz", style=discord.ButtonStyle.success, emoji="🔄", custom_id="liga:save")
    async def save(self, interaction: discord.Interaction, button: discord.ui.Button):
        try:
            embed = _make_liga_embed(interaction.guild, _get_liga(self.owner_id))
            await interaction.response.edit_message(embed=embed, view=self)
        except Exception as e:
            logging.exception("Liga.save error: %s", e)
            try: await interaction.response.send_message("Błąd przy zapisie/odświeżeniu.", ephemeral=True)
            except: pass
    @discord.ui.button(label="Wyczyść", style=discord.ButtonStyle.danger, emoji="🧹", custom_id="liga:clear")
    async def clear(self, interaction: discord.Interaction, button: discord.ui.Button):
        LIGA_SESSIONS[self.owner_id] = _new_liga()
        await interaction.response.edit_message(
            embed=_make_liga_embed(interaction.guild, LIGA_SESSIONS[self.owner_id]), view=self
        )

_cmd_kwargs_liga = {"name": "liga", "description": "Policz tytuł z medali (prywatny panel)"}
if GUILD: _cmd_kwargs_liga["guild"] = GUILD
@tree.command(**_cmd_kwargs_liga)
async def liga(interaction: discord.Interaction):
    try:
        s = _get_liga(interaction.user.id)
        view = LigaView(interaction.user.id)
        embed = _make_liga_embed(interaction.guild, s)
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)
    except Exception as e:
        logging.exception("/liga error: %s", e)
        await interaction.response.send_message("Nie udało się otworzyć panelu. Spróbuj ponownie.", ephemeral=True)

# ==============================================================
# ========================= /ZBIERACZ ==========================
# ==============================================================

def required_today(current: int, days_left: int, target: int, multiplier: float = 1.35) -> int:
    """
    Ile trzeba zdobyć DZIŚ, żeby po 'days_left' kolejnych mnożnikach (×multiplier)
    osiągnąć 'target'. Dni do końca = liczba pełnych PRZYSZŁYCH mnożników.
    """
    days_left = max(0, int(days_left))
    current = max(0, int(current))
    target = max(0, int(target))
    factor = multiplier ** days_left
    needed_base = target / factor
    need_today = max(0, math.ceil(needed_base - current))
    return need_today

class ZbieraczModal(discord.ui.Modal, title="Zbieracz — kalkulator"):
    def __init__(self):
        super().__init__(custom_id="zbieracz:modal")
        self.cur = discord.ui.TextInput(label="Twoje punkty teraz", placeholder="np. 12 345", required=True)
        self.days = discord.ui.TextInput(label="Dni do końca (pełne do mnożnika)", placeholder="np. 3", required=True, max_length=3)
        self.goal = discord.ui.TextInput(label="Cel punktowy", placeholder="np. 100 000", required=True)
        self.add_item(self.cur); self.add_item(self.days); self.add_item(self.goal)

    async def on_submit(self, interaction: discord.Interaction):
        try:
            current = _to_int(self.cur.value)
            days_left = _to_int(self.days.value)
            goal = _to_int(self.goal.value)

            need = required_today(current, days_left, goal, 1.35)
            factor = 1.35 ** max(0, days_left)
            projected = (current + need) * factor

            emb = discord.Embed(title="📦 Zbieracz — wynik", color=0x00A67E)
            emb.add_field(name="🎯 Cel", value=f"**{fmt_int(goal)}** pkt", inline=True)
            emb.add_field(name="⏳ Dni do końca", value=f"**{days_left}**", inline=True)
            emb.add_field(name="✳️ Mnożnik", value=f"**×1.35** / dzień", inline=True)
            emb.add_field(name="🧮 Musisz zdobyć DZIŚ", value=f"**{fmt_int(need)}** pkt", inline=False)
            emb.add_field(name="🔮 Po tylu pkt. dziś, na koniec będzie", value=f"**{fmt_int(projected)}** pkt", inline=False)
            emb.set_footer(text="Dni do końca = liczba pełnych mnożników ×1.35, które jeszcze zajdą po dzisiejszym dniu.")
            await interaction.response.send_message(embed=emb, ephemeral=True)
        except Exception as e:
            logging.exception("Zbieracz error: %s", e)
            await interaction.response.send_message("Błąd podczas obliczeń. Sprawdź wartości.", ephemeral=True)

_cmd_kwargs_zb = {"name": "zbieracz", "description": "Ile musisz zdobyć dziś w evencie Zbieracz, by dobić do celu?"}
if GUILD: _cmd_kwargs_zb["guild"] = GUILD

@tree.command(**_cmd_kwargs_zb)
async def zbieracz(interaction: discord.Interaction):
    try:
        await interaction.response.send_modal(ZbieraczModal())
    except Exception as e:
        logging.exception("/zbieracz error: %s", e)
        await interaction.response.send_message("Nie udało się otworzyć kalkulatora.", ephemeral=True)

# ========== /shutdown (opcjonalnie) ==========
if OWNER_ID:
    try: OWNER_ID_INT = int(OWNER_ID)
    except: OWNER_ID_INT = None
else:
    OWNER_ID_INT = None

if OWNER_ID_INT:
    _sd_kwargs = {"name": "shutdown", "description": "Wyłącz bota (tylko właściciel)."}
    if GUILD: _sd_kwargs["guild"] = GUILD
    @tree.command(**_sd_kwargs)
    async def shutdown(interaction: discord.Interaction):
        if interaction.user.id != OWNER_ID_INT:
            return await interaction.response.send_message("Brak uprawnień.", ephemeral=True)
        await interaction.response.send_message("Wyłączam się... 👋", ephemeral=True)
        await client.close()

# ========== START ==========
@client.event
async def on_ready():
    logging.basicConfig(level=logging.INFO)
    logging.info(f"Zalogowano jako {client.user} (id: {client.user.id})")

client.run(TOKEN)
