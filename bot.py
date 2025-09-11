# bot.py
from __future__ import annotations
import os, re, math, logging, sys, asyncio
from typing import Dict, List, Tuple, Optional, Set
from datetime import datetime, timedelta, timezone

import discord
from discord import app_commands
from dotenv import load_dotenv

# ===================== ENV / KONFIG =====================
load_dotenv(override=True)

def _clean_token(raw: str) -> str:
    t = (raw or "").strip().strip('"').strip("'")
    if t.lower().startswith("bot "):
        t = t[4:].strip()
    return t

TOKEN = _clean_token(os.getenv("DISCORD_TOKEN") or "")
HUB_ID = int(os.getenv("EMOJI_HUB_ID") or 0)

def _parse_ids(s: str) -> List[int]:
    parts = re.split(r"[,\s;]+", (s or "").strip())
    out: List[int] = []
    for p in parts:
        if not p:
            continue
        try:
            out.append(int(p))
        except:
            logging.warning(f"Pominięto niepoprawne ID: {p!r}")
    return out

GUILD_IDS: List[int] = _parse_ids(os.getenv("GUILD_IDS", ""))  # podaj ID(y) serwerów, na których rejestrujemy komendy
RUN_MODE = (os.getenv("RUN_MODE") or "bot").strip().lower()    # bot | purge_global | purge_guild | purge_all

if not TOKEN:
    raise RuntimeError("Brak DISCORD_TOKEN (sprawdź .env).")

# ====== STAŁE „PrimeTime” – tylko na głównym serwerze
TARGET_GUILD_ID = 1016796563227541574
WATCH_CHANNEL_ID = 1414146583666364447   # kanał z wiadomościami „A new EM: PT …”
SIGNUP_CHANNEL_ID = 1415624731293646891  # kanał z panelem reakcji

ROLE_300GL_ID = 1415630918529454081      # 300gl
ROLE_200OR_ID = 1415631072246628433      # 200or
ROLE_200BTH_ID = 1415631110351622224     # 200bth

TRIGGER_BOT_USER_ID = 1414146769436147783  # autor wiadomości z triggerami

EMOJI_GL = "🟢"
EMOJI_OR = "🟡"
EMOJI_BTH = "🌊"

SIGNUP_MARKER = "## PrimeTime na Ruble"
SIGNUP_INFO = "Kliknij odpowiednie emoji by dostać ping TYLKO przy następnej premce na ruble:"

# cron co 10 min o :03, :13, :23, :33, :43, :53
CRON_MINUTES = {3, 13, 23, 33, 43, 53}

# ================= LOGI =================
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("discord")
logger.setLevel(logging.INFO)
log = logging.getLogger(__name__)

# ================== PURGE TRYBY ==================
intents_min = discord.Intents.none()
intents_min.guilds = True

async def _purge_global():
    class Cleaner(discord.Client):
        def __init__(self):
            super().__init__(intents=intents_min)
            self.tree = app_commands.CommandTree(self)
        async def setup_hook(self):
            self.tree.clear_commands(guild=None)
            await self.tree.sync()
            left = await self.tree.fetch_commands()
            log.info(f"[PURGE_GLOBAL] Globalne po czyszczeniu: {[c.name for c in left]}")
            await self.close()
    Cleaner().run(TOKEN)

async def _purge_guilds(guild_ids: List[int]):
    if not guild_ids:
        log.error("Brak GUILD_IDS do purge_guild.")
        return
    class Cleaner(discord.Client):
        def __init__(self, gids: List[int]):
            super().__init__(intents=intents_min)
            self.tree = app_commands.CommandTree(self)
            self.gids = gids
        async def setup_hook(self):
            for gid in self.gids:
                g = discord.Object(id=gid)
                self.tree.clear_commands(guild=g)
                await self.tree.sync(guild=g)
                left = await self.tree.fetch_commands(guild=g)
                log.info(f"[PURGE_GUILD] {gid}: {[c.name for c in left]}")
            await self.close()
    Cleaner(guild_ids).run(TOKEN)

if RUN_MODE in {"purge_global", "purge_guild", "purge_all"}:
    if RUN_MODE in {"purge_global", "purge_all"}:
        try:
            import asyncio
            asyncio.run(_purge_global())
        except RuntimeError:
            discord.Client(intents=intents_min).close()
    if RUN_MODE in {"purge_guild", "purge_all"}:
        try:
            import asyncio
            asyncio.run(_purge_guilds(GUILD_IDS))
        except RuntimeError:
            discord.Client(intents=intents_min).close()
    sys.exit(0)

# ================== INTENTS / KLIENT ==================
intents = discord.Intents.default()
intents.guilds = True
intents.members = True               # wymagane (włącz w Dev Portal)
intents.message_content = True       # wymagane (włącz w Dev Portal)
intents.reactions = True

class MyClient(discord.Client):
    def __init__(self):
        super().__init__(intents=intents)
        self.tree = app_commands.CommandTree(self)
        self.signup_message_id: Optional[int] = None
        self._poll_task: Optional[asyncio.Task] = None
        self._seen_message_ids: Set[int] = set()
        self._last_poll_ts: datetime = datetime.now(timezone.utc) - timedelta(minutes=15)

    async def setup_hook(self):
        try:
            self.tree.clear_commands(guild=None)
            await self.tree.sync()
            log.info("Globalne komendy wyczyszczone.")
        except Exception as e:
            log.warning(f"Nie udało się wyczyścić globalnych: {e}")

        if not GUILD_IDS:
            for cmd in ALL_CMDS:
                try: self.tree.add_command(cmd)
                except Exception as e: log.warning(f"add_command (global) {cmd.name}: {e}")
            await self.tree.sync()
            log.info("Zsynchronizowano globalnie (brak GUILD_IDS).")
        else:
            for gid in GUILD_IDS:
                gobj = discord.Object(id=gid)
                for cmd in ALL_CMDS:
                    try: self.tree.add_command(cmd, guild=gobj)
                    except Exception as e: log.warning(f"add_command (guild={gid}) {cmd.name}: {e}")
                synced = await self.tree.sync(guild=gobj)
                log.info(f"Zsynchronizowano {len(synced)} komend dla gildii {gid}")
                try:
                    existing = await self.tree.fetch_commands(guild=gobj)
                    log.info(f"GUILD {gid} → {[c.name for c in existing]}")
                except Exception as e:
                    log.warning(f"fetch_commands({gid}) nieudane: {e}")

        await self._post_signup_message()
        if self._poll_task is None:
            self._poll_task = asyncio.create_task(self._poll_loop())
        asyncio.create_task(self._post_signup_after_ready())

    async def _post_signup_after_ready(self):
        await self.wait_until_ready()
        await asyncio.sleep(2)
        if not self.signup_message_id:
            await self._post_signup_message()

    def _perm_report(self, ch: discord.TextChannel, me: discord.Member) -> Dict[str, bool]:
        p = ch.permissions_for(me)
        return {
            "view_channel": p.view_channel,
            "send_messages": p.send_messages,
            "read_message_history": p.read_message_history,
            "add_reactions": p.add_reactions,
            "manage_messages": p.manage_messages,
            "mention_everyone/roles": p.mention_everyone,
            "manage_roles (global)": me.guild_permissions.manage_roles,
        }

    async def _post_signup_message(self):
        guild = self.get_guild(TARGET_GUILD_ID)
        if not guild:
            log.warning("[SIGNUP] Brak docelowej gildii albo bot nie jest na serwerze.")
            return
        ch = guild.get_channel(SIGNUP_CHANNEL_ID)
        if not isinstance(ch, discord.TextChannel):
            log.warning("[SIGNUP] Nie widzę kanału zapisów (zły ID? brak dostępu?).")
            return

        me = guild.get_member(self.user.id) if self.user else None
        if not isinstance(me, discord.Member):
            log.warning("[SIGNUP] Nie mogę pobrać siebie (Member).")
            return

        rep = self._perm_report(ch, me)
        log.info(f"[SIGNUP] Perms w kanale {ch.id}: {rep}")

        try:
            async for m in ch.history(limit=50, oldest_first=False):
                if m.author.id == self.user.id and SIGNUP_MARKER in (m.content or ""):
                    self.signup_message_id = m.id
                    log.info(f"[SIGNUP] Znalazłem istniejący panel: {m.id}")
                    return
        except Exception as e:
            log.warning(f"[SIGNUP] Nie mogę czytać historii: {e}")

        if not (rep["view_channel"] and rep["send_messages"] and rep["add_reactions"]):
            log.warning("[SIGNUP] Brakuje uprawnień do utworzenia panelu.")
            return

        lines = [
            SIGNUP_MARKER,
            SIGNUP_INFO,
            "",
            f"{EMOJI_GL} 300% PrimeTime na głownym serwerze",
            f"{EMOJI_OR} 200% PrimeTime na zewnętrzynych",
            f"{EMOJI_BTH} 200% PrimeTime na horyzoncie",
        ]
        msg = await ch.send("\n".join(lines))
        self.signup_message_id = msg.id
        for e in (EMOJI_GL, EMOJI_OR, EMOJI_BTH):
            try:
                await msg.add_reaction(e)
            except Exception as e:
                log.warning(f"[SIGNUP] add_reaction {e}")

    async def _poll_loop(self):
        await self.wait_until_ready()
        while not self.is_closed():
            try:
                now = datetime.now(timezone.utc)
                minute = now.minute
                if minute in CRON_MINUTES:
                    await self._poll_once()
                    await asyncio.sleep(60)
                else:
                    await asyncio.sleep(5)
            except Exception as e:
                log.warning(f"[POLL] wyjątek: {e}")
                await asyncio.sleep(10)

    async def _poll_once(self):
        guild = self.get_guild(TARGET_GUILD_ID)
        if not guild:
            return
        ch = guild.get_channel(WATCH_CHANNEL_ID)
        if not isinstance(ch, discord.TextChannel):
            return
        cutoff = self._last_poll_ts
        newest_ts = cutoff
        try:
            async for m in ch.history(limit=50, oldest_first=False, after=cutoff):
                newest_ts = max(newest_ts, m.created_at or newest_ts)
                if m.id in self._seen_message_ids:
                    continue
                if m.author.id != TRIGGER_BOT_USER_ID:
                    continue
                await self._maybe_trigger_from_text(m.content or "")
                self._seen_message_ids.add(m.id)
        except Exception as e:
            log.warning(f"[POLL] history error: {e}")
        self._last_poll_ts = newest_ts or datetime.now(timezone.utc)

    async def _maybe_trigger_from_text(self, text: str):
        s = (text or "").lower()
        if ("a new em: pt 300% is starting" in s and "goodgame empire" in s) or ("a new em: pt 350% is starting" in s and "goodgame empire" in s):
            await self._fire_ping_and_cleanup(kind="300gl", role_id=ROLE_300GL_ID, label="300% PrimeTime na głównym serwerze")
        elif ("a new em: pt 200% is starting" in s and "the outer realms" in s):
            await self._fire_ping_and_cleanup(kind="200or", role_id=ROLE_200OR_ID, label="200% PrimeTime na zewnętrzynych")
        elif ("a new em: pt 200% is starting" in s and "beyond the horizon" in s):
            await self._fire_ping_and_cleanup(kind="200bth", role_id=ROLE_200BTH_ID, label="200% PrimeTime na horyzoncie")

    async def _fire_ping_and_cleanup(self, kind: str, role_id: int, label: str):
        guild = self.get_guild(TARGET_GUILD_ID)
        if not guild:
            return
        ch = guild.get_channel(WATCH_CHANNEL_ID)
        if not isinstance(ch, discord.TextChannel):
            return
        role = guild.get_role(role_id)
        if not role:
            log.warning(f"[PING] Brak roli {role_id}")
            return

        members_with_role = [m for m in guild.members if role in m.roles]
        if not members_with_role:
            log.info(f"[PING] Nikt nie zapisał się na {label}, pomijam ping.")
            return

        mention_line = role.mention
        can_edit_mentionable = guild.me.guild_permissions.manage_roles and role.position < guild.me.top_role.position
        changed_flag = False
        try:
            if not role.mentionable and can_edit_mentionable:
                await role.edit(mentionable=True, reason="Tymczasowo, by pingnąć zapisanych")
                changed_flag = True
        except Exception as e:
            log.warning(f"[PING] Nie mogę ustawić mentionable dla roli {role.id}: {e}")

        try:
            await ch.send(f"{mention_line} — {label} wystartował!")
        except Exception as e:
            log.warning(f"[PING] Nie mogę wysłać pingu: {e}")

        if changed_flag:
            try:
                await role.edit(mentionable=False, reason="Przywrócenie poprzedniego stanu")
            except Exception as e:
                log.warning(f"[PING] Nie mogę cofnąć mentionable: {e}")

        for m in members_with_role:
            try:
                await m.remove_roles(role, reason="Jednorazowy ping wykorzystany")
            except Exception as e:
                log.warning(f"[CLEANUP] remove_roles({m.id}): {e}")

        if self.signup_message_id:
            try:
                signup_ch = guild.get_channel(SIGNUP_CHANNEL_ID)
                if isinstance(signup_ch, discord.TextChannel):
                    msg = await signup_ch.fetch_message(self.signup_message_id)
                    target_emoji = EMOJI_GL if kind=="300gl" else EMOJI_OR if kind=="200or" else EMOJI_BTH
                    for m in members_with_role:
                        try:
                            await msg.remove_reaction(target_emoji, m)
                        except Exception:
                            pass
            except Exception as e:
                log.warning(f"[CLEANUP] remove_reaction: {e}")

    async def on_message(self, message: discord.Message):
        if not isinstance(message.channel, discord.TextChannel):
            return
        if message.guild and message.guild.id == TARGET_GUILD_ID and message.channel.id == WATCH_CHANNEL_ID and message.author.id == TRIGGER_BOT_USER_ID:
            if message.id in self._seen_message_ids:
                return
            await self._maybe_trigger_from_text(message.content or "")
            self._seen_message_ids.add(message.id)

    async def on_raw_reaction_add(self, payload: discord.RawReactionActionEvent):
        if payload.guild_id != TARGET_GUILD_ID:
            return
        if payload.channel_id != SIGNUP_CHANNEL_ID:
            return
        if payload.user_id == self.user.id:
            return
        guild = self.get_guild(payload.guild_id)
        if not guild:
            return
        member = guild.get_member(payload.user_id)
        if not member:
            return
        if self.signup_message_id and payload.message_id != self.signup_message_id:
            return

        emoji_str = str(payload.emoji)
        role: Optional[discord.Role] = None
        if emoji_str == EMOJI_GL:
            role = guild.get_role(ROLE_300GL_ID)
        elif emoji_str == EMOJI_OR:
            role = guild.get_role(ROLE_200OR_ID)
        elif emoji_str == EMOJI_BTH:
            role = guild.get_role(ROLE_200BTH_ID)

        if role is None:
            return
        try:
            await member.add_roles(role, reason="Zapisy na 1x ping PrimeTime")
        except Exception as e:
            log.warning(f"[REACTION_ADD] add_roles: {e}")

    async def on_raw_reaction_remove(self, payload: discord.RawReactionActionEvent):
        if payload.guild_id != TARGET_GUILD_ID:
            return
        if payload.channel_id != SIGNUP_CHANNEL_ID:
            return
        if self.signup_message_id and payload.message_id != self.signup_message_id:
            return

        guild = self.get_guild(payload.guild_id)
        if not guild:
            return
        member = guild.get_member(payload.user_id)
        if not member:
            return

        emoji_str = str(payload.emoji)
        role: Optional[discord.Role] = None
        if emoji_str == EMOJI_GL:
            role = guild.get_role(ROLE_300GL_ID)
        elif emoji_str == EMOJI_OR:
            role = guild.get_role(ROLE_200OR_ID)
        elif emoji_str == EMOJI_BTH:
            role = guild.get_role(ROLE_200BTH_ID)
        if role is None:
            return
        try:
            await member.remove_roles(role, reason="Wypis z pingu PrimeTime")
        except Exception as e:
            log.warning(f"[REACTION_REMOVE] remove_roles: {e}")

client = MyClient()
tree = client.tree

# ================== UTYLITKI ==================
def fmt_int(x): return f"{int(round(float(x))):,}".replace(","," ")
def _to_int(s):
    try:
        return int(re.sub(r"[^\d-]", "", str(s)) or "0")
    except:
        return 0
def _pl_dni(n:int)->str:
    return "1 dzień" if int(n)==1 else f"{int(n)} dni"
def _sev_emoji(days:int)->str:
    if days <= 1:
        return "🔴"
    elif days <= 9:
        return "🟠"
    else:
        return "🟢"

HUB_EMOJI_ID: Dict[str,int] = {}
HUB_NAMES = {
 "patronat":["Patronat","patronat"],
 "zetony_budowy":["zetony_budowy"],
 "groszaki":["groszaki"],
 "zetony_ulepszenia":["zetony_ulepszenia"],
 "medale_samuraja":["Medale_samuraja","medale_samuraja"],
 "zetony_samuraja":["Tokeny_samuraja","zetony_samuraja"],
 "medale_chana":["Medale_chana","medale_chana"],
 "tabliczki_nomada":["tabliczki_nomada","tabliczki_chana"],
 "Dekorka":["Dekorka","dekorka"],
 "rubiny":["rubiny"],
 "zloty_medal":["zloty_medal"],
 "srebrny_medal":["srebrny_medal"],
 "brazowy_medal":["brazowy_medal"],
 "szklany_medal":["szklany_medal"],
 "miedziany_medal":["miedziany_medal"],
 "kamienny_medal":["kamienny_medal"],
 "drewniany_medal":["drewniany_medal"],
}
UNI={"charter":"💠","construction":"🧱","sceat":"🪙","upgrade":"🛠️","samurai_medals":"🎖️","samurai_tokens":"🔶","khan_medals":"🏅","khan_tablets":"🪪","decor":"🏛️","rubies":"💎"}
MEDAL_UNI={"gold":"🥇","silver":"🥈","bronze":"🥉","glass":"🪟","copper":"🟠","stone":"🪨","wood":"🪵"}
MEDAL_ALIAS={"gold":"zloty_medal","silver":"srebrny_medal","bronze":"brazowy_medal","glass":"szklany_medal","copper":"miedziany_medal","stone":"kamienny_medal","wood":"drewniany_medal"}

async def load_hub_emoji():
    if not HUB_ID: return
    try:
        g = client.get_guild(HUB_ID) or await client.fetch_guild(HUB_ID)
        emojis = await g.fetch_emojis()
        for e in emojis:
            HUB_EMOJI_ID[e.name] = e.id
    except Exception as e:
        log.warning(f"Nie udało się wczytać emoji z HUB_ID={HUB_ID}: {e}")

def _app(name: str) -> Optional[str]:
    eid = HUB_EMOJI_ID.get(name)
    return f"<:{name}:{eid}>" if eid else None

RES_KEYS={
 "charter":["patronat","Patronat"],
 "construction":["zetony_budowy"],
 "sceat":["groszaki"],
 "upgrade":["zetony_ulepszenia"],
 "samurai_medals":["Medale_samuraja","medale_samuraja"],
 "samurai_tokens":["Tokeny_samuraja","zetony_samuraja"],
 "khan_medals":["Medale_chana","medale_chana"],
 "khan_tablets":["tabliczki_nomada","tabliczki_chana"],
 "decor":["Dekorka","dekorka"],
 "rubies":["rubiny"],
}
def E(key:str)->str:
    for nm in RES_KEYS.get(key, []):
        for nn in HUB_NAMES.get(nm, [nm]):
            s=_app(nn)
            if s: return s
    return UNI.get(key, "•")
def M(key:str)->str:
    alias=MEDAL_ALIAS.get(key)
    if alias:
        for nn in HUB_NAMES.get(alias,[alias]):
            s=_app(nn)
            if s: return s
    return MEDAL_UNI.get(key,"🔸")

COST_PER_POINT={"charter":1,"construction":3,"sceat":4,"upgrade":9,"samurai_medals":50,"samurai_tokens":1380,"khan_medals":3400,"khan_tablets":1950}
LEVEL_COSTS=[310,915,2030,3600,5280,6650,9300,13300,14600,25200]
MELEE=[1,2,3,4,5,6,7,10,13,15]; RANGED=[1,2,3,4,5,6,7,10,13,15]; COURTY=[0,0,0,0,1,3,6,9,12,15]
PL_NAME={"charter":"Żetony patronatu","construction":"Żetony budowy","sceat":"Groszaki","upgrade":"Żetony ulepszenia","samurai_medals":"Medale Samuraja","samurai_tokens":"Żetony Samuraja","khan_medals":"Medale Chana","khan_tablets":"Tabliczki Nomada"}

def calc_points(**spent): return sum((float(v)/COST_PER_POINT[k]) for k,v in spent.items() if v)

def walk_levels(lv,prog,gain):
    lv=max(0,min(10,int(lv))); prog=float(max(0,prog)); pool=float(max(0,gain))
    if lv>=10: return 10,0.0,None,prog+pool
    while lv<10:
        need=LEVEL_COSTS[lv]-prog
        if pool>=need:
            pool-=need; lv+=1; prog=0.0
        else:
            prog+=pool; pool=0.0; break
        if lv==10: return 10,0.0,None,pool
    nxt=LEVEL_COSTS[lv]-prog if lv<10 else None
    return lv,prog,nxt,None

P_PACKS=[{"amount":32500,"price":625000,"limit":1},{"amount":3250,"price":70000,"limit":1},{"amount":3250,"price":79000,"limit":2},{"amount":3250,"price":85000,"limit":3},{"amount":325,"price":7000,"limit":3},{"amount":325,"price":7900,"limit":10},{"amount":325,"price":8800,"limit":50},{"amount":35,"price":700,"limit":5},{"amount":35,"price":800,"limit":10},{"amount":35,"price":900,"limit":50}]
SINGLE_PRICE=35
def best_ruby_cost_for_charters(req:int)->Tuple[int,str,float]:
    req=max(0,int(req))
    if req==0: return 0,"",0.0
    packs=[dict(p) for p in P_PACKS]; packs.sort(key=lambda p:(p["price"]/p["amount"],-p["amount"]))
    rem=req; total=0; buys=[]
    for p in packs:
        if rem<=0: break
        k=min(p["limit"], rem//p["amount"])
        if k>0:
            total+=k*p["price"]; rem-=k*p["amount"]; buys.append((p["amount"],p["price"],k)); p["limit"]-=k
    while rem>0:
        best_i=-1; best=SINGLE_PRICE
        for i,p in enumerate(packs):
            if p["limit"]<=0: continue
            s=min(p["amount"],rem); eff=p["price"]/s
            if eff<best-1e-9:
                best=eff; best_i=i
        if best_i==-1:
            total+=rem*SINGLE_PRICE; buys.append((1,SINGLE_PRICE,rem)); rem=0
        else:
            p=packs[best_i]; total+=p["price"]; buys.append((p["amount"],p["price"],1)); rem=max(0,rem-p["amount"]); p["limit"]-=1
    agg:Dict[Tuple[int,int],int]={}
    for a,pr,c in buys:
        agg[(a,pr)]=agg.get((a,pr),0)+c
    items=sorted(agg.items(), key=lambda kv:(kv[0][1]/kv[0][0],-kv[0][0]))
    plan="\n".join(f"{c}× {a} za {fmt_int(pr)}" for (a,pr),c in items)
    avg= total/req if req>0 else 0.0
    return int(round(total)), plan, avg

def parse_yn_optional(val: str) -> Optional[bool]:
    s = str(val or "").strip().lower()
    if s == "": return None
    if s in ("y","yes","tak","1"): return True
    if s in ("n","no","nie","0"): return False
    return None

def days_until_below(current: int, threshold: int, daily_loss_pct: float) -> int:
    c = float(max(0, int(current)))
    t = float(max(0, int(threshold)))
    r = max(0.0, min(100.0, float(daily_loss_pct))) / 100.0
    if c < t:  return 0
    if c == t: return 1
    if r <= 0.0: return 10**9
    n = math.log(t/c) / math.log(1.0 - r)
    return max(0, math.ceil(n))

def _beri_rate_and_boundary(cur: float) -> Tuple[float, int]:
    if cur < 45_000:
        return 3.0, 0
    elif cur < 95_000:
        return 4.0, 45_000
    elif cur < 145_000:
        return 5.0, 95_000
    else:
        return 7.0, 145_000

def days_until_below_berimond(current: int, threshold: int) -> int:
    c = float(max(0, int(current)))
    t = float(max(0, int(threshold)))
    if c < t: return 0
    if c == t: return 1
    days = 0
    while c > t:
        rate, boundary = _beri_rate_and_boundary(c)
        r = rate / 100.0
        target_in_seg = max(t, float(boundary))
        if c <= target_in_seg:
            break
        n = days_until_below(int(c), int(target_in_seg), rate)
        if n <= 0: n = 1
        days += n
        c = c * ((1.0 - r) ** n)
        if days > 10000: break
    return days

# ================== PANEL DEKORACJI ==================
SESS:Dict[int,dict]={}
def _new_s(): return {"charter":0,"construction":0,"sceat":0,"upgrade":0,"samurai_medals":0,"samurai_tokens":0,"khan_medals":0,"khan_tablets":0,"current_level":0,"current_progress":0,"target_level":0}
def _s(uid:int)->dict:
    if uid not in SESS: SESS[uid]=_new_s()
    return SESS[uid]

ORDER=["charter","sceat","construction","upgrade","samurai_medals","samurai_tokens","khan_medals","khan_tablets"]
def _spent_lines(s):
    parts=[]
    for k in ORDER:
        v=s.get(k,0)
        if v and int(v)>0:
            parts.append(f"{E(k)} **{PL_NAME[k]}:** {fmt_int(v)}")
    return "\n".join(parts) if parts else "—"

def _embed(guild, s, show=False):
    gained=calc_points(charter=s["charter"],construction=s["construction"],sceat=s["sceat"],upgrade=s["upgrade"],samurai_medals=s["samurai_medals"],samurai_tokens=s["samurai_tokens"],khan_medals=s["khan_medals"],khan_tablets=s["khan_tablets"])
    lv,prog,nxt,overflow=walk_levels(s["current_level"],s["current_progress"],gained)
    emb=discord.Embed(title=f"{E('decor')} Dekoracja — panel",color=0x2ecc71)
    emb.add_field(name="🧾 Wydatki",value=_spent_lines(s),inline=False)
    if s["current_level"]>0 or s["current_progress"]>0:
        emb.add_field(name="🧭 Stan początkowy",value=f"Poziom: **{s['current_level']}**\nPunkty w poziomie: **{fmt_int(s['current_progress'])}**",inline=True)
    emb.add_field(name="🧮 Łączne pkt.",value=f"**{fmt_int(gained)}**",inline=True)
    if show:
        if lv<10:
            post=f"❗ Nadwyżka: **{fmt_int(prog)}**\n⏭️ Brakuje: **{fmt_int(nxt)}**"
        else:
            post=f"❗ Nadwyżka po maks.: **{fmt_int(overflow or 0)}**"
        show_lv=max(1,lv); idx=show_lv-1; stats=f"({MELEE[idx]}/{RANGED[idx]}/{COURTY[idx]})"
        post+=f"\n🏛️ Poziom dekoracji: **{show_lv}**  {stats}"
        emb.add_field(name="📈 Postęp",value=post,inline=False)
    if s["charter"]>0:
        rub,plan,avg=best_ruby_cost_for_charters(s["charter"])
        emb.add_field(name=f"{E('rubies')} Koszt rubinów",value=f"Rubiny: **{fmt_int(rub)}**\nPlan:\n{plan}" if plan else f"Rubiny: **{fmt_int(rub)}**",inline=False)
        emb.set_footer(text=f"Średni koszt 1 pkt: {avg:.2f} rub.")
    if show and s["target_level"]:
        target=int(s["target_level"])
        if lv>=10: need=0
        else:
            need=LEVEL_COSTS[lv]-prog
            for L in range(lv+1,target):
                need+=LEVEL_COSTS[L]
        if need>0:
            rub2,plan2,_=best_ruby_cost_for_charters(need)
            emb.add_field(name=f"🎯 Koszt do poziomu {target} (żetony patronatu)",value=(f"Żetony patronatu: **{fmt_int(need)}**\n{E('rubies')} Rubiny: **{fmt_int(rub2)}**\nPlan:\n{plan2}") if plan2 else f"Żetony patronatu: **{fmt_int(need)}**\n{E('rubies')} Rubiny: **{fmt_int(rub2)}**",inline=False)
        elif target<=lv:
            emb.add_field(name="🎯 Cel już osiągnięty",value=f"Masz co najmniej poziom **{target}**.",inline=False)
    return emb

class SpendingModal1(discord.ui.Modal, title="Wydatki — 1/2"):
    def __init__(self, s): super().__init__(custom_id="patronat:m1"); self.s=s
    charter=discord.ui.TextInput(label="Żetony patronatu",required=False)
    sceat=discord.ui.TextInput(label="Groszaki",required=False)
    construction=discord.ui.TextInput(label="Żetony budowy",required=False)
    upgrade=discord.ui.TextInput(label="Żetony ulepszenia",required=False)
    async def on_submit(self,i):
        try:
            self.s["charter"]=_to_int(self.charter.value); self.s["sceat"]=_to_int(self.sceat.value)
            self.s["construction"]=_to_int(self.construction.value); self.s["upgrade"]=_to_int(self.upgrade.value)
            await i.response.send_message("Zapisano (1/2). Kliknij **Zapisz**.",ephemeral=True)
        except:
            await i.response.send_message("Błąd (1/2).",ephemeral=True)

class SpendingModal2(discord.ui.Modal, title="Wydatki — 2/2"):
    def __init__(self, s): super().__init__(custom_id="patronat:m2"); self.s=s
    samurai_medals=discord.ui.TextInput(label="Medale Samuraja",required=False)
    samurai_tokens=discord.ui.TextInput(label="Żetony Samuraja",required=False)
    khan_medals=discord.ui.TextInput(label="Medale Chana",required=False)
    khan_tablets=discord.ui.TextInput(label="Tabliczki Nomada",required=False)
    async def on_submit(self,i):
        try:
            self.s["samurai_medals"]=_to_int(self.samurai_medals.value)
            self.s["samurai_tokens"]=_to_int(self.samurai_tokens.value)
            self.s["khan_medals"]=_to_int(self.khan_medals.value)
            self.s["khan_tablets"]=_to_int(self.khan_tablets.value)
            await i.response.send_message("Zapisano (2/2). Kliknij **Zapisz**.",ephemeral=True)
        except:
            await i.response.send_message("Błąd (2/2).",ephemeral=True)

class StateModal(discord.ui.Modal, title="LVL dekoracji"):
    def __init__(self,s): super().__init__(custom_id="patronat:state"); self.s=s
    level=discord.ui.TextInput(label="Obecny poziom (0–10)",required=False,max_length=2)
    progress=discord.ui.TextInput(label="Punkty wbite w poziom",required=False)
    target=discord.ui.TextInput(label="Docelowy poziom (1–10)",required=False,max_length=2)
    async def on_submit(self,i):
        try:
            self.s["current_level"]=max(0,min(10,_to_int(self.level.value or 0)))
            self.s["current_progress"]=max(0,_to_int(self.progress.value or 0))
            self.s["target_level"]=max(0,min(10,_to_int(self.target.value or 0)))
            await i.response.send_message("Parametry zapisane. Kliknij **Zapisz**.",ephemeral=True)
        except:
            await i.response.send_message("Błąd.",ephemeral=True)

class DekorView(discord.ui.View):
    def __init__(self,uid): super().__init__(timeout=600); self.uid=uid
    async def interaction_check(self,i):
        if i.user.id!=self.uid:
            await i.response.send_message("To prywatny panel innego użytkownika.",ephemeral=True)
            return False
        return True
    @discord.ui.button(label="1",style=discord.ButtonStyle.primary,emoji="🧾")
    async def b1(self,i,_): await i.response.send_modal(SpendingModal1(_s(self.uid)))
    @discord.ui.button(label="2",style=discord.ButtonStyle.primary,emoji="💰")
    async def b2(self,i,_): await i.response.send_modal(SpendingModal2(_s(self.uid)))
    @discord.ui.button(label="LVL dekoracji",style=discord.ButtonStyle.secondary,emoji="🧭")
    async def b3(self,i,_): await i.response.send_modal(StateModal(_s(self.uid)))
    @discord.ui.button(label="Zapisz",style=discord.ButtonStyle.success,emoji="🔄")
    async def b4(self,i,_): await i.response.edit_message(embed=_embed(i.guild,_s(self.uid),True),view=self)
    @discord.ui.button(label="Wyczyść",style=discord.ButtonStyle.danger,emoji="🧹")
    async def b5(self,i,_): SESS[self.uid]=_new_s(); await i.response.edit_message(embed=_embed(i.guild,_s(self.uid),False),view=self)

# ================== KOMENDY ==================
@app_commands.command(name="pomoc",description="Lista komend")
async def pomoc(i:discord.Interaction):
    d=(
        "**/patronat** — panel dekoracji\n"
        "**/liga** — Tytuły z medali\n"
        "**/tytul** — kiedy tracisz bonus z chwały / Berimond\n"
        "**/zbieracz** — ile musisz zdobyć punktów, by spełnić swój cel"
    )
    await i.response.send_message(
        embed=discord.Embed(title="📚 Pomoc",description=d,color=0x3498DB),
        ephemeral=True
    )

@app_commands.command(name="patronat",description="Panel liczenia dekoracji")
async def patronat_cmd(i:discord.Interaction):
    await i.response.send_message(embed=_embed(i.guild,_s(i.user.id),False),view=DekorView(i.user.id),ephemeral=True)

MEDALS=[("gold","Złoty",1000),("silver","Srebrny",950),("bronze","Brązowy",850),("glass","Szklany",700),("copper","Miedziany",500),("stone","Kamienny",300),("wood","Drewniany",100)]
TITLES=["Zadziora","Awanturnik","Rozrabiaka","Wprawny Rozrabiaka","Łowca","Łowca Głów","Wytrawny Łowca","Mistrzowski Łowca","Strażnik","Strażnik Zamkowy","Strażnik Dworu","Strażnik Tronu","Wojownik","Dzielny Wojownik","Doświadczony Wojownik","Bohaterski Wojownik","Pan Wojny","Wielki Pan Wojny","Najwyższy Pan Wojny","Pan Wojny Totalnej","Niszczyciel"]
TITLE_EMOJI="🏆"
PTS={"gold":1000,"silver":950,"bronze":850,"glass":700,"copper":500,"stone":300,"wood":100}

def liga_points(s): return sum(int(s.get(k,0))*PTS[k] for k in PTS)
def title_from_points(t):
    idx=min(t//2000,len(TITLES)-1); cur=TITLES[idx]; nxt=TITLES[idx+1] if idx+1<len(TITLES) else None
    inb=t%2000; need=0 if nxt is None else (2000-inb if inb>0 else 2000); return idx,cur,nxt,inb,need
WEAK=list(reversed(MEDALS))
def weak_one(need):
    for k,_,p in WEAK:
        if p>=need: return k
    return None
def weak_two(need):
    for j in range(len(WEAK)):
        for i2 in range(j+1):
            k1,_,p1=WEAK[i2]; k2,_,p2=WEAK[j]
            if p1+p2>=need: return k1,k2
    return WEAK[0][0],WEAK[0][0]

LIGA:Dict[int,dict]={}
def _new_l(): return {k:0 for k,_,_ in MEDALS}
def _l(uid):
    if uid not in LIGA: LIGA[uid]=_new_l()
    return LIGA[uid]

def _medals_text(s):
    parts=[]
    for k,n,_ in MEDALS:
        c=int(s.get(k,0))
        if c>0: parts.append(f"{M(k)} × **{fmt_int(c)}**")
    return "\n".join(parts) if parts else "—"

def _liga_embed(g,s):
    t=liga_points(s); idx,cur,nxt,inb,need=title_from_points(t)
    emb=discord.Embed(title="🏰 Liga — tytuły z medali",color=0x5865F2)
    emb.add_field(name="🎖️ Medale",value=_medals_text(s),inline=False)
    if nxt:
        post=f"❗ Nadwyżka: **{fmt_int(inb)}**\n⏭️ Brakuje: **{fmt_int(need)}**\n"
        one=weak_one(need)
        if one: post+=f"🗓️ Dziś wystarczy: {M(one)} ({PTS[one]})"
        else:
            k1,k2=weak_two(need); post+=f"🗓️ W 2 dni: {M(k1)} + {M(k2)} ({PTS[k1]}+{PTS[k2]})"
        emb.add_field(name="🏆 Tytuł",value=f"{TITLE_EMOJI} **{cur}** → następny: **{nxt}**",inline=True)
        emb.add_field(name="📈 Postęp",value=post,inline=False)
    else:
        emb.add_field(name="🏆 Tytuł",value=f"{TITLE_EMOJI} **{cur}** (MAX)",inline=True)
        emb.add_field(name="📈 Postęp",value=f"❗ Nadwyżka po maks.: **{fmt_int(inb)}**",inline=False)
    return emb

class L1(discord.ui.Modal, title="Medale — 1/2"):
    def __init__(self,s): super().__init__(custom_id="liga:m1"); self.s=s
    gold=discord.ui.TextInput(label="Złoty",required=False)
    silver=discord.ui.TextInput(label="Srebrny",required=False)
    bronze=discord.ui.TextInput(label="Brązowy",required=False)
    glass=discord.ui.TextInput(label="Szklany",required=False)
    async def on_submit(self,i):
        try:
            self.s["gold"]=_to_int(self.gold.value); self.s["silver"]=_to_int(self.silver.value); self.s["bronze"]=_to_int(self.bronze.value); self.s["glass"]=_to_int(self.glass.value)
            await i.response.send_message("Zapisano (1/2). Kliknij **Zapisz**.",ephemeral=True)
        except:
            await i.response.send_message("Błąd (1/2).",ephemeral=True)

class L2(discord.ui.Modal, title="Medale — 2/2"):
    def __init__(self,s): super().__init__(custom_id="liga:m2"); self.s=s
    copper=discord.ui.TextInput(label="Miedziany",required=False)
    stone=discord.ui.TextInput(label="Kamienny",required=False)
    wood=discord.ui.TextInput(label="Drewniany",required=False)
    async def on_submit(self,i):
        try:
            self.s["copper"]=_to_int(self.copper.value); self.s["stone"]=_to_int(self.stone.value); self.s["wood"]=_to_int(self.wood.value)
            await i.response.send_message("Zapisano (2/2). Kliknij **Zapisz**.",ephemeral=True)
        except:
            await i.response.send_message("Błąd (2/2).",ephemeral=True)

class LigaView(discord.ui.View):
    def __init__(self,uid): super().__init__(timeout=600); self.uid=uid
    async def interaction_check(self,i):
        if i.user.id!=self.uid:
            await i.response.send_message("To prywatny panel innego użytkownika.",ephemeral=True)
            return False
        return True
    @discord.ui.button(label="1",style=discord.ButtonStyle.primary,emoji="🎖️")
    async def a(self,i,_): await i.response.send_modal(L1(_l(self.uid)))
    @discord.ui.button(label="2",style=discord.ButtonStyle.primary,emoji="🏅")
    async def b(self,i,_): await i.response.send_modal(L2(_l(self.uid)))
    @discord.ui.button(label="Zapisz",style=discord.ButtonStyle.success,emoji="🔄")
    async def c(self,i,_): await i.response.edit_message(embed=_liga_embed(i.guild,_l(self.uid)),view=self)
    @discord.ui.button(label="Wyczyść",style=discord.ButtonStyle.danger,emoji="🧹")
    async def d(self,i,_): LIGA[self.uid]=_new_l(); await i.response.edit_message(embed=_liga_embed(i.guild,_l(self.uid)),view=self)

@app_commands.command(name="liga",description="Tytuły z medali")
async def liga_cmd(i:discord.Interaction):
    await i.response.send_message(embed=_liga_embed(i.guild,_l(i.user.id)),view=LigaView(i.user.id),ephemeral=True)

def required_today(current:int,days_left:int,target:int,mult:float=1.35)->int:
    days_left=max(0,int(days_left)); current=max(0,int(current)); target=max(0,int(target))
    need_base= target/(mult**days_left); return max(0, math.ceil(need_base-current))

class ZbieraczModal(discord.ui.Modal, title="Zbieracz — kalkulator"):
    def __init__(self): super().__init__(custom_id="zbieracz:m")
    cur=discord.ui.TextInput(label="Twoje punkty teraz",required=True)
    days=discord.ui.TextInput(label="Dni do końca",required=True,max_length=3)
    goal=discord.ui.TextInput(label="Cel punktowy",required=True)
    async def on_submit(self,i):
        try:
            cur=_to_int(self.cur.value); days=_to_int(self.days.value); goal=_to_int(self.goal.value)
            need=required_today(cur,days,goal,1.35); projected=(cur+need)*(1.35**max(0,days))
            e=discord.Embed(title="📦 Zbieracz — wynik",color=0x00A67E)
            e.add_field(name="🎯 Cel",value=f"**{fmt_int(goal)}** pkt",inline=True)
            e.add_field(name="⏳ Dni do końca",value=f"**{days}**",inline=True)
            e.add_field(name="🧮 Musisz zdobyć DZIŚ",value=f"**{fmt_int(need)}** pkt",inline=False)
            e.add_field(name="🔮 Po tylu pkt. dziś, na koniec będzie",value=f"**{fmt_int(projected)}** pkt",inline=False)
            await i.response.send_message(embed=e,ephemeral=True)
        except:
            await i.response.send_message("Błąd podczas obliczeń.",ephemeral=True)

@app_commands.command(name="zbieracz",description="ile musisz zdobyć punktów, by spełnić swój cel")
async def zbieracz_cmd(i:discord.Interaction):
    await i.response.send_modal(ZbieraczModal())

@app_commands.command(name="tytul", description="kiedy tracisz bonus z chwały / Berimond")
async def tytul_cmd(i: discord.Interaction):
    class TytulModal(discord.ui.Modal, title="Tytuły — dane"):
        def __init__(self): super().__init__(custom_id="tytul:m")
        glory = discord.ui.TextInput(label="Aktualna chwała (opcjonalnie)",required=False,placeholder="np. 30500000")
        sub = discord.ui.TextInput(label="Subskrypcja? (Y/N, opcjonalnie)",required=False,placeholder="Y / N")
        beri = discord.ui.TextInput(label="Punkty Berimond (opcjonalnie)",required=False,placeholder="np. 240000")
        async def on_submit(self, inter: discord.Interaction):
            try:
                speed_threshold = 22_724_097
                out_lines: List[str] = []
                out_lines.append("🎖️ Tytuły")
                glory_raw = (self.glory.value or "").strip()
                sub_raw = (self.sub.value or "").strip()
                beri_raw = (self.beri.value or "").strip()
                if glory_raw:
                    chwala = _to_int(glory_raw)
                    sub_opt = parse_yn_optional(sub_raw)
                    if sub_opt is None:
                        daily_loss = 10.0
                    else:
                        daily_loss = 8.0 if sub_opt else 10.0
                    dni = days_until_below(chwala, speed_threshold, daily_loss)
                    out_lines.append("➡️Chwała:")
                    out_lines.append(f"Aktualnie: {fmt_int(chwala)}")
                    if chwala < speed_threshold:
                        out_lines.append(f"{_sev_emoji(0)}Utrata bonusu: JUŻ.")
                    elif chwala == speed_threshold:
                        out_lines.append(f"{_sev_emoji(1)}Utrata bonusu za 1 dzień.")
                    else:
                        out_lines.append(f"{_sev_emoji(dni)}Utrata bonusu za { _pl_dni(dni) }.")
                if beri_raw:
                    ber = _to_int(beri_raw)
                    T1, T2, T3 = 195_000, 95_000, 37_500
                    d1 = days_until_below_berimond(ber, T1)
                    d2 = days_until_below_berimond(ber, T2)
                    d3 = days_until_below_berimond(ber, T3)
                    out_lines.append("➡️Berimond:")
                    out_lines.append(f"Aktualnie: {fmt_int(ber)}")
                    def line(cur, thr, days, text):
                        if cur < thr:
                            return f"{_sev_emoji(0)} {text} (< {fmt_int(thr)}): JUŻ."
                        elif cur == thr:
                            return f"{_sev_emoji(1)} {text} (< {fmt_int(thr)}): za 1 dzień."
                        else:
                            return f"{_sev_emoji(days)} {text} (< {fmt_int(thr)}): za { _pl_dni(days) }."
                    out_lines.append(line(ber, T1, d1, "-20% żywności na Zieleni"))
                    out_lines.append(line(ber, T2, d2, "-20% żywności na Zieleni (kolejne -20%)"))
                    out_lines.append(line(ber, T3, d3, "-20% produkcji na Krainach (dodatkowo)"))
                if len(out_lines)==1:
                    await inter.response.send_message("Podaj chociaż chwałę lub punkty Berimond.",ephemeral=True)
                    return
                e = discord.Embed(description="\n".join(out_lines), color=0xE67E22)
                await inter.response.send_message(embed=e, ephemeral=True)
            except Exception:
                await inter.response.send_message("Błąd obliczeń.", ephemeral=True)
    await i.response.send_modal(TytulModal())

# >>> Narzędzie diagnostyczne: wymuś panel + raport uprawnień
@app_commands.command(name="ptsetup", description="[ADMIN] Wymuś panel PrimeTime i pokaż uprawnienia")
@app_commands.checks.has_permissions(manage_guild=True)
async def ptsetup_cmd(i: discord.Interaction):
    if not i.guild or i.guild.id != TARGET_GUILD_ID:
        return await i.response.send_message("Ta komenda działa tylko na głównym serwerze.", ephemeral=True)
    await client._post_signup_message()
    g = i.guild
    ch = g.get_channel(SIGNUP_CHANNEL_ID)
    me = g.get_member(client.user.id) if client.user else None
    rep = client._perm_report(ch, me) if isinstance(ch, discord.TextChannel) and isinstance(me, discord.Member) else {}
    await i.response.send_message(
        f"OK. signup_message_id={client.signup_message_id}\nPerms: {rep}",
        ephemeral=True
    )

ALL_CMDS=[pomoc, patronat_cmd, liga_cmd, tytul_cmd, zbieracz_cmd, ptsetup_cmd]

# ================== LIFECYCLE ==================
@client.event
async def on_ready():
    await client.change_presence(activity=None, status=discord.Status.online)
    await load_hub_emoji()
    log.info(f"Wczytano emoji z huba: {len(HUB_EMOJI_ID)}")
    gl = await client.tree.fetch_commands()
    log.info(f"GLOBAL → {[c.name for c in gl]}")
    for gid in GUILD_IDS:
        cmds = await client.tree.fetch_commands(guild=discord.Object(id=gid))
        log.info(f"GUILD {gid} → {[c.name for c in cmds]}")

# ================== START ==================
client.run(TOKEN)
