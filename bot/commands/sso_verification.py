import discord
from discord.ext import commands
from discord import app_commands, Interaction
import logging
import json
from shared.redis_client import get_redis_client
from shared.keycloak_client import keycloak_client

# Role Mapping: Keycloak Group Path -> Discord Role ID
GROUP_MAPPING = {
    "/Dobrovolníci/E-koučové": 1022056088062918707,
    "/Dobrovolníci/Moderátoři Discord": 1022049035705655316,
    "/Dobrovolníci/Moderátoři fórum": 1252505707534745681,
    "/Pracovníci NP/Koordinátoři": 1191708314673877124
}

class SSOStatusView(discord.ui.View):
    def __init__(self, bot: commands.Bot):
        super().__init__(timeout=None)
        self.bot = bot

    @discord.ui.button(label="Ověřit stav (Check Status)", style=discord.ButtonStyle.primary, emoji="🔄", custom_id="sso_check_status")
    async def btn_check_status(self, interaction: Interaction, button: discord.ui.Button):
        await interaction.response.defer(ephemeral=True)
        
        r = await get_redis_client()
        user_id = str(interaction.user.id)
        
        # 1. Check if user is linked in Redis
        kc_user_id = await r.get(f"sso:keycloak_link:{user_id}")
        if not kc_user_id:
            await interaction.followup.send(
                "❌ **Tvůj Discord účet není propojen s NePornu ID.**\n"
                "Klikni na tlačítko 'Propojit účet' výše a přihlas se.",
                ephemeral=True
            )
            return

        # 2. Fetch groups from Keycloak
        groups = await keycloak_client.get_user_groups(kc_user_id)
        if not groups and not isinstance(groups, list):
            await interaction.followup.send("❌ Nepodařilo se načíst data z Keycloaku. Zkus to prosím později.", ephemeral=True)
            return

        # 3. Map groups to roles
        assigned_roles = []
        failed_roles = []
        
        group_paths = [g.get("path") for g in groups]
        logging.info(f"SSO Check for {interaction.user.name} ({user_id}): KC_UID={kc_user_id}, Groups={group_paths}")

        for group_path, role_id in GROUP_MAPPING.items():
            if group_path in group_paths:
                role = interaction.guild.get_role(role_id)
                if role:
                    if role not in interaction.user.roles:
                        try:
                            await interaction.user.add_roles(role, reason="SSO Verification")
                            assigned_roles.append(role.name)
                        except Exception as e:
                            logging.error(f"Failed to add role {role.name} to {user_id}: {e}")
                            failed_roles.append(role.name)
                else:
                    logging.warning(f"Role ID {role_id} not found in guild for group {group_path}")

        if assigned_roles:
            msg = f"✅ **Úspěšně ověřeno!** Byly ti přiděleny role: {', '.join(assigned_roles)}"
            if failed_roles:
                msg += f"\n⚠️ Nepodařilo se přidělit: {', '.join(failed_roles)} (Kontaktuj adminy)"
            await interaction.followup.send(msg, ephemeral=True)
        else:
            await interaction.followup.send(
                "ℹ️ **Propojení je v pořádku**, ale ve tvém NePornu ID nemáš žádné speciální skupiny (např. E-kouč).\n"
                "Pokud si myslíš, že je to chyba, kontaktuj svého koordinátora.",
                ephemeral=True
            )

class SSOVerificationCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    propojit_group = app_commands.Group(name="propojit", description="Propojení tvého Discordu s NePornu ID (Keycloak)")

    @propojit_group.command(name="nepornu", description="Propojí tvůj Discord s interním systémem NePornu")
    async def sso_link(self, interaction: Interaction):
        """Sends an interactive message to link Keycloak and Discord"""
        embed = discord.Embed(
            title="🔗 Propojení s NePornu ID",
            description=(
                "Tento příkaz slouží k propojení tvého Discord účtu s interním systémem NePornu (Keycloak).\n\n"
                "**Postup:**\n"
                "1. Klikni na tlačítko **'Propojit účet'** níže.\n"
                "2. Přihlas se svými údaji (nebo si je vyžádej od koordinátora).\n"
                "3. Po úspěšném přihlášení a schválení se vrať sem.\n"
                "4. Klikni na tlačítko **'Ověřit stav'**.\n\n"
                "*Tip: Pokud jsi E-kouč, Moderátor nebo Koordinátor, automaticky získáš své role.*"
            ),
            color=discord.Color.blue()
        )
        
        view = SSOStatusView(self.bot)
        # Add link button
        link_button = discord.ui.Button(
            label="Propojit účet (Link SSO)",
            url="https://portal.nepornu.cz",
            style=discord.ButtonStyle.link,
            emoji="🔑"
        )
        view.add_item(link_button)
        
        await interaction.response.send_message(embed=embed, view=view)

async def setup(bot: commands.Bot):
    cog = SSOVerificationCog(bot)
    await bot.add_cog(cog)
    # Register persistent view
    bot.add_view(SSOStatusView(bot))
