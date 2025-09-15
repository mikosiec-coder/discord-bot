from __future__ import annotations
import os, re, math, logging, asyncio
from typing import Dict, List, Tuple, Optional, Set
from datetime import datetime, timedelta, timezone
from dotenv import load_dotenv
import discord
from discord import app_commands

logging.getLogger("discord.client").setLevel(logging.ERROR)
load_dotenv(override=True)

def _clean_token(raw: str) -> str:
    t = (raw or "").strip().strip('"').strip("'")
    if t.lower().startswith("bot "):
        t = t[4:].strip()
    return t

TOKEN = _clean_token(os.getenv("DISCORD_TOKEN") or "")
if not TOKEN:
    raise RuntimeError("Brak DISCORD_TOKEN (.env).")

def _parse_ids(s: str) -> List[int]:
    parts = re.split(r"[,\s;]+", (s or "").strip())
    out: List[int] = []
    for p in parts:
        if not p:
            continue
        try:
            out.append(int(p))
        except:
            pass
    return out

GUILD_IDS: List[int] = _parse_ids(os.getenv("GUILD_IDS", ""))

MAIN_GUILD_ID = 1016796563227541574
EM_CHANNEL_ID = 1414146583666364447
SIGNUP_CHANNEL_ID = 1415624731293646891
SIGNUP_MESSAGE_ID_ENV = int(os.getenv("SIGNUP_MESSAGE_ID") or 0)
SELF_BOT_ID = 1413952299989995720

ROLE_PREMKA300 = 1415630918529454081
ROLE_PREMKAZWK = 1415631072246628433
ROLE_PREMKAHORY = 1415631110351622224

EMOJI_300GL = "🟩"
EMOJI_200OR  = "🟨"
EMOJI_200BTH = "🟦"

MATCH_300GL = (
    "A new EM: PT 300% is starting in GoodGame Empire.",
    "A new EM: PT 350% is starting in GoodGame Empire.",
)
MATCH_200OR = ("A new EM: PT 200% is starting in the Outer Realms.",)
MATCH_200BTH = ("A new EM: PT 200% is starting in Beyond the Horizon.",)

SIGNUP_MARKER = "## PrimeTime na Ruble"
SIGNUP_LEAD = "Kliknij odpowiednie emoji by dostać ping TYLKO przy następnej premce na ruble:"
SIGNUP_TEXT = (
    f"{SIGNUP_MARKER}\n"
    f"{SIGNUP_LEAD}\n\n"
    f"{EMOJI_300GL} — **300% PrimeTime na głównym serwerze**\n"
    f"{EMOJI_200OR} — **200% PrimeTime na zewnętrznych**\n"
    f"{EMOJI_200BTH} — **200% PrimeTime na horyzoncie**\n"
    f"\nPo pingnięciu przy najbliższym wydarzeniu rola i Twoja reakcja zostaną zdjęte (one-shot)."
)

EMOJI_TO_ROLE = {
    EMOJI_300GL: ROLE_PREMKA300,
    EMOJI_200OR: ROLE_PREMKAZWK,
    EMOJI_200BTH: ROLE_PREMKAHORY,
}

logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)

intents = discord.Intents.default()
intents.message_content = True
intents.members = True
intents.guilds = True
intents.reactions = True
intents.emojis = True

class MyClient(discord.Client):
    def __init__(self):
        super().__init__(intents=intents)
        self.tree = app_commands.CommandTree(self)
        self.signup_message_id: Optional[int] = None
        self.pending: Dict[int, Set[int]] = {ROLE_PREMKA300:set(), ROLE_PREMKAZWK:set(), ROLE_PREMKAHORY:set()}
        self.announced: Set[Tuple[int, int]] = set()
        self.last_ping: Dict[int, datetime] = {}
        self.pt_task: Optional[asyncio.Task] = None
        self.start_time: datetime = datetime.now(timezone.utc)

    async def setup_hook(self):
        try:
            self.tree.clear_commands(guild=None)
            await self.tree.sync()
        except Exception:
            pass
        if not GUILD_IDS:
            for cmd in ALL_CMDS:
                try:
                    self.tree.add_command(cmd)
                except Exception:
                    pass
            await self.tree.sync()
        else:
            for gid in GUILD_IDS:
                gobj = discord.Object(id=gid)
                for cmd in ALL_CMDS:
                    try:
                        self.tree.add_command(cmd, guild=gobj)
                    except Exception:
                        pass
                try:
                    await self.tree.sync(guild=gobj)
                except Exception:
                    pass
                try:
                    await self.tree.fetch_commands(guild=gobj)
                except Exception:
                    pass

    async def on_ready(self):
        await self.change_presence(activity=None, status=discord.Status.online)
        await load_hub_emoji(self)
        await self.ensure_signup_message()
        await self.sync_roles_from_reactions()
        if self.pt_task is None:
            self.pt_task = asyncio.create_task(self.primetime_loop())
        log.info(f"Gotowy jako {self.user} ({self.user.id})")

    async def ensure_signup_message(self):
        guild = self.get_guild(MAIN_GUILD_ID)
        if not guild:
            return
        ch: Optional[discord.TextChannel] = guild.get_channel(SIGNUP_CHANNEL_ID)  # type: ignore
        if not isinstance(ch, discord.TextChannel):
            try:
                ch = await self.fetch_channel(SIGNUP_CHANNEL_ID)  # type: ignore
            except Exception:
                return
        msg: Optional[discord.Message] = None
        if SIGNUP_MESSAGE_ID_ENV:
            try:
                msg = await ch.fetch_message(SIGNUP_MESSAGE_ID_ENV)
            except Exception:
                msg = None
        if msg is None:
            try:
                async for m in ch.history(limit=50):
                    if m.author.id == self.user.id and SIGNUP_MARKER in (m.content or ""):
                        msg = m
                        break
            except Exception:
                msg = None
        if msg is None:
            try:
                msg = await ch.send(SIGNUP_TEXT)
            except Exception:
                msg = None
        if msg:
            self.signup_message_id = msg.id
            await self._ensure_reactions(msg)

    async def sync_roles_from_reactions(self):
        guild = self.get_guild(MAIN_GUILD_ID)
        if not guild or not self.signup_message_id:
            return
        ch: Optional[discord.TextChannel] = guild.get_channel(SIGNUP_CHANNEL_ID)  # type: ignore
        if not isinstance(ch, discord.TextChannel):
            try:
                ch = await self.fetch_channel(SIGNUP_CHANNEL_ID)  # type: ignore
            except Exception:
                return
        try:
            for role_id in [ROLE_PREMKA300, ROLE_PREMKAZWK, ROLE_PREMKAHORY]:
                role = guild.get_role(role_id)
                if role:
                    for m in list(role.members):
                        try:
                            await m.remove_roles(role, reason="PrimeTime reset przy starcie")
                        except Exception:
                            pass
                    self.pending[role_id].clear()
            msg = await ch.fetch_message(self.signup_message_id)
            for reaction in msg.reactions:
                emoji_str = str(reaction.emoji)
                role_id = EMOJI_TO_ROLE.get(emoji_str)
                if not role_id:
                    continue
                try:
                    async for user in reaction.users(limit=None):
                        if user.bot:
                            continue
                        try:
                            member = guild.get_member(user.id) or await guild.fetch_member(user.id)
                            role = guild.get_role(role_id)
                            if role:
                                await member.add_roles(role, reason="PrimeTime sync po starcie")
                                self.pending.setdefault(role_id, set()).add(member.id)
                        except Exception:
                            pass
                except Exception:
                    pass
        except Exception:
            pass

    async def _ensure_reactions(self, msg: discord.Message):
        order = [EMOJI_300GL, EMOJI_200OR, EMOJI_200BTH]
        have = set(str(r.emoji) for r in msg.reactions)
        for em in order:
            if em not in have:
                try:
                    await msg.add_reaction(em)
                except Exception:
                    pass

    def _role_for_emoji(self, emoji_str: str) -> Optional[int]:
        return EMOJI_TO_ROLE.get(emoji_str)

    async def _add_pending_role(self, guild: discord.Guild, user_id: int, role_id: int):
        role = guild.get_role(role_id)
        if not role:
            return
        try:
            member = guild.get_member(user_id) or await guild.fetch_member(user_id)
            await member.add_roles(role, reason="PrimeTime signup (one-shot)")
            self.pending.setdefault(role_id, set()).add(user_id)
        except Exception:
            pass

    async def _remove_pending_role_and_reaction(self, guild: discord.Guild, user_id: int, role_id: int):
        role = guild.get_role(role_id)
        if role:
            try:
                member = guild.get_member(user_id) or await guild.fetch_member(user_id)
                if role in member.roles:
                    await member.remove_roles(role, reason="PrimeTime one-shot zakończony")
            except Exception:
                pass
        if self.signup_message_id:
            try:
                ch = guild.get_channel(SIGNUP_CHANNEL_ID) or await self.fetch_channel(SIGNUP_CHANNEL_ID)  # type: ignore
                if isinstance(ch, discord.TextChannel):
                    msg = await ch.fetch_message(self.signup_message_id)
                    emoji = next((e for e,r in EMOJI_TO_ROLE.items() if r==role_id), None)
                    if emoji:
                        try:
                            member = guild.get_member(user_id) or await guild.fetch_member(user_id)
                            await msg.remove_reaction(emoji, member)
                        except Exception:
                            pass
            except Exception:
                pass

    async def on_raw_reaction_add(self, payload: discord.RawReactionActionEvent):
        if payload.guild_id != MAIN_GUILD_ID:
            return
        if self.signup_message_id is None or payload.message_id != self.signup_message_id:
            return
        if payload.user_id == self.user.id:
            return
        emoji_str = str(payload.emoji)
        role_id = self._role_for_emoji(emoji_str)
        if not role_id:
            return
        guild = self.get_guild(payload.guild_id)
        if not guild:
            return
        await self._add_pending_role(guild, payload.user_id, role_id)

    async def on_raw_reaction_remove(self, payload: discord.RawReactionActionEvent):
        if payload.guild_id != MAIN_GUILD_ID:
            return
        if self.signup_message_id is None or payload.message_id != self.signup_message_id:
            return
        emoji_str = str(payload.emoji)
        role_id = self._role_for_emoji(emoji_str)
        if not role_id:
            return
        guild = self.get_guild(payload.guild_id)
        if not guild:
            return
        try:
            member = guild.get_member(payload.user_id) or await guild.fetch_member(payload.user_id)
            role = guild.get_role(role_id)
            if role and role in member.roles:
                await member.remove_roles(role, reason="PrimeTime: usunięcie reakcji")
        except Exception:
            pass
        self.pending.get(role_id, set()).discard(payload.user_id)

    async def primetime_loop(self):
        while not self.is_closed():
            now = datetime.now(timezone.utc)
            next_tick = (now + timedelta(minutes=1)).replace(second=0, microsecond=0)
            await asyncio.sleep(max(1.0, (next_tick - now).total_seconds()))
            try:
                await self.scan_and_ping()
            except Exception:
                pass

    async def _find_recent_self_ping(self, ch: discord.TextChannel, role_id: int, within_minutes: int) -> Optional[datetime]:
        since = datetime.now(timezone.utc) - timedelta(minutes=within_minutes)
        mention = f"<@&{role_id}>"
        try:
            async for m in ch.history(after=since, limit=200, oldest_first=False):
                if not m.author:
                    continue
                if m.author.id in {SELF_BOT_ID, (self.user.id if self.user else 0)} and mention in (m.content or ""):
                    return m.created_at if m.created_at.tzinfo else m.created_at.replace(tzinfo=timezone.utc)
        except Exception:
            return None
        return None

    async def scan_and_ping(self):
        guild = self.get_guild(MAIN_GUILD_ID)
        if not guild:
            return
        ch = guild.get_channel(EM_CHANNEL_ID)
        if not isinstance(ch, discord.TextChannel):
            try:
                ch = await self.fetch_channel(EM_CHANNEL_ID)  # type: ignore
            except Exception:
                return
        if not isinstance(ch, discord.TextChannel):
            return

        now = datetime.now(timezone.utc)
        within_catchup = (now - self.start_time) < timedelta(minutes=30)
        lookback_minutes = 30 if within_catchup else 12
        since = now - timedelta(minutes=lookback_minutes)

        matched: List[Tuple[int, discord.Message]] = []
        try:
            async for msg in ch.history(after=since, limit=200, oldest_first=False):
                if msg.author and (msg.author.id == SELF_BOT_ID or msg.author.id == (self.user.id if self.user else 0)):
                    continue
                c = (msg.content or "")
                if any(s in c for s in MATCH_300GL):
                    matched.append((ROLE_PREMKA300, msg))
                elif any(s in c for s in MATCH_200OR):
                    matched.append((ROLE_PREMKAZWK, msg))
                elif any(s in c for s in MATCH_200BTH):
                    matched.append((ROLE_PREMKAHORY, msg))
        except Exception:
            return

        by_role_latest: Dict[int, discord.Message] = {}
        for role_id, m in matched:
            prev = by_role_latest.get(role_id)
            if prev is None or m.created_at > prev.created_at:
                by_role_latest[role_id] = m

        cooldown = timedelta(minutes=30)

        for role_id, msg in by_role_latest.items():
            if (last := self.last_ping.get(role_id)) and (now - last) < cooldown:
                continue

            if role_id not in self.last_ping and within_catchup:
                prev_ts = await self._find_recent_self_ping(ch, role_id, within_minutes=30)
                if prev_ts:
                    self.last_ping[role_id] = prev_ts
                    continue

            key = (role_id, msg.id)
            if key in self.announced:
                continue

            try:
                mention = f"<@&{role_id}>"
                await ch.send(f"{mention} — {msg.content.strip()}")
                self.announced.add(key)
                self.last_ping[role_id] = now
                users = list(self.pending.get(role_id, set()))
                for uid in users:
                    try:
                        await self._remove_pending_role_and_reaction(guild, uid, role_id)
                    except Exception:
                        pass
                self.pending[role_id].clear()
            except Exception:
                pass

def fmt_int(x): return f"{int(round(float(x))):,}".replace(","," ")
def _to_int(s):
    try:
        return int(re.sub(r"[^\d-]", "", str(s)) or "0")
    except:
        return 0
def _pl_dni(n:int)->str:
    return "1 dzień" if int(n)==1 else f"{int(n)} dni"
def _sev_emoji(days:int)->str:
    if days <= 1: return "🔴"
    elif days <= 9: return "🟠"
    else: return "🟢"

HUB_ID = int(os.getenv("EMOJI_HUB_ID") or 0)
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

async def load_hub_emoji(client: discord.Client):
    if not HUB_ID: return
    try:
        g = client.get_guild(HUB_ID) or await client.fetch_guild(HUB_ID)
        emojis = await g.fetch_emojis()
        for e in emojis:
            HUB_EMOJI_ID[e.name] = e.id
    except Exception:
        pass

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

def required_today(current:int,days_left:int,target:int,mult:float=1.35)->int:
    days_left=max(0,int(days_left)); current=max(0,int(current)); target=max(0,int(target))
    need_base= target/(mult**days_left); return max(0, math.ceil(need_base-current))

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

ALL_CMDS=[pomoc, patronat_cmd, liga_cmd, tytul_cmd, zbieracz_cmd]

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

client = MyClient()

if __name__ == "__main__":
    client.run(TOKEN)
