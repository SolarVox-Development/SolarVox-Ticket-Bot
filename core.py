import discord
from discord.ext import commands, tasks
from discord import app_commands
import asyncio
import datetime
import aiohttp
import io
import zoneinfo
import pytz

# ==== CONFIG ====
TOKEN = "" # Bot Token here
AUTH_PASSWORD = "" # Put Your Password for sending panel here  
GUILD_ID =   # your server ID
TICKET_CATEGORY_ID =  # category for tickets
LOGO_URL = "" # Put your Logo URL

COLOR_PRIMARY = discord.Color.dark_blue()

intents = discord.Intents.all()
intents.message_content = True

bot = commands.Bot(command_prefix="!", intents=intents)


# ==== Ticket Dropdown ====
class TicketTypeSelect(discord.ui.Select):
    def __init__(self):
        options = [
            discord.SelectOption(label="Support", description="Get general support")
            discord.SelectOption(label="Scammer Report", description="Report a scam")
        ]
        super().__init__(placeholder="Select ticket type...", min_values=1, max_values=1, options=options)

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        ticket_type = self.values[0]
        guild = interaction.guild
        overwrites = {
            guild.default_role: discord.PermissionOverwrite(view_channel=False),
            interaction.user: discord.PermissionOverwrite(view_channel=True, send_messages=True, attach_files=True)
        }
        category = guild.get_channel(TICKET_CATEGORY_ID)
        channel = await guild.create_text_channel(
            f"{ticket_type.lower()}-{interaction.user.name}",
            overwrites=overwrites,
            category=category
        )

        tz = pytz.timezone("America/New_York")
        now = datetime.datetime.now(tz)
        support_hours_start = 9
        support_hours_end = 21
        user_hour = now.hour

        if support_hours_start <= user_hour < support_hours_end:
            response_note = "Our support team will respond as soon as possible."
        else:
            response_note = "⚠️ Our support team is currently offline. It may take longer for a response."

        embed = discord.Embed(
            title=f"🎫 》{ticket_type} Ticket Opened",
            description=(
                f"**Ticket Info:**\n"
                f"• Type: {ticket_type}\n"
                f"• Created by: {interaction.user.mention}\n"
                f"• Created at: {now.strftime('%Y-%m-%d %H:%M:%S %Z')}\n\n"
                f"{response_note}\n──────────\n"
                f"Click the button below to close this ticket when done."
            ),
            color=COLOR_PRIMARY
        )
        embed.set_thumbnail(url=LOGO_URL)
        await channel.send(embed=embed, view=CloseTicketView(interaction.user))
        await interaction.followup.send(f"✅ Ticket created: {channel.mention}", ephemeral=True)
        bot.loop.create_task(ticket_timeout(channel, interaction.user))

class TicketDropdownView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        self.add_item(TicketTypeSelect())

# ==== Close Ticket ====
class CloseTicketView(discord.ui.View):
    def __init__(self, ticket_owner):
        super().__init__(timeout=None)
        self.ticket_owner = ticket_owner

    @discord.ui.button(label="Close Ticket", style=discord.ButtonStyle.danger)
    async def close(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(ephemeral=True)
        if interaction.user != self.ticket_owner and not interaction.user.guild_permissions.manage_channels:
            return await interaction.followup.send(
                "❌ Only the ticket owner or a support member can close this.",
                ephemeral=True
            )
        await handle_ticket_close(interaction.channel, self.ticket_owner)
        await interaction.followup.send("🔒 Ticket closed.", ephemeral=True)

# ==== Ticket Timeout ====
async def ticket_timeout(channel, user):
    def check(msg):
        return msg.channel == channel

    while True:
        try:
            await bot.wait_for("message", timeout=43200, check=check)
        except asyncio.TimeoutError:
            await channel.send(f"⚠️ {user.mention}, your ticket has been inactive for 12 hours. It will close in 12 hours if no activity.")
            try:
                await bot.wait_for("message", timeout=43200, check=check)
            except asyncio.TimeoutError:
                await handle_ticket_close(channel, user)
                break

# ==== Handle Ticket Close ====
async def handle_ticket_close(channel, ticket_owner):
    messages = [msg async for msg in channel.history(limit=None, oldest_first=True)]
    log_text = "".join(f"[{msg.created_at.strftime('%Y-%m-%d %H:%M:%S')}] {msg.author}: {msg.content}\n" for msg in messages)
    file = discord.File(io.BytesIO(log_text.encode()), filename=f"{channel.name}_log.txt")

    if ticket_owner:
        try:
            embed = discord.Embed(
                title="📄 》Your Ticket Was Closed",
                description=f"Your ticket `{channel.name}` has been closed.\nLog file attached. You can rate the support below.",
                color=COLOR_PRIMARY
            )
            embed.set_thumbnail(url=LOGO_URL)
            await ticket_owner.send(embed=embed, file=file, view=RatingView())
        except discord.Forbidden:
            embed = discord.Embed(
                title="📄 》Ticket Closed",
                description=f"Ticket `{channel.name}` has been closed.\nLog file attached.",
                color=COLOR_PRIMARY
            )
            embed.set_thumbnail(url=LOGO_URL)
            await channel.send(embed=embed, file=file, view=RatingView())
    await asyncio.sleep(5)
    await channel.delete()

# ==== Rating ====
class RatingSelect(discord.ui.Select):
    def __init__(self):
        options = [
            discord.SelectOption(label="⭐", description="1 star", value="1"),
            discord.SelectOption(label="⭐⭐", description="2 stars", value="2"),
            discord.SelectOption(label="⭐⭐⭐", description="3 stars", value="3"),
            discord.SelectOption(label="⭐⭐⭐⭐", description="4 stars", value="4"),
            discord.SelectOption(label="⭐⭐⭐⭐⭐", description="5 stars", value="5"),
        ]
        super().__init__(placeholder="Rate the support", min_values=1, max_values=1, options=options)

    async def callback(self, interaction: discord.Interaction):
        rating = self.values[0]
        await interaction.response.send_message(f"Thank you! You rated this support **{rating} star(s)**.", ephemeral=True)

class RatingView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        self.add_item(RatingSelect())

# ==== Send Ticket Panel ====
@bot.tree.command(name="send", description="Send the Ticket Assistant ticket panel", guild=discord.Object(id=GUILD_ID))
@app_commands.describe(channel="Select the channel to send the ticket panel")
@app_commands.checks.has_permissions(manage_channels=True)
async def send_ticket_embed(interaction: discord.Interaction, channel: discord.TextChannel):
    modal = discord.ui.Modal(title="Authorization Required")
    password_input = discord.ui.TextInput(
        label="Enter Authorization Password",
        style=discord.TextStyle.short,
        placeholder="Enter password to continue",
        required=True
    )
    modal.add_item(password_input)

    async def modal_callback(interaction_modal: discord.Interaction):
        if password_input.value != AUTH_PASSWORD:
            await interaction_modal.response.send_message("❌ Invalid password.", ephemeral=True)
            return

        embed = discord.Embed(
            title="<:favicon:1432643438070992926> 》SolarVox Ticket System",
            description="**🕘 Working Hours:** ``3 PM – 9 PM``\nTickets opened outside working hours may take longer for a response.\n──────────",
            color=COLOR_PRIMARY
        )
        embed.set_thumbnail(url=LOGO_URL)
        embed.add_field(name="Tickets", value="Need help? Pick your ticket type below and our team will assist you!", inline=False)
        embed.set_footer(text="SolarVox • Ticket System", icon_url=LOGO_URL)

        await channel.send(embed=embed, view=TicketDropdownView())
        await interaction_modal.response.send_message(f"✅ Ticket panel sent in {channel.mention}", ephemeral=True)

    modal.on_submit = modal_callback
    await interaction.response.send_modal(modal)

# ==== Moderation Commands ====
@bot.tree.command(name="ban", description="Ban a member", guild=discord.Object(id=GUILD_ID))
@app_commands.checks.has_permissions(ban_members=True)
async def ban(interaction: discord.Interaction, member: discord.Member, reason: str = "No reason provided"):
    embed = discord.Embed(title="🔨 》User Banned", description=f"{member.mention} was banned.\nReason: {reason}\n──────────", color=COLOR_PRIMARY)
    embed.set_thumbnail(url=LOGO_URL)
    await member.ban(reason=reason)
    await interaction.response.send_message(embed=embed)

@bot.tree.command(name="kick", description="Kick a member", guild=discord.Object(id=GUILD_ID))
@app_commands.checks.has_permissions(kick_members=True)
async def kick(interaction: discord.Interaction, member: discord.Member, reason: str = "No reason provided"):
    embed = discord.Embed(title="👢 》User Kicked", description=f"{member.mention} was kicked.\nReason: {reason}\n──────────", color=COLOR_PRIMARY)
    embed.set_thumbnail(url=LOGO_URL)
    await member.kick(reason=reason)
    await interaction.response.send_message(embed=embed)

@bot.tree.command(name="warn", description="Warn a member", guild=discord.Object(id=GUILD_ID))
@app_commands.checks.has_permissions(manage_messages=True)
async def warn(interaction: discord.Interaction, member: discord.Member, reason: str = "No reason provided"):
    embed = discord.Embed(title="⚠️ 》User Warned", description=f"{member.mention} has been warned.\nReason: {reason}\n──────────", color=COLOR_PRIMARY)
    embed.set_thumbnail(url=LOGO_URL)
    await interaction.response.send_message(embed=embed)

# ==== Server Info ====
@bot.tree.command(name="serverinfo", description="Show server info", guild=discord.Object(id=GUILD_ID))
async def serverinfo(interaction: discord.Interaction):
    guild = interaction.guild
    embed = discord.Embed(title=f"📊 》Server Info - {guild.name}", description="──────────", color=COLOR_PRIMARY)
    embed.set_thumbnail(url=LOGO_URL)
    embed.set_footer(text=f"Server ID: {guild.id}")
    embed.add_field(name="Owner", value=guild.owner, inline=True)
    embed.add_field(name="Members", value=guild.member_count, inline=True)
    embed.add_field(name="Roles", value=len(guild.roles), inline=True)
    embed.add_field(name="Boosts", value=guild.premium_subscription_count, inline=True)
    embed.add_field(name="Created", value=guild.created_at.strftime("%Y-%m-%d"), inline=True)
    embed.add_field(name="Channels", value=len(guild.channels), inline=True)
    embed.add_field(name="Verification Level", value=str(guild.verification_level), inline=True)
    await interaction.response.send_message(embed=embed)


# ==== On Ready ====
@bot.event
async def on_ready():
    await bot.tree.sync(guild=discord.Object(id=GUILD_ID))
    activity = discord.Activity(type=discord.ActivityType.watching, name="Tickets")
    await bot.change_presence(status=discord.Status.dnd, activity=activity)
    print(f"{bot.user} is online and Watching Tickets")

bot.run(TOKEN)
