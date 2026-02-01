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

XP_EMOJI = "<:xp:1466626995793301726>"
COINS_EMOJI = "<:coins:1466619316089917625>"

with open("progression_data.json", "r") as f:
    progression_data = json.load(f)

ores = progression_data["ores"]
gear = progression_data["gear"]
items = progression_data["items"]
processing = progression_data["processing"]
mines = progression_data["mines"]

def get_highest_gear(inventory: dict) -> str:
    for pickaxe in reversed(gear):
        if pickaxe in inventory:
            return pickaxe

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
                current_mine TEXT DEFAULT 'surface_cave',
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
                    'current_mine': row[4],
                    'session_begin_time': row[5]
                }
            return None
    
    async def create_user(self, user_id: int):
        await self.db.execute(
            'INSERT OR IGNORE INTO users (user_id) VALUES (?)', (user_id,)
        )
        await self.db.execute(
            'UPDATE users SET inventory = ? WHERE user_id = ? AND inventory = ?',
            (json.dumps({"wooden_pickaxe": 1}), user_id, '{}')
        )
        await self.db.commit()
    
    async def update_user_data(self, user_id: int, **kwargs):
        await self.create_user(user_id)
        
        updates = []
        values = []
        for key, value in kwargs.items():
            if key == "inventory" and isinstance(value, dict):
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
        
        # Disable end session button first
        for child in self.children:
            child.disabled = True
        await interaction.response.edit_message(view=self)
        
        await end_mining_session(interaction, bot, disable_button=True)

# todo: test
class ShopSelect(ui.Select):
    def __init__(self, user_data: dict):
        inventory = user_data['inventory']

        options = []

        for item_key in gear.keys():
            if inventory.get(item_key, 0) == 1:
                continue
            
            options.append(discord.SelectOption(
                label=item_key.replace("_", " "),
                description=f"{gear[item_key]['price']} coins",
                value=item_key,
                emoji=gear[item_key]['emoji']
            ))

        # for item_key, price in self.gear_prices.items():
        #     item_name = item_key.replace("_", " ")
        #     if item_key not in gear:
        #         options.append(discord.SelectOption(
        #             label=item_name, 
        #             description=f"{price} coins", 
        #             value=item_key, 
        #             emoji=gear[item_key]['emoji']
        #         ))
        super().__init__(placeholder="select an item to purchase", min_values=1, max_values=1, options=options)

    async def callback(self, interaction: discord.Interaction):
        bot: RockyflowBot = interaction.client
        user_data = await bot.get_user_data(interaction.user.id)
        
        selected_item_key = self.values[0]
        item_price = gear[selected_item_key]['price']
        item_name = selected_item_key.replace("_", " ")
        
        if user_data['coins'] < item_price:
            await interaction.response.send_message(
                f"you don't have enough coins! {item_name} costs {COINS_EMOJI} {item_price} coins, but you only have {COINS_EMOJI} {user_data['coins']} coins.", 
                ephemeral=True
            )
            return
        
        # add to gear
        inventory = user_data['inventory']
        inventory[selected_item_key] = 1
        
        
        # deduct coins
        new_balance = user_data['coins'] - item_price
        
        await bot.update_user_data(
            interaction.user.id,
            inventory=inventory,
            coins=new_balance
        )
        
        purchaseEmbed = Embed(
            title="purchase successful!",
            color=0x00FF00,
            description=f"you purchased {gear[selected_item_key]['emoji']} **{item_name}**!\n\n{COINS_EMOJI} **- {item_price}** coins\n**balance:** {COINS_EMOJI} {new_balance} coins"
        )
        purchaseEmbed.set_footer(text=str(interaction.user))
        await interaction.response.send_message(embed=purchaseEmbed, ephemeral=True)
        
        # disable the select menu after responding
        self.disabled = True
        await interaction.message.edit(view=self.view)

class ShopView(ui.View):
    def __init__(self, user_data: dict):
        super().__init__(timeout=None)
        self.add_item(ShopSelect(user_data))


async def send_stats_embed(interaction: discord.Interaction, bot: RockyflowBot):
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
    
    gear_display = get_highest_gear(user_data['inventory']).replace('_', ' ') if get_highest_gear(user_data['inventory']) else "no gear equipped"
    statsEmbed.add_field(name="gear:", value=gear_display, inline=False)
    
    statsEmbed.set_footer(text=str(interaction.user))
    await interaction.response.send_message(embed=statsEmbed, ephemeral=True)

async def send_shop_embed(interaction: discord.Interaction, bot: RockyflowBot, ephemeral: bool = False):
    user_data = await bot.get_user_data(interaction.user.id)
    if not user_data:
        await bot.create_user(interaction.user.id)
        user_data = await bot.get_user_data(interaction.user.id)

    shopEmbed = Embed(
        title="shop",
        color=0xFFD700,
        description="select an item to purchase!"
    )

    value = ""
    for item_key in gear.keys():
        if user_data['inventory'].get(item_key, 0) == 1:
            continue
        value += f"**{gear[item_key]['emoji']} {item_key.replace('_', ' ')}** - {COINS_EMOJI} {gear[item_key]['price']} coins\n"

    shopEmbed.add_field(name="available items:", value=value, inline=False)
    await interaction.response.send_message(embed=shopEmbed, view=ShopView(user_data), ephemeral=ephemeral)

async def end_mining_session(interaction: discord.Interaction, bot: RockyflowBot, disable_button: bool = False):
    user_data = await bot.get_user_data(interaction.user.id)
    
    if not user_data or not user_data['session_begin_time']:
        await interaction.response.send_message("you don't have an active mining session!", ephemeral=True)
        return
    
    begin_time = datetime.fromisoformat(user_data['session_begin_time'])
    end_time = datetime.now()
    elapsed_seconds = (end_time - begin_time).total_seconds()
    duration = elapsed_seconds
    
    # calc rewards
    inventory = user_data['inventory']
    earnings = {}
    xpEarnings = 0

    while duration > 0:
        num = random.uniform(0, 1)
        chance_sum = 0
        for ore in mines[user_data['current_mine']]['available_ores'].keys():
            chance_sum += mines[user_data['current_mine']]['available_ores'][ore]
            if num <= chance_sum:
                if ores[ore][get_highest_gear(user_data['inventory'])] != 0:
                    drop = ores[ore]['drops']
                    inventory[drop] = inventory.get(drop, 0) + 1
                    if drop not in earnings:
                        earnings[drop] = 1
                    else:
                        earnings[drop] += 1
                    xpEarnings += ores[ore]['xp']
                duration -= ores[ore][get_highest_gear(user_data['inventory'])]
            
    for ore, amount in earnings.items():
        inventory[ore] = inventory.get(ore, 0) + amount
    
    await bot.update_user_data(
        interaction.user.id,
        inventory=inventory,
        xp=user_data['xp'] + xpEarnings,
        session_begin_time=None
    )
    
    description = f"**session duration:** {elapsed_seconds / 60:.1f} minutes\n**rewards:**\n"
    for ore, amount in earnings.items():
        description += f"{items[ore]['emoji']} x{amount} {ore}\n"

    description += f"{XP_EMOJI} +{xpEarnings} xp"

    resultsEmbed = Embed(
        title="mining session ended!",
        color=0x737270,
        description=description,
    )
    resultsEmbed.set_footer(text=str(interaction.user))
    
    if disable_button:
        await interaction.followup.send(embed=resultsEmbed, view=SessionEndedView())
    else:
        await interaction.response.send_message(embed=resultsEmbed, view=SessionEndedView())

class SessionEndedView(ui.View):
    def __init__(self):
        super().__init__(timeout=None)
    
    @ui.button(label="view stats", style=discord.ButtonStyle.primary, custom_id="view_stats_button")
    async def view_stats(self, interaction: discord.Interaction, button: ui.Button):
        bot: RockyflowBot = interaction.client
        await send_stats_embed(interaction, bot)
    
    @ui.button(label="enter shop", style=discord.ButtonStyle.success, custom_id="enter_shop_button")
    async def enter_shop(self, interaction: discord.Interaction, button: ui.Button):
        bot: RockyflowBot = interaction.client
        await send_shop_embed(interaction, bot, ephemeral=False)

    @ui.button(label="sell", style=discord.ButtonStyle.secondary, custom_id="sell_button")
    async def sell_items(self, interaction: discord.Interaction, button: ui.Button):
        bot: RockyflowBot = interaction.client
        user_data = await bot.get_user_data(interaction.user.id)
        if not user_data:
            await bot.create_user(interaction.user.id)
            user_data = await bot.get_user_data(interaction.user.id)

        inventory = user_data['inventory']
        
        # check if user has any sellable items
        has_items = False
        for item_key in inventory.keys():
            if item_key in items and inventory.get(item_key, 0) > 0:
                has_items = True
                break
        
        if not has_items:
            await interaction.response.send_message("you have nothing to sell!", ephemeral=True)
            return
        
        sellEmbed = Embed(
            title="sell items",
            color=0xFFD700,
            description="select items to sell from your inventory!"
        )
        await interaction.response.send_message(embed=sellEmbed, view=SellView(user_data), ephemeral=True)

class SellSelect(ui.Select):
    def __init__(self, user_data: dict):
        inventory = user_data['inventory']
        options = []
        
        for item_key in inventory.keys():
            if item_key in items and inventory.get(item_key, 0) > 0:
                amount = inventory[item_key]
                sell_price = items[item_key]['sell_price']
                options.append(discord.SelectOption(
                    label=f"{item_key.replace('_', ' ')} x{amount}",
                    description=f"{sell_price} coins each ({amount * sell_price} total)",
                    value=item_key,
                    emoji=items[item_key]['emoji']
                ))
        
        super().__init__(placeholder="select items to sell", min_values=1, max_values=min(len(options), 25), options=options)
    
    async def callback(self, interaction: discord.Interaction):
        bot: RockyflowBot = interaction.client
        user_data = await bot.get_user_data(interaction.user.id)
        
        inventory = user_data['inventory']
        coins_gained = 0
        sold_items = []
        
        for item_key in self.values:
            if item_key in inventory and inventory[item_key] > 0:
                amount = inventory[item_key]
                sell_price = items[item_key]['sell_price']
                total_price = amount * sell_price
                coins_gained += total_price
                sold_items.append(f"{items[item_key]['emoji']} x{amount} {item_key.replace('_', ' ')} for {total_price} coins")
                inventory[item_key] = 0
        
        await bot.update_user_data(
            interaction.user.id,
            inventory=inventory,
            coins=user_data['coins'] + coins_gained
        )
        
        description = "\n".join(sold_items)
        description += f"\n\n**earned:** {COINS_EMOJI} {coins_gained} coins\n**balance:** {COINS_EMOJI} {user_data['coins'] + coins_gained} coins"
        
        sellEmbed = Embed(
            title="items sold!",
            color=0xFFD700,
            description=description
        )
        sellEmbed.set_footer(text=str(interaction.user))
        await interaction.response.send_message(embed=sellEmbed, ephemeral=True)

class SellView(ui.View):
    def __init__(self, user_data: dict):
        super().__init__(timeout=None)
        self.add_item(SellSelect(user_data))

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
    
    gear_display = get_highest_gear(user_data['inventory']).replace('_', ' ') if get_highest_gear(user_data['inventory']) else "no gear equipped"
    
    sessionEmbed = Embed(
        title="you began a mining session!",
        color=0x737270,
    )
    sessionEmbed.add_field(name="current gear:", value=gear_display, inline=False)
    sessionEmbed.add_field(name="current mine:", value=user_data['current_mine'].replace('_', ' '), inline=False)
    sessionEmbed.add_field(name="current balance:", value=f"{COINS_EMOJI} {user_data['coins']} coins\n{XP_EMOJI} {user_data['xp']} xp", inline=False)
    sessionEmbed.set_footer(text=str(interaction.user))
    
    await interaction.response.send_message(embed=sessionEmbed, view=MiningView())

@bot.tree.command(name="endsession", description="end your current mining session")
async def end_session_command(interaction: discord.Interaction):
    await end_mining_session(interaction, bot, disable_button=False)

@bot.tree.command(name="inventory", description="view your inventory")
async def inventory_command(interaction: discord.Interaction):
    user_data = await bot.get_user_data(interaction.user.id)

    if not user_data:
        await bot.create_user(interaction.user.id)
        user_data = await bot.get_user_data(interaction.user.id)

    inventory = user_data['inventory']
    inventory_display = "\n".join([f"{ores[k]['emoji']} x{v}" for k, v in inventory.items()]) if inventory else "empty"

    inventory_embed = Embed(
        title="your inventory",
        color=0x737270,
        description=inventory_display
    )
    inventory_embed.set_footer(text=str(interaction.user))
    await interaction.response.send_message(embed=inventory_embed, ephemeral=True)

@bot.tree.command(name="shop", description="open the shop")
async def shop_command(interaction: discord.Interaction):
    await send_shop_embed(interaction, bot, ephemeral=True)

@bot.tree.command(name="stats", description="view your stats")
async def stats_command(interaction: discord.Interaction):
    await send_stats_embed(interaction, bot)

bot.run(os.environ.get('BOT-TOKEN'))