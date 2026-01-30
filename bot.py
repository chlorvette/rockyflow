import discord
import os
from dotenv import load_dotenv
from discord import Embed, ui
from discord.ext import commands
import random
import aiosqlite
import json
from datetime import datetime

load_dotenv("venv/.env")

COAL_EMOJI = "<:coal:1466599886647590942>"
IRON_EMOJI = "<:iron:1466599885678579835>"
GOLD_EMOJI = "<:gold:1466599884340727808>"
COINS_EMOJI = "<:coins:1466619316089917625>"
XP_EMOJI = "<:xp:1466626995793301726>"

class RockyflowBot(commands.Bot):
    user: discord.ClientUser
    db: aiosqlite.Connection

    def __init__(self):
        intents = discord.Intents.default()
        intents.message_content = True
        super().__init__(command_prefix="!", intents=intents)
    
    async def setup_hook(self):
        self.db = await aiosqlite.connect('rockyflow.db')
        await self.init_database()
        self.add_view(MiningView())
        await self.tree.sync()
        print('command tree synced')
    
    async def init_database(self):
        await self.db.execute('''
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                inventory TEXT DEFAULT '{}',
                xp INTEGER DEFAULT 0,
                coins INTEGER DEFAULT 0,
                gear TEXT DEFAULT '{}',
                current_mine TEXT DEFAULT 'starter mine',
                session_begin_time TEXT DEFAULT NULL
            )
        ''')
        await self.db.commit()
    
    async def get_user_data(self, user_id: int):
        async with self.db.execute(
            'SELECT * FROM users WHERE user_id = ?', (user_id,)
        ) as cursor:
            row = await cursor.fetchone()
            if row:
                return {
                    'user_id': row[0],
                    'inventory': json.loads(row[1]),
                    'xp': row[2],
                    'coins': row[3],
                    'gear': json.loads(row[4]),
                    'current_mine': row[5],
                    'session_begin_time': row[6]
                }
            return None
    
    async def create_user(self, user_id: int):
        await self.db.execute(
            'INSERT OR IGNORE INTO users (user_id) VALUES (?)', (user_id,)
        )
        await self.db.commit()
    
    async def update_user_data(self, user_id: int, **kwargs):
        await self.create_user(user_id)
        
        updates = []
        values = []
        for key, value in kwargs.items():
            if key in ['inventory', 'gear'] and isinstance(value, dict):
                value = json.dumps(value)
            updates.append(f'{key} = ?')
            values.append(value)
        
        values.append(user_id)
        query = f'UPDATE users SET {', '.join(updates)} WHERE user_id = ?'
        await self.db.execute(query, values)
        await self.db.commit()
    
    async def on_ready(self):
        print(f'Logged on as {self.user}!')

class MiningView(ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @ui.button(label="end session", style=discord.ButtonStyle.danger, custom_id="end_session_button")
    async def end_session(self, interaction: discord.Interaction, button: ui.Button):
        bot: RockyflowBot = interaction.client
        user_data = await bot.get_user_data(interaction.user.id)
        
        if not user_data or not user_data['session_begin_time']:
            await interaction.response.send_message("you don't have an active mining session!", ephemeral=True)
            return
        
        begin_time = datetime.fromisoformat(user_data['session_begin_time'])
        end_time = datetime.now()
        duration = (end_time - begin_time).total_seconds() / 60  # in minutes
        
        # calc rewards
        coalAmount = int(duration * random.uniform(0.5, 1.5))
        ironAmount = int(duration * random.uniform(0.3, 0.8))
        goldAmount = int(duration * random.uniform(0.1, 0.4))
        
        xpAmount = coalAmount * 2 + ironAmount * 5 + goldAmount * 10
        coinsAmount = coalAmount * 1 + ironAmount * 3 + goldAmount * 5
        
        inventory = user_data['inventory']
        inventory['coal'] = inventory.get('coal', 0) + coalAmount
        inventory['iron'] = inventory.get('iron', 0) + ironAmount
        inventory['gold'] = inventory.get('gold', 0) + goldAmount
        
        await bot.update_user_data(
            interaction.user.id,
            inventory=inventory,
            xp=user_data['xp'] + xpAmount,
            coins=user_data['coins'] + coinsAmount,
            session_begin_time=None
        )
        
        # disable end session button
        for child in self.children:
            child.disabled = True
        await interaction.response.edit_message(view=self)
        
        resultsEmbed = Embed(
            title="mining session ended!",
            color=0x737270,
            description=(
                f"**session duration:** {duration:.1f} minutes\n\n"
                f"**rewards:**\n"
                f"{COAL_EMOJI} x{coalAmount} coal\n"
                f"{IRON_EMOJI} x{ironAmount} iron\n"
                f"{GOLD_EMOJI} x{goldAmount} gold\n"
                f"{XP_EMOJI} +{xpAmount} xp\n"
                f"**balance:** {COINS_EMOJI} {user_data['coins'] + coinsAmount} coins"
            ),
        )
        resultsEmbed.set_footer(text=str(interaction.user))
        await interaction.followup.send(embed=resultsEmbed, view=SessionEndedView())

class SessionEndedView(ui.View):
    def __init__(self):
        super().__init__(timeout=None)
    
    @ui.button(label="view stats", style=discord.ButtonStyle.primary, custom_id="view_stats_button")
    async def view_stats(self, interaction: discord.Interaction, button: ui.Button):
        bot: RockyflowBot = interaction.client
        user_data = await bot.get_user_data(interaction.user.id)
        
        if not user_data:
            await interaction.response.send_message("no user data found!", ephemeral=True)
            return
        
        inventory = user_data['inventory']
        statsEmbed = Embed(
            title="your stats",
            color=0x737270,
        )
        statsEmbed.add_field(name="balance:", value=f"{COINS_EMOJI} {user_data['coins']} coins", inline=False)
        statsEmbed.add_field(name="experience:", value=f"{XP_EMOJI} {user_data['xp']} xp", inline=False)
        
        inventory_display = "\n".join([f"{k}: {v}" for k, v in inventory.items()]) if inventory else "empty"
        statsEmbed.add_field(name="inventory:", value=inventory_display, inline=False)
        statsEmbed.add_field(name="current mine:", value=user_data['current_mine'], inline=False)
        
        gear_display = "\n".join([f"{k}: {v}" for k, v in user_data['gear'].items()]) if user_data['gear'] else "no gear equipped"
        statsEmbed.add_field(name="gear:", value=gear_display, inline=False)
        
        statsEmbed.set_footer(text=str(interaction.user))
        await interaction.response.send_message(embed=statsEmbed, ephemeral=True)
    
    @ui.button(label="enter shop", style=discord.ButtonStyle.success, custom_id="enter_shop_button")
    async def enter_shop(self, interaction: discord.Interaction, button: ui.Button):
        shopEmbed = Embed(
            title="shop",
            color=0xFFD700,
            description="shop coming soon!"
        )
        await interaction.response.send_message(embed=shopEmbed, ephemeral=True)

bot = RockyflowBot()

@bot.tree.command(name="mine", description="start a mining session")
async def mine(interaction: discord.Interaction):
    user_data = await bot.get_user_data(interaction.user.id)
    
    if not user_data:
        await bot.create_user(interaction.user.id)
        user_data = await bot.get_user_data(interaction.user.id)
    
    if user_data['session_begin_time']:
        await interaction.response.send_message("you already have an active mining session! use `/endsession` or click the button to end it.")
        return
    
    # begin session
    begin_time = datetime.now().isoformat()
    await bot.update_user_data(interaction.user.id, session_begin_time=begin_time)
    
    gear_display = "\n".join([f"{k}: {v}" for k, v in user_data['gear'].items()]) if user_data['gear'] else "no gear equipped"
    
    sessionEmbed = Embed(
        title="⛏️ you began a mining session!",
        color=0x737270,
    )
    sessionEmbed.add_field(name="current gear:", value=gear_display, inline=False)
    sessionEmbed.add_field(name="current mine:", value=user_data['current_mine'], inline=False)
    sessionEmbed.add_field(name="current balance:", value=f"{COINS_EMOJI} {user_data['coins']} coins\n{XP_EMOJI} {user_data['xp']} xp", inline=False)
    sessionEmbed.set_footer(text=str(interaction.user))
    
    await interaction.response.send_message(embed=sessionEmbed, view=MiningView())

@bot.tree.command(name="endsession", description="end your current mining session")
async def end_session_command(interaction: discord.Interaction):
    user_data = await bot.get_user_data(interaction.user.id)
    
    if not user_data or not user_data['session_begin_time']:
        await interaction.response.send_message("you don't have an active mining session!")
        return
    
    begin_time = datetime.fromisoformat(user_data['session_begin_time'])
    end_time = datetime.now()
    duration = (end_time - begin_time).total_seconds() / 60
    
    # calc rewards
    coalAmount = int(duration * random.uniform(0.5, 1.5))
    ironAmount = int(duration * random.uniform(0.3, 0.8))
    goldAmount = int(duration * random.uniform(0.1, 0.4))
    
    xpAmount = coalAmount * 2 + ironAmount * 5 + goldAmount * 10
    
    inventory = user_data['inventory']
    inventory['coal'] = inventory.get('coal', 0) + coalAmount
    inventory['iron'] = inventory.get('iron', 0) + ironAmount
    inventory['gold'] = inventory.get('gold', 0) + goldAmount
    
    await bot.update_user_data(
        interaction.user.id,
        inventory=inventory,
        xp=user_data['xp'] + xpAmount,
        session_begin_time=None
    )
    
    resultsEmbed = Embed(
        title="mining session ended!",
        color=0x737270,
        description=(
            f"**session duration:** {duration:.1f} minutes\n\n"
            f"**rewards:**\n"
            f"{COAL_EMOJI} x{coalAmount} coal\n"
            f"{IRON_EMOJI} x{ironAmount} iron\n"
            f"{GOLD_EMOJI} x{goldAmount} gold\n"
            f"{XP_EMOJI} +{xpAmount} xp\n"
            f"**balance:** {COINS_EMOJI} {user_data['coins']} coins"
        ),
    )
    resultsEmbed.set_footer(text=str(interaction.user))
    await interaction.response.send_message(embed=resultsEmbed, view=SessionEndedView())

bot.run(os.environ.get('BOT-TOKEN'))