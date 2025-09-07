from __future__ import annotations
import os, re, math, logging
from typing import Dict, Optional, List, Tuple
import discord
from discord import app_commands
from dotenv import load_dotenv

load_dotenv(override=True)
TOKEN=(os.getenv("DISCORD_TOKEN") or "").strip()
OWNER_ID=os.getenv("OWNER_ID")
HUB_ID=int(os.getenv("EMOJI_HUB_ID") or 0)
if not TOKEN or len(TOKEN)<50: raise RuntimeError("Brak/niepoprawny DISCORD_TOKEN")

intents=discord.Intents.default()
class MyClient(discord.Client):
    def __init__(self): super().__init__(intents=intents); self.tree=app_commands.CommandTree(self)
    async def setup_hook(self): await self.tree.sync()
client=MyClient(); tree=client.tree

def fmt_int(x): return f"{int(round(float(x))):,}".replace(","," ")
def _to_int(s):
    try: return int(re.sub(r"[^\d-]","",str(s)) or "0")
    except: return 0

HUB_EMOJI_ID:Dict[str,int]={}
HUB_NAMES={
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
        for e in emojis: HUB_EMOJI_ID[e.name]=e.id
    except Exception as e: logging.warning(f"Nie udało się wczytać emoji z HUB_ID={HUB_ID}: {e}")

def _app(name:str)->str|None:
    eid=HUB_EMOJI_ID.get(name)
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
    for nm in RES_KEYS.get(key,[]):
        for nn in HUB_NAMES.get(nm,[nm]):
            s=_app(nn)
            if s: return s
    return UNI.get(key,"•")
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
        if pool>=need: pool-=need; lv+=1; prog=0.0
        else: prog+=pool; pool=0.0; break
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
        if k>0: total+=k*p["price"]; rem-=k*p["amount"]; buys.append((p["amount"],p["price"],k)); p["limit"]-=k
    while rem>0:
        best_i=-1; best=SINGLE_PRICE
        for i,p in enumerate(packs):
            if p["limit"]<=0: continue
            s=min(p["amount"],rem); eff=p["price"]/s
            if eff<best-1e-9: best=eff; best_i=i
        if best_i==-1: total+=rem*SINGLE_PRICE; buys.append((1,SINGLE_PRICE,rem)); rem=0
        else: p=packs[best_i]; total+=p["price"]; buys.append((p["amount"],p["price"],1)); rem=max(0,rem-p["amount"]); p["limit"]-=1
    agg:Dict[Tuple[int,int],int]={}
    for a,pr,c in buys: agg[(a,pr)]=agg.get((a,pr),0)+c
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
        if v and int(v)>0: parts.append(f"{E(k)} **{PL_NAME[k]}:** {fmt_int(v)}")
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
        if lv<10: post=f"❗ Nadwyżka: **{fmt_int(prog)}**\n⏭️ Brakuje: **{fmt_int(nxt)}**"
        else: post=f"❗ Nadwyżka po maks.: **{fmt_int(overflow or 0)}**"
        show_lv=max(1,lv); idx=show_lv-1; stats=f"({MELEE[idx]}/{RANGED[idx]}/{COURTY[idx]})"
        post+=f"\n🏛️ Poziom dekoracji: **{show_lv}**  {stats}"
        emb.add_field(name="📈 Postęp",value=post,inline=False)
    if s["charter"]>0:
        rub,plan,avg=best_ruby_cost_for_charters(s["charter"])
        emb.add_field(name=f"{E('rubies')} Koszt rubinów",value=f"Rubiny: **{fmt_int(rub)}**\nPlan:\n{plan}" if plan else f"Rubiny: **{fmt_int(rub)}**",inline=False)
        emb.set_footer(text=f"Średni koszt 1 pkt: {avg:.2f} rub.")
    if show and s.get("target_level",0):
        target=int(s["target_level"])
        if lv>=10: need=0
        else:
            need=LEVEL_COSTS[lv]-prog
            for L in range(lv+1,target): need+=LEVEL_COSTS[L]
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
        except: await i.response.send_message("Błąd (1/2).",ephemeral=True)

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
        except: await i.response.send_message("Błąd (2/2).",ephemeral=True)

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
        except: await i.response.send_message("Błąd.",ephemeral=True)

class DekorView(discord.ui.View):
    def __init__(self,uid): super().__init__(timeout=600); self.uid=uid
    async def interaction_check(self,i):
        if i.user.id!=self.uid: await i.response.send_message("To prywatny panel innego użytkownika.",ephemeral=True); return False
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

@tree.command(name="patronat",description="Panel liczenia dekoracji")
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
        else: k1,k2=weak_two(need); post+=f"🗓️ W 2 dni: {M(k1)} + {M(k2)} ({PTS[k1]}+{PTS[k2]})"
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
        except: await i.response.send_message("Błąd (1/2).",ephemeral=True)

class L2(discord.ui.Modal, title="Medale — 2/2"):
    def __init__(self,s): super().__init__(custom_id="liga:m2"); self.s=s
    copper=discord.ui.TextInput(label="Miedziany",required=False)
    stone=discord.ui.TextInput(label="Kamienny",required=False)
    wood=discord.ui.TextInput(label="Drewniany",required=False)
    async def on_submit(self,i):
        try:
            self.s["copper"]=_to_int(self.copper.value); self.s["stone"]=_to_int(self.stone.value); self.s["wood"]=_to_int(self.wood.value)
            await i.response.send_message("Zapisano (2/2). Kliknij **Zapisz**.",ephemeral=True)
        except: await i.response.send_message("Błąd (2/2).",ephemeral=True)

class LigaView(discord.ui.View):
    def __init__(self,uid): super().__init__(timeout=600); self.uid=uid
    async def interaction_check(self,i):
        if i.user.id!=self.uid: await i.response.send_message("To prywatny panel innego użytkownika.",ephemeral=True); return False
        return True
    @discord.ui.button(label="1",style=discord.ButtonStyle.primary,emoji="🎖️")
    async def a(self,i,_): await i.response.send_modal(L1(_l(self.uid)))
    @discord.ui.button(label="2",style=discord.ButtonStyle.primary,emoji="🏅")
    async def b(self,i,_): await i.response.send_modal(L2(_l(self.uid)))
    @discord.ui.button(label="Zapisz",style=discord.ButtonStyle.success,emoji="🔄")
    async def c(self,i,_): await i.response.edit_message(embed=_liga_embed(i.guild,_l(self.uid)),view=self)
    @discord.ui.button(label="Wyczyść",style=discord.ButtonStyle.danger,emoji="🧹")
    async def d(self,i,_): LIGA[self.uid]=_new_l(); await i.response.edit_message(embed=_liga_embed(i.guild,_l(self.uid)),view=self)

@tree.command(name="liga",description="Policz tytuł z medali")
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
        except: await i.response.send_message("Błąd podczas obliczeń.",ephemeral=True)

@tree.command(name="zbieracz",description="Kalkulator eventu Zbieracz")
async def zbieracz_cmd(i:discord.Interaction): await i.response.send_modal(ZbieraczModal())

@tree.command(name="pomoc",description="Lista komend")
async def pomoc(i:discord.Interaction):
    d="**/patronat** — panel dekoracji\n**/liga** — tytuł z medali\n**/zbieracz** — ile musisz dziś zdobyć"
    await i.response.send_message(embed=discord.Embed(title="📚 Pomoc",description=d,color=0x3498DB),ephemeral=True)

if OWNER_ID:
    @tree.command(name="shutdown",description="Owner: wyłącz bota")
    async def shutdown(i:discord.Interaction):
        if i.user.id!=int(OWNER_ID): return await i.response.send_message("Brak uprawnień.",ephemeral=True)
        await i.response.send_message("Wyłączam się…",ephemeral=True); await client.close()

@client.event
async def on_ready():
    logging.basicConfig(level=logging.INFO)
    await client.change_presence(activity=None,status=discord.Status.online)
    await load_hub_emoji()
    logging.info(f"Wczytano emoji z huba: {len(HUB_EMOJI_ID)}")

client.run(TOKEN)
