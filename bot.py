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

ore_emojis = {
    "coal": COAL_EMOJI,
    "iron": IRON_EMOJI,
    "gold": GOLD_EMOJI,
}

WOODEN_PICKAXE_EMOJI = "<:wooden_pickaxe:1467307932483059920>"
STONE_PICKAXE_EMOJI = "<:stone_pickaxe:1467307778937978944>"
IRON_PICKAXE_EMOJI = "<:iron_pickaxe:1467308051592778002>"
GOLD_PICKAXE_EMOJI = "<:gold_pickaxe:1467308186821464104>"

gear_emojis = {
    "wooden_pickaxe": WOODEN_PICKAXE_EMOJI,
    "stone_pickaxe": STONE_PICKAXE_EMOJI,
    "iron_pickaxe": IRON_PICKAXE_EMOJI,
    "gold_pickaxe": GOLD_PICKAXE_EMOJI,
}

gear_levels = {
    "wooden_pickaxe": 1,
    "stone_pickaxe": 2,
    "iron_pickaxe": 3,
    "gold_pickaxe": 4,
}

def get_highest_gear(gear: dict) -> str:
    if not gear:
        return "no gear equipped"
    owned_gear = [name for name in gear.keys() if gear[name]]
    if not owned_gear:
        return "no gear equipped"
    highest = max(owned_gear, key=lambda x: gear_levels.get(x, 0))
    emoji = gear_emojis.get(highest, "")
    return f"{emoji} {highest.replace('_', ' ')}"

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
        query = f"UPDATE users SET {', '.join(updates)} WHERE user_id = ?"
        await self.db.execute(query, values)
        await self.db.commit()
    
    async def on_ready(self):
        if not hasattr(self, '_synced'):
            self._synced = True
            synced = await self.tree.sync()
            print(f'Logged on as {self.user}!')
            print(f'Synced {len(synced)} command(s)')

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
        gear_multiplier = gear_levels.get(get_highest_gear(user_data['gear']).replace(" ", "_").lower(), 1) + 2
        coalAmount = int(duration * random.uniform(0.5, 1.5)) * gear_multiplier
        ironAmount = int(duration * random.uniform(0.3, 0.8)) * gear_multiplier
        goldAmount = int(duration * random.uniform(0.1, 0.4)) * gear_multiplier
        
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
                f"**balance:** {COINS_EMOJI} {user_data['coins']} coins"
            ),
        )
        resultsEmbed.set_footer(text=str(interaction.user))
        await interaction.followup.send(embed=resultsEmbed, view=SessionEndedView())

class ShopSelect(ui.Select):
    def __init__(self, gear: dict):
        self.gear_prices = {
            "wooden_pickaxe": 10,
            "stone_pickaxe": 50,
            "iron_pickaxe": 200,
            "gold_pickaxe": 500,
        }

        gear = gear or {}

        options = []
        
        for item_key, price in self.gear_prices.items():
            item_name = item_key.replace("_", " ")
            if item_key not in gear:
                options.append(discord.SelectOption(
                    label=item_name, 
                    description=f"{price} coins", 
                    value=item_key, 
                    emoji=gear_emojis[item_key]
                ))
        super().__init__(placeholder="select an item to purchase", min_values=1, max_values=1, options=options)

    async def callback(self, interaction: discord.Interaction):
        bot: RockyflowBot = interaction.client
        user_data = await bot.get_user_data(interaction.user.id)
        
        selected_item = self.values[0]
        item_price = self.gear_prices[selected_item]
        item_name = selected_item.replace("_", " ")
        
        if user_data['coins'] < item_price:
            await interaction.response.send_message(
                f"you don't have enough coins! {item_name} costs {COINS_EMOJI} {item_price} coins, but you only have {COINS_EMOJI} {user_data['coins']} coins.", 
                ephemeral=True
            )
            return
        
        # add to gear
        gear = user_data['gear']
        gear[selected_item] = True
        
        
        # deduct coins
        new_balance = user_data['coins'] - item_price
        
        await bot.update_user_data(
            interaction.user.id,
            gear=gear,
            coins=new_balance
        )
        
        purchaseEmbed = Embed(
            title="purchase successful!",
            color=0x00FF00,
            description=f"you purchased {gear_emojis[selected_item]} **{item_name}**!\n\n{COINS_EMOJI} **-{item_price}** coins\n**balance:** {COINS_EMOJI} {new_balance} coins"
        )
        purchaseEmbed.set_footer(text=str(interaction.user))
        await interaction.response.send_message(embed=purchaseEmbed, ephemeral=True)
        
        # disable the select menu after responding
        self.disabled = True
        await interaction.message.edit(view=self.view)

class ShopView(ui.View):
    def __init__(self, gear: dict):
        super().__init__(timeout=None)
        self.add_item(ShopSelect(gear))

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
        
        gear_display = get_highest_gear(user_data['gear'])
        statsEmbed.add_field(name="gear:", value=gear_display, inline=False)
        
        statsEmbed.set_footer(text=str(interaction.user))
        await interaction.response.send_message(embed=statsEmbed, ephemeral=True)
    
    @ui.button(label="enter shop", style=discord.ButtonStyle.success, custom_id="enter_shop_button")
    async def enter_shop(self, interaction: discord.Interaction, button: ui.Button):
        bot: RockyflowBot = interaction.client
        user_data = await bot.get_user_data(interaction.user.id)
        if not user_data:
            await bot.create_user(interaction.user.id)
            user_data = await bot.get_user_data(interaction.user.id)

        shopEmbed = Embed(
            title="shop",
            color=0xFFD700,
            description="select an item to purchase!"
        )
        shopEmbed.add_field(name="available items:", value=(
            f"{WOODEN_PICKAXE_EMOJI} **wooden pickaxe** - {COINS_EMOJI} 10 coins\n"
            f"{STONE_PICKAXE_EMOJI} **stone pickaxe** - {COINS_EMOJI} 50 coins\n"
            f"{IRON_PICKAXE_EMOJI} **iron pickaxe** - {COINS_EMOJI} 200 coins\n"
            f"{GOLD_PICKAXE_EMOJI} **gold pickaxe** - {COINS_EMOJI} 500 coins\n"
        ), inline=False)
        await interaction.response.send_message(embed=shopEmbed, view=ShopView(user_data['inventory']))

    @ui.button(label="sell", style=discord.ButtonStyle.secondary, custom_id="sell_button")
    async def sell_items(self, interaction: discord.Interaction, button: ui.Button):
        bot: RockyflowBot = interaction.client
        user_data = await bot.get_user_data(interaction.user.id)
        if not user_data:
            await bot.create_user(interaction.user.id)
            user_data = await bot.get_user_data(interaction.user.id)

        inventory = user_data['inventory']
        coal_amount = inventory.get('coal', 0)
        iron_amount = inventory.get('iron', 0)
        gold_amount = inventory.get('gold', 0)

        if coal_amount == 0 and iron_amount == 0 and gold_amount == 0:
            await interaction.response.send_message("you have nothing to sell!", ephemeral=True)
            return

        coins_gained = coal_amount * 1 + iron_amount * 3 + gold_amount * 5

        inventory['coal'] = 0
        inventory['iron'] = 0
        inventory['gold'] = 0

        await bot.update_user_data(
            interaction.user.id,
            inventory=inventory,
            coins=user_data['coins'] + coins_gained
        )

        sellEmbed = Embed(
            title="items sold!",
            color=0xFFD700,
            description=(
                f"{COAL_EMOJI} x{coal_amount} coal for {coal_amount} coins\n"
                f"{IRON_EMOJI} x{iron_amount} iron for {iron_amount * 3} coins\n"
                f"{GOLD_EMOJI} x{gold_amount} gold for {gold_amount * 5} coins\n\n"
                f"**earned:** {COINS_EMOJI} {coins_gained} coins\n"
                f"**balance:** {COINS_EMOJI} {user_data['coins'] + coins_gained} coins"
            )
        )
        sellEmbed.set_footer(text=str(interaction.user))
        await interaction.response.send_message(embed=sellEmbed)

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
    
    gear_display = get_highest_gear(user_data['gear'])
    
    sessionEmbed = Embed(
        title="you began a mining session!",
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
            f"**session duration:** {duration:.1f} minutes\n"
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

@bot.tree.command(name="inventory", description="view your inventory")
async def inventory_command(interaction: discord.Interaction):
    user_data = await bot.get_user_data(interaction.user.id)

    if not user_data:
        await bot.create_user(interaction.user.id)
        user_data = await bot.get_user_data(interaction.user.id)

    inventory = user_data['inventory']
    inventory_display = "\n".join([f"{ore_emojis.get(k, '')} x{v}" for k, v in inventory.items()]) if inventory else "empty"

    inventory_embed = Embed(
        title="your inventory",
        color=0x737270,
        description=inventory_display
    )
    inventory_embed.set_footer(text=str(interaction.user))
    await interaction.response.send_message(embed=inventory_embed, ephemeral=True)

@bot.tree.command(name="shop", description="open the shop")
async def shop_command(interaction: discord.Interaction):
    user_data = await bot.get_user_data(interaction.user.id)
    
    if not user_data:
        await bot.create_user(interaction.user.id)
        user_data = await bot.get_user_data(interaction.user.id)

    shopEmbed = Embed(
        title="shop",
        color=0xFFD700,
        description="select an item to purchase!"
    )
    shopEmbed.add_field(name="available items:", value=(
        f"**{WOODEN_PICKAXE_EMOJI} wooden pickaxe** - {COINS_EMOJI} 10 coins\n"
        f"**{STONE_PICKAXE_EMOJI} stone pickaxe** - {COINS_EMOJI} 50 coins\n"
        f"**{IRON_PICKAXE_EMOJI} iron pickaxe** - {COINS_EMOJI} 200 coins\n"
        f"**{GOLD_PICKAXE_EMOJI} gold pickaxe** - {COINS_EMOJI} 500 coins\n"
    ), inline=False)
    await interaction.response.send_message(embed=shopEmbed, view=ShopView(user_data['gear']), ephemeral=True)

bot.run(os.environ.get('BOT-TOKEN'))